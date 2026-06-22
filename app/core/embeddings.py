# app/core/embeddings.py
# Wrapper fastembed per BAAI/BGE-M3.
# Lazy loading — il modello viene caricato solo alla prima chiamata.
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import asyncio
from functools import lru_cache
from typing import Any
from loguru import logger


@lru_cache(maxsize=1)   #decoratore che trasforma la funzione in un singleton, quindi get_qdrant_client() ritorna sempre la stessa istanza di QdrantClient, evitando overhead di connessioni multiple
def get_embedding_model() -> Any:
    """
    Carica e ritorna il modello fastembed.
    Singleton, il modello da 500MB viene caricato una sola volta.
    Il modello viene cercato prima nella cache_dir (evita re-download🔥),
    poi scaricato da HuggingFace se non presente.
    """
    from app.core.settings import get_settings
    settings = get_settings()
    from fastembed import TextEmbedding
    logger.info(
        "Caricamento modello embedding",
        model=settings.embeddings_model,
        cache_dir=settings.embeddings_cache_dir,
    )  #log strutturato, x essere letto chiarmanet da opentelemetry/ELK/ect
    model = TextEmbedding(   #creazione model
        model_name=settings.embeddings_model,  #ovviamnete scarica il model da HuggingFace e lo mette in cache_dir="./models" o lo prende da li se era gia scaricato
        cache_dir=settings.embeddings_cache_dir,
        max_length=512,   #max token per chunk — BAAI/BGE-M3 supporta 8192 ma 512 è perfect!
        threads=4,        #4 thread per batch processing
    )
    logger.info("Modello embedding caricato", model=settings.embeddings_model)  #log strutturato
    return model

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Genera embedding per una lista di testi.
    Usato durante l'ingestion per vettorizzare i chunk.
    Args:
        texts: lista di stringhe da vettorizzare
    Returns:
        Lista di vettori float (uno per testo)
    """
    from app.core.settings import get_settings
    settings = get_settings()
    model = get_embedding_model()
    batch_size = settings.embeddings_batch_size
    logger.debug(f"Embedding {len(texts)} testi in batch da {batch_size}")
    # fastembed ritorna un generator — converti in lista
    vectors = list( model.embed(texts, batch_size=batch_size) )   #🔥🔥🔥HERE ACCADE EMBEDDING DEI DOCS!!
    #🔥i modelli retrieval di solito hanno 2 modalita: document embedding e query embedding, quindi con BGE utilizziamo embed(mydocument) e query_embed(myquery)
    #otterrai qualcosa come 
    # [
    # array([-0.1115,  0.0097,  0.0052,  0.0195, ...], dtype=float32),
    # array([-0.1019,  0.0635, -0.0332,  0.0522, ...], dtype=float32)
    # ]
    return [v.tolist() for v in vectors]   #converts array([0.1, 0.2])(array numpy) -> [0.1, 0.2] perché Qdrant vuole liste normali per lavorare!!

def embed_query(text: str) -> list[float]:
    """
    Genera embedding per una singola query.
    Più veloce di embed_texts per query singole perché salta il batching!
    Args:
        text: query dell'utente
    Returns:
        Vettore float della query
    """
    model = get_embedding_model()
    vectors = list( model.query_embed([text]) )  #🔥🔥here accada l'embedding docs!!
    #🔥🔥i modelli retrieval di solito hanno 2 modalita: document embedding e query embedding, quindi con BGE utilizziamo embed(myDocument) e query_embed(myQuery)
    return vectors[0].tolist()  #return il primo elem [0] xk hai passato [query] una lista con 1 solo elem


async def aembed_texts(texts: list[str]) -> list[list[float]]:  #async
    """
    Versione async di embed_texts.
    fastembed è sincrono, eseguiamo in un thread pool per non bloccare l'event loop.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_texts, texts)

async def aembed_query(text: str) -> list[float]:  #async
    """Versione async di embed_query."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embed_query, text)

def get_embedding_dimension() -> int:
    """
    Ritorna la dimensione del vettore per il modello corrente.
    Necessario quando si crea una collection Qdrant.
    e.g.
    BAAI/BGE-M3: 1024 dimensioni
    nomic-embed-text: 768 dimensioni
    """
    model = get_embedding_model()
    test_vector = list(model.embed(["test"]))[0]   #dummy x ottenere la dimension del vettore
    return len(test_vector)

@lru_cache(maxsize=1)
def get_reranker_model() -> Any:
    """
    Carica il modello di reranking cross-encoder.
    Usato da app/rag/retrieval/reranker.py dopo il retrieval iniziale.
    io ho scelto BAAI/bge-reranker-base ottimo buon bilanciamento velocità/qualità!
    """
    from app.core.settings import get_settings
    settings = get_settings()
    if not settings.reranker_enabled:
        return None
    from sentence_transformers import CrossEncoder  #🔥CrossEncoder è il wrapper
    logger.info("Caricamento reranker", model=settings.reranker_model)  #log strutturato
    reranker = CrossEncoder(
        settings.reranker_model,
        max_length=512,  #max token per chunk
    )  #gli altri setups in file config.yaml in reranking cioe top_k e initial_k verranno usati da altre parti
    #🔥reranking CrossEncoder fa (query, documento) -> score. è piu lento dell'embeddings.
    logger.info("Reranker caricato", model=settings.reranker_model)  #log strutturato
    return reranker


