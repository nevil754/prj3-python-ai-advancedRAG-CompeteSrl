# =============================================================
# app/rag/ingestion/pipeline.py
# Orchestra la pipeline completa: parse→clean→chunk→embed→upsert.
# Chiamato dal task Celery ingest_document.
# =============================================================

from __future__ import annotations  #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import hashlib   #x fare hashing 
import uuid
from pathlib import Path
from typing import Any
from loguru import logger   #x logging strutturato
from app.rag.ingestion.parser import parse_document  #ur custom
from app.rag.ingestion.cleaner import clean_text  #ur custom
from app.rag.ingestion.chunker import chunk_document
from app.rag.ingestion.metadata import build_chunk_metadata
from app.core.embeddings import embed_texts
from app.core.vectorstore import get_qdrant_client, get_collection_name, ensure_collection
from app.core.settings import get_settings


settings = get_settings()

def run_ingestion_pipeline(
    tenant_id: str,
    tenant_slug: str,
    document_id: str,
    file_path: str,
    collection_id: str | None = None,
) -> dict[str, Any]:
    """
    Pipeline completa di ingestion.
    Flusso:
    1. Parse → ParsedDocument (testo + pagine + tabelle)
    2. Clean → testo pulito
    3. Chunk → lista di Chunk
    4. Embed → vettori float per ogni chunk
    5. Upsert → inserimento in Qdrant con payload metadata
    Returns:
        dict con chunk_count, page_count, collection_name
    """
    path = Path(file_path)
    filename = path.name
    file_type = path.suffix
    logger.info(
        "Pipeline ingestion avviata",
        file=filename,
        tenant=tenant_slug,
        document_id=document_id,
    )
    parsed = parse_document(file_path)
    logger.debug( f"Parsing: {parsed.page_count} pagine, {len(parsed.text)} chars" )
    clean = clean_text(parsed.text)
    logger.debug( f"Pulizia: { len(parsed.text) } → { len(clean) } chars" )
    base_metadata = {
        "tenant_id": tenant_id,
        "document_id": document_id,
        "filename": filename,
    }
    chunks = chunk_document( clean, pages=parsed.pages, base_metadata=base_metadata )   #🔥🔥🔥 HERE FAI IL CHUNCKING!! passi il text pulito - le pagine ok - i metadata ok
    logger.debug( f"Chunking: {len(chunks)} chunk" )
    if not chunks:
        raise ValueError(f"Nessun chunk estratto dal documento {filename}")
    texts = [ c.text for c in chunks ]  #estrai solo il test e crei array
    vectors = embed_texts(texts)   #🔥🔥🔥HERE ACCADE EMBEDDING DEI DOCS!!
    logger.debug( f"Embedding: {len(vectors)} vettori generati" )
    collection_name = ensure_collection( tenant_slug, settings.qdrant_force_recreate )
    client = get_qdrant_client()
    from qdrant_client.http import models as qmodels  #models serve per ottenere PointStruct Filter FieldCondition MatchValue FilterSelector
    points = []
    for chunk, vector in zip( chunks, vectors ):   #zip itera su piu liste (o sequenze) in parallelo, mettendo insieme gli elementi che sono nella stessa posizione index, e ottieni qualcosa come [(Xelems),(Xelems),(Xelems)]
        payload = build_chunk_metadata(
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            filename=filename, 
            chunk_index=chunk.chunk_index, 
            page_number=chunk.page_number, 
            file_type=file_type, 
            document_text_sample=clean[:500], 
        )  #payload che viene aggiunto per ogni vettore, serve per ogni vettore per eseguire i filtri!! molto importante 
        payload["text"] = chunk.text  #aggiungi nel payload anche il testo del chunk
        points.append( qmodels.PointStruct(  #obj che rappresenta un singolo punto vettoriale dentro qdrant 
            id=str(uuid.uuid4()),
            vector={"dense": vector},   #visto che vectro puo essere e.g. [23, 45, 67] allora otteniamo e.g. {"dense": [23, 45, 67]}
            payload=payload,
        ) )
            #ogni chunk diventa e.g.
            # {
            #   "id": "uuid",
            #   "vector": [0.1, 0.2, ...],
            #   "payload": {
            #     "text": "...",
            #     "tenant_id": "...",
            #     "doc_type": "...",
            #     ...
            #   }
            # }
    batch_size = 100   #qdrant supporta inserimenti a batch, quindi invece di fare 1 upsert per ogni punto, facciamo 1 upsert ogni 100 punti
    for i in range( 0, len(points), batch_size ):   #slices 0-99, 100-199, ect
        batch = points[i:i + batch_size]   #prendi il blocco di 100 elems
        client.upsert(collection_name=collection_name, points=batch)  #🔥upsert fa update+insert command, quindi crei una nuova riga se non esisteva altrimenti la aggiorni
        logger.debug(f"Upserted batch {i // batch_size + 1}: { len(batch) } punti")
    logger.info(
        "Pipeline ingestion completata",
        file=filename,
        chunks=len(chunks),
        collection=collection_name,
    )
    return {
        "chunk_count": len(chunks),
        "page_count": parsed.page_count,
        "collection_name": collection_name,
    }


