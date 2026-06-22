# =============================================================
# app/workers/ingestion_tasks.py
# Task Celery per l'ingestion asincrona dei documenti.
# Eseguiti dai celery-worker-default in background.
# =============================================================

from __future__ import annotations  #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import time
from uuid import UUID
from celery import shared_task  #create tasks that can be called independently of any class instance
from loguru import logger   #x logging strutturato
from sqlalchemy import text   #x query sql manuali
from app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,                #permette accesso a self (il classico self per l'istanza stessa)
    max_retries=3,            #massimo 3 tentativi
    default_retry_delay=60,   #60secs tra i retries
    acks_late=True,   #🔥il task viene confermato successfully solo DOPO il completamento 
    reject_on_worker_lost=True,   #se worker crasha il task torna in coda!
    name="app.workers.ingestion_tasks.ingest_document",
)
def ingest_document(
    self,  #istanza della task Celery
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
    collection_id: str | None = None,
) -> dict:
    """
    Pipeline completa di ingestion per un singolo documento.
    Flusso:
    1. Aggiorna status → 'running' in SQL Server
    2. Parse documento (docling → unstructured fallback)
    3. Pulizia testo
    4. Chunking
    5. Embedding chunks (fastembed)
    6. Upsert in Qdrant
    7. Aggiorna status → 'done' + chunk_count
    8. Invalida cache query Redis (doc nuovo = cache stale)
    Args:
        tenant_id: UUID del tenant
        tenant_slug: slug per schema switching SQL Server
        document_id: UUID del documento in SQL Server
        file_path: path assoluto del file sul filesystem
        collection_id: UUID collection Qdrant (opzionale)
    """
    from app.db.sqlserver import tenant_db
    from app.core.redis_client import TenantRedis
    from app.rag.ingestion.pipeline import run_ingestion_pipeline  #ur custom
    task_id = self.request.id   #con celery il self.request contiene metadata della chiamata del task
    log = logger.bind(  #.bind permette di aggiungere campi personalizzati al Logger, che saranno inclusi in tutti i log successivi fatti con questo logger
        task_id=task_id,
        tenant=tenant_slug,
        document_id=document_id,
    )
    log.info("Inizio ingestion documento")
    with tenant_db.get_session(tenant_slug) as session:
        session.execute(
            text("""
                UPDATE ingestion_jobs
                SET status = 'running',
                    started_at = SYSUTCDATETIME(),
                    celery_task_id = :task_id
                WHERE document_id = :doc_id
            """),
            {"task_id": task_id, "doc_id": document_id}
        )   #in tab ingestion_jobs filtra x document_id, e modifica cols celery_task_id, started_at, status
        session.execute(
            text("UPDATE documents SET status = 'processing' WHERE id = :id"),
            {"id": document_id}
        )
    try:
        start = time.time()   #start timer 
        # 2-6. Pipeline completa: parse -> chunk -> embed -> upsert Qdrant
        result = run_ingestion_pipeline(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            document_id=document_id,
            file_path=file_path,
            collection_id=collection_id,
        )
        elapsed_ms = round((time.time() - start) * 1000)    #calcolo tempo trascorso in ms
        log.info(
            "Pipeline completata",
            chunks=result["chunk_count"],
            elapsed_ms=elapsed_ms,
        )
        with tenant_db.get_session(tenant_slug) as session:
            session.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status = 'done', 
                        finished_at = SYSUTCDATETIME(), 
                        progress_pct = 100
                    WHERE document_id = :doc_id
                """),
                {"doc_id": document_id}
            )
            session.execute(
                text("""
                    UPDATE documents
                    SET status = 'ready',
                        chunk_count = :chunks,
                        page_count = :pages,
                        updated_at = SYSUTCDATETIME()
                    WHERE id = :id
                """),
                {
                    "chunks": result["chunk_count"],
                    "pages": result.get("page_count"),
                    "id": document_id,
                }
            )
        import asyncio
        redis = TenantRedis(tenant_id=tenant_id)
        invalidated = asyncio.run(redis.invalidate_query_cache())
        log.info(f"Cache invalidata: {invalidated} chiavi")
        return {
            "status": "done",
            "document_id": document_id,
            "chunk_count": result["chunk_count"],
            "elapsed_ms": elapsed_ms,
        }
    
    except Exception as exc:
        log.error(f"Ingestion fallita: {exc}")
        with tenant_db.get_session(tenant_slug) as session:
            retry_count = self.request.retries
            is_final = retry_count >= self.max_retries  #visto che c'è >= allora python fa diventare is_final un boolean
            session.execute(
                text("""
                    UPDATE ingestion_jobs
                    SET status = :status,
                        error_msg = :err,
                        retry_count = :retries,
                        finished_at = CASE WHEN :is_final = 1 THEN GETUTCDATE() ELSE NULL END
                    WHERE document_id = :doc_id
                """),
                {
                    "status": "failed" if is_final else "queued",
                    "err": str(exc)[:2000],  #prendi solo i primi 2k chars
                    "retries": retry_count + 1,
                    "is_final": 1 if is_final else 0,   #1 = True, 0 = False
                    "doc_id": document_id,
                }
            )
            if is_final:
                session.execute(
                    text("UPDATE documents SET status = 'error' WHERE id = :id"),
                    {"id": document_id}
                )
        if is_final:
            raise exc  #propaga l'eccezione originale, non MaxRetriesExceededError
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))  #backoff esponenziale

@celery_app.task(
    bind=True,      #permette accesso a self (il classico self per l'istanza stessa)
    max_retries=2,
    acks_late=True,   #🔥il task viene confermato successfully solo DOPO il completamento
    name="app.workers.ingestion_tasks.reprocess_document",
)
def reprocess_document(
    self,
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
) -> dict:
    """
    Riprocessa un documento già ingerito.
    Usato quando cambiano i parametri di chunking o il modello di embedding.
    Prima cancella i vecchi vettori da Qdrant, poi reingestisce.
    """
    from app.core.vectorstore import get_qdrant_client, get_collection_name  #ur custom
    from qdrant_client.http import models as qmodels  #QDRANT models ti da disponibili PointStruct, Filter, Distance, VectorParams, ...
    client = get_qdrant_client()
    collection = get_collection_name(tenant_slug)
    client.delete(
        collection_name=collection,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="document_id",
                    match=qmodels.MatchValue(value=document_id)
                )]
            )
        )
    )
    logger.info(f"Vecchi vettori cancellati per documento {document_id}")
    task = ingest_document.apply_async(
        args=[tenant_id, tenant_slug, document_id, file_path],
        queue="low",
    )
    return {"status": "queued", "task_id": task.id, "document_id": document_id}

