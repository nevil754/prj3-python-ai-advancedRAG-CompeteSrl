# Qdrant client singleton + gestione collection per tenant.
# Ogni tenant ha la sua collection separata in Qdrant.
from __future__ import annotations
from functools import lru_cache  #x singleton cache
from typing import Any   #x typing generico python
from loguru import logger
from qdrant_client import AsyncQdrantClient, QdrantClient  #client sincrono easincrono per qdrant
from qdrant_client.http import models as qmodels  #modelli/schema qdrant
from qdrant_client.http.exceptions import UnexpectedResponse   #errore qdrant

@lru_cache(maxsize=1)    #decoratore che trasforma la funzione in un singleton, quindi get_qdrant_client() ritorna sempre la stessa istanza di QdrantClient, evitando overhead di connessioni multiple
def get_qdrant_client() -> QdrantClient:  
    """
    Ritorna il client Qdrant sincrono (singleton).
    Usato nei worker Celery e nei task di ingestion.
    """
    from app.core.settings import get_settings  #ur custom settings 
    settings = get_settings()
    logger.info("Connessione Qdrant", url=settings.qdrant_url)
    kwargs: dict[str, Any] = {"url": settings.qdrant_url}  #costruisce parametri dinamici, edit x tutti
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key  #edit only if settings.qdrant_api_key is true/present
    return QdrantClient(**kwargs)  #equivale a QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key[questo modificato solo nella condition here qua sopra] ) se api_key è presente, altrimenti senza api_key


@lru_cache(maxsize=1)  #cache per singleton
def get_async_qdrant_client() -> AsyncQdrantClient:   #return async qdrant client
    """
    Ritorna il client Qdrant Asincrono (singleton).
    Usato nelle route FastAPI per non bloccare l'event loop.
    """
    from app.core.settings import get_settings
    settings = get_settings()
    kwargs: dict[str, Any] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return AsyncQdrantClient(**kwargs)   #return async client con params updated

def get_collection_name(tenant_slug: str) -> str:
    """
    Genera il nome della collection Qdrant per un tenant.
    Convenzione: tenant_{slug}_documents
    Args:
        tenant_slug: es. "acme-corp" -> "tenant_acme_corp_documents"
    """
    safe_slug = tenant_slug.replace("-", "_").lower()  #i - non sono validi nei nomi delle collection, quindi usiamo '_' invece.
    return f"tenant_{safe_slug}_documents"  #slug w '..documents' finale

def get_memory_collection_name(tenant_slug: str) -> str:
    """Collection per la semantic memory (fatti utente estratti da Zep-like (Zep è un plugin per la memory, ma io faccio molto meglio tutto custom e adatto a me) layer!)."""
    safe_slug = tenant_slug.replace("-", "_").lower()
    return f"tenant_{safe_slug}_memory"  #slug w '..memory' finale

def ensure_collection(
    tenant_slug: str,
    force_recreate: bool = False,
) -> str:
    """
    Crea la collection Qdrant per un tenant se non esiste.
    Idempotente, chiamabile più volte senza effetti collaterali.
    Args:
        tenant_slug: slug del tenant
        force_recreate: se True, cancella e ricrea la collection
    Returns:
        Nome della collection creata/esistente
    """
    from app.core.settings import get_settings    #ur custom settings
    from app.core.embeddings import get_embedding_dimension    #ur custom
    settings = get_settings()
    client = get_qdrant_client()
    collection_name = get_collection_name(tenant_slug)
    try:
        existing = client.get_collection(collection_name)
        if not force_recreate:   #ricordi, force_recreate è False di default, pero se è True allora significa che la collection deve essere creata
            logger.debug(f"Collection già esistente: {collection_name}")
            return collection_name
        logger.warning(f"force_recreate=True — cancello collection {collection_name}")
        client.delete_collection(collection_name)  #🔥DELETE COLLECTION
    except UnexpectedResponse:
        pass  #anche se catturi un errore, non è un problema, significa solo che la collection non esiste e quindi here continuiamo
    dimension = get_embedding_dimension()

    vectors_config: dict[str, Any] = {  #dizionario python
        #vettori densi per semantic search
        "dense": qmodels.VectorParams(    #VectorParams serve per definire dimensione/metrica/storage/ect per vettore
            size=dimension,
            distance=qmodels.Distance[settings.qdrant_distance],   #🔥configurazione dinamica della distanza (cosine, euclidean, dot_product) per la ricerca semantica, definita in settings
            on_disk=True,   #🔥🔥vettori su ssd per risparmiare RAM! praticamente obbligatorio in enterprise
        )
    }
    #vettori sparsi per BM25 hybrid search
    sparse_vectors_config = None   #variable
    if settings.qdrant_use_sparse:
        sparse_vectors_config = {
            "sparse": qmodels.SparseVectorParams( index=qmodels.SparseIndexParams(on_disk=True)  #configurazione dell'indice sparse
            )
        }
    client.create_collection(
        collection_name=collection_name,
        vectors_config=vectors_config,    #ur setted here qua sopra
        sparse_vectors_config=sparse_vectors_config,    #ur setted here qua sopra
        on_disk_payload=settings.qdrant_on_disk_payload,
        #ottimizza per ricerche frequenti
        optimizers_config=qmodels.OptimizersConfigDiff(   #🔥set gli ottimizzatori interni di Qdrant, DATA LA QUANTITA DI DATAS UTILIZZI TECHNIQUES DI INDEXES DIFFERENTI
            indexing_threshold=20_000,  #quando una segment supera 20.000 punti, crea l'indice HNSW per ricerche più veloci
            memmap_threshold=50_000,   #quando una segment supera 50.000 punti, sposta i dati su disco (memmap) per risparmiare RAM
        ),
    )
    #crea indexes su tenant_id per filtri veloci
    client.create_payload_index(
        collection_name=collection_name,
        field_name="tenant_id",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,  #KEYWORD significa stringa esatta. e.g. se tenant_id = "abc123", puoi fare filter=tenant_id="abc123" e trova tutti i documenti di quel tenant matchato 
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="document_id",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="doc_type",
        field_schema=qmodels.PayloadSchemaType.KEYWORD,
    )
    logger.info(     #logging
        "Collection Qdrant creata",
        collection=collection_name,
        dimension=dimension,
        sparse=settings.qdrant_use_sparse,
    )
    return collection_name

async def aensure_collection( tenant_slug: str, force_recreate: bool = False ) -> str:  #versione Async di ensure_collection
    """Versione async di ensure_collection."""
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor( None, ensure_collection, tenant_slug, force_recreate )

async def adelete_tenant_collections(tenant_slug: str) -> None:  #cancella tutte le collections di un target tenant
    """
    Cancella tutte le collection Qdrant di un tenant.
    Chiamato durante l'offboarding del tenant (quando un cliente è cancellato dalla piattaforma).
    """
    client = get_async_qdrant_client()
    for get_name in [ get_collection_name, get_memory_collection_name ]:  #è come dire functions = [function1, function2], quindi ora iteri e nel first cycle get_name = get_collection_name, nel secondo ciclo get_name = get_memory_collection_name
        name = get_name(tenant_slug)
        try:
            await client.delete_collection(name)  #in questo modo nel FIRST cycle eseguo un delete su tenant_{safe_slug}_documents, mentre nel SECOND cycle eseguo un delete su tenant_{safe_slug}_memory
            logger.info(f"Collection cancellata: {name}")
        except Exception as e:
            logger.warning(f"Impossibile cancellare collection {name}: {e}")


