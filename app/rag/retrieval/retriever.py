# =============================================================
# app/rag/retrieval/retriever.py
# Facade del sistema di retrieval.
# Orchestrata: dense search + sparse BM25 → RRF fusion → MMR → reranker
# =============================================================

from __future__ import annotations  #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import asyncio
from dataclasses import dataclass  #messo sopra una classe, ti da automaticamente __init__, __repr__, __eq__, ect
from functools import lru_cache
from typing import Any
from loguru import logger
from app.core.settings import get_settings   #ur custom

settings = get_settings()

@dataclass
class RetrievedChunk:
    """Chunk recuperato con score e metadata."""
    text: str
    score: float
    chunk_id: str
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    doc_type: str
    metadata: dict[str, Any]

async def retrieve(
    query: str,
    tenant_slug: str,
    tenant_id: str,
    collection_id: str | None = None,
    top_k: int | None = None,
    filters: dict | None = None,
) -> list[RetrievedChunk]:
    """
    Pipeline di retrieval completa (async — non blocca l'event loop FastAPI).
    Flusso:
    1. Embed query (dense vector)
    2. Dense search su Qdrant (semantic)
    3. Sparse SPLADE search su Qdrant (keyword)
    4. RRF fusion dei due risultati
    5. MMR diversification
    6. Reranking cross-encoder (riduce da top_k a reranker_top_k)
    Args:
        query: domanda dell'utente
        tenant_slug: per collection name e filtro tenant
        tenant_id: per filtro isolamento multi-tenant
        collection_id: filtra per collection specifica (opzionale)
        top_k: override del top_k di config
        filters: filtri metadata aggiuntivi (doc_type, data, ecc.)
    Returns:
        Lista di RetrievedChunk ordinati per rilevanza
    """
    k = top_k or settings.retriever_top_k
    logger.debug(f"Retrieval: query='{query[:50]}...', top_k={k}")
    from app.core.embeddings import aembed_query  #versione async — non blocca event loop
    query_vector = await aembed_query(query)
    from app.core.vectorstore import get_async_qdrant_client, get_collection_name
    from qdrant_client.http import models as qmodels
    client = get_async_qdrant_client()
    collection_name = get_collection_name(tenant_slug)
    must_conditions = [  #costruisci filtro qdrant
        qmodels.FieldCondition(
            key="tenant_id",
            match=qmodels.MatchValue(value=tenant_id)  #🔥🔥SEMPRE TENANT ISOLATION!!
        )
    ]
    if collection_id:
        must_conditions.append(
            qmodels.FieldCondition(
                key="collection_id",
                match=qmodels.MatchValue(value=collection_id)
            )
        )
    if filters:
        for key, value in filters.items():
            must_conditions.append(
                qmodels.FieldCondition(
                    key=key,
                    match=qmodels.MatchValue(value=value)
                )
            )
    qdrant_filter = qmodels.Filter(must=must_conditions)
    #🔥🔥Dense Search (semantic similarity)
    dense_results = await client.search(
        collection_name=collection_name,
        query_vector=qmodels.NamedVector(name="dense", vector=query_vector),
        query_filter=qdrant_filter,
        limit=k,
        with_payload=True,
        score_threshold=0.3,
    )
    #🔥🔥Sparse Search (SPLADE keyword) se abilitato
    sparse_results = []
    if settings.qdrant_use_sparse:
        try:
            sparse_vector = await _abuild_sparse_vector(query)  #async: carica modello in thread pool
            sparse_results = await client.search(
                collection_name=collection_name,
                query_vector=qmodels.NamedSparseVector(name="sparse", vector=sparse_vector),
                query_filter=qdrant_filter,
                limit=k,
                with_payload=True,
            )
        except Exception as e:
            logger.warning(f"Sparse search fallita: {e}")

    fused = _rrf_fusion(dense_results, sparse_results, k=k)  #🔥🔥RRF fusion

    if settings.retriever_strategy == "mmr" and len(fused) > 1:
        fused = _mmr_rerank(query_vector, fused, lambda_param=settings.retriever_mmr_lambda)
    if settings.reranker_enabled and len(fused) > 1:
        fused = await _async_cross_encoder_rerank(query, fused, top_k=settings.reranker_top_k)

    #⭐️⭐️pipeline:
    #1. Hybrid Search (dense + sparse SPLADE) → Top 20 risultati
    #2. RRF fusion → 1 ranking unico con i migliori di entrambi
    #3. MMR → diversifica, penalizza chunk troppo simili
    #4. Cross-Encoder reranker → Top 5 precisi

    chunks = []
    for item in fused:
        payload = item["payload"]
        chunks.append(RetrievedChunk(
            text=payload.get("text", ""),
            score=item["score"],
            chunk_id=item["id"],
            document_id=payload.get("document_id", ""),
            filename=payload.get("filename", ""),
            page_number=payload.get("page_number"),
            chunk_index=payload.get("chunk_index", 0),
            doc_type=payload.get("doc_type", "generic"),
            metadata=payload,
        ))
    logger.debug(f"Retrieval completato: {len(chunks)} chunk")
    return chunks


@lru_cache(maxsize=1)
def _get_splade_model() -> Any:
    """Singleton modello SPLADE — caricato una sola volta come embedding e reranker."""
    from fastembed import SparseTextEmbedding
    logger.info("Caricamento modello SPLADE sparse", model="prithivida/Splade_PP_en_v1")
    return SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

def _build_sparse_vector(query: str) -> Any:  #🔥utilizzo Sparse Search w SPLADE type (better than BM25 type base)
    """Costruisce vettore sparso SPLADE per la query."""
    model = _get_splade_model()  #singleton: non ricreato ad ogni chiamata
    vectors = list(model.embed([query]))
    v = vectors[0]
    return {"indices": v.indices.tolist(), "values": v.values.tolist()}

async def _abuild_sparse_vector(query: str) -> Any:
    """Versione async di _build_sparse_vector — eseguita in thread pool per non bloccare l'event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _build_sparse_vector, query)

def _rrf_fusion(  #🔥🔥RRF fusion technique!! formula score=1/(rank+k). k=60 stabilizza la curva, rank è la posizione nel risultato.
    dense: list,  #risultati semantic search Qdrant
    sparse: list,  #risultati keyword search
    k: int = 60,  #k=60 stabilizza la curva
) -> list[dict]:
    """
    Reciprocal Rank Fusion — combina risultati dense e sparse.
    RRF score = Σ 1/(k + rank_i) per ogni lista.
    k = 60 è il valore standard dalla letteratura.
    """
    scores: dict[str, dict] = {}
    for rank, result in enumerate(dense):  #enumerate() iteri e ti da anche l'index 
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {
                "id": rid, 
                "payload": result.payload, 
                "score": 0.0
            }   #pk ricorda scores dict[str, dict], e lo inizializzi
        scores[rid]["score"] += 1.0 / (60 + rank + 1)   #accedi all campo target e fai update. rank+1 perché enumerate parte da 0, quindi formula è 1/(k + rank) quindi e.g. per il primo risultato rank=0 quindi 1/(60+0+1)=1/61, per il secondo rank=1 quindi 1/(60+1+1)=1/62, ecc. in questo modo i primi risultati sono piu bassi e hanno un boost maggiore
    for rank, result in enumerate(sparse):
        rid = str(result.id)
        if rid not in scores:
            scores[rid] = {
                "id": rid, 
                "payload": result.payload, 
                "score": 0.0
            }
        scores[rid]["score"] += 1.0 / (60 + rank + 1)   #accedi all campo target e fai update
    return sorted( scores.values(), key=lambda x: x["score"], reverse=True )    #prende tutti i chunks, e li ordin per score decrescente.

def _mmr_rerank(      #Re-Ranking technique, formuala  λ*relevance-(1-λ)*similarity. QUESTA MIA VERSIONE è meno potente della vera versione di mmr!!
    query_vector: list[float],
    results: list[dict],
    lambda_param: float = 0.5,
    top_k: int | None = None,
) -> list[dict]:
    """
    Maximal Marginal Relevance — diversifica i risultati.
    formula: MMR = λ*relevance - (1-λ)*max_similarity_to_selected
    Bilancia rilevanza (similarity con query) e diversità (dissimilarity tra chunk).
    lambda_param: 0=massima diversità, 1=massima rilevanza
    """
    if not results:
        return results
    k = top_k or len(results)
    selected = []
    remaining = list( results )  #clone
    #Vettori dei chunk (usiamo lo score come proxy della similarity)
    while len(selected) < k and remaining:   #continue finche lista selected non supera k(number) e che ci sono sempre ancora elementi dentro list 'remaining'
        if not selected:
            #prima iterazione: prendi il più rilevante cioe il primo della lista(quello che ha il massimo score) !
            best = remaining[0]
        else:
            #MMR: massimizza λ*relevance - (1-λ)*max_similarity_to_selected
            best_score = float("-inf")   #equivale a -∞
            best = remaining[0]
            for candidate in remaining:
                relevance = candidate["score"]
                # Similarità con i già selezionati (approssimazione tramite score overlap)
                max_sim = max(
                    _score_similarity(candidate, sel) for sel in selected  #run function here qua sotto
                )  #max() prende solo il valore max calcolato tra tutti quelli calcolati
                mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim   #formula mmr, prima parte → qualità del chunk seconda parte → penalità se è troppo simile
                if mmr_score > best_score:
                    best_score = mmr_score
                    best = candidate
        selected.append(best)
        remaining.remove(best)
        #sposti il best nei risultati finali e lo rimuovi da quelli rimanenti
    return selected  #return the bests

def _score_similarity(a: dict, b: dict) -> float:
    """Similarità approssimata tra due chunk basata sul filename e chunk_index."""
    pa, pb = a["payload"], b["payload"]
    if pa.get("document_id") == pb.get("document_id"):  #verifica se provengono dalla stessa fonte (se è cosi alta similarità se chunk adiacenti )
        diff = abs( pa.get("chunk_index", 0) - pb.get("chunk_index", 0) )
        #prende l'indice dei chunks e.g. pa["chunk_index"]=5  pb["chunk_index"]=6  e 
        #calcola la distanza tra i chunk (), più sono vicini più sono simili, quindi similarity è 1 quando diff=0, e decresce linearmente fino a 0 quando diff>=10 (puoi regolare questo valore in base alla lunghezza media dei tuoi chunk, ma 10 è un buon punto di partenza)
        return max(0, 1.0 - diff * 0.1)   #questa è la formula equivale a similarity = 1 - 0.1 * diff. e.g. diff=0  1-0*0.1 -> 1  result similarity = 1.0 (massima similarita),  se è invece diff=1 (chunks adiacenti) ... result similarity = 0.9
    return 0.0

def _cross_encoder_rerank(  #ReRanking technique usando Cross-Encoder (NON Bi-Encoder)
    query: str,
    results: list[dict],
    top_k: int,
) -> list[dict]:
    """
    Reranking con cross-encoder BAAI/bge-reranker-base.
    Più preciso del bi-encoder per la rilevanza finale.
    Riduce da initial_k (20) a top_k (5).
    """
    from app.core.embeddings import get_reranker_model
    reranker = get_reranker_model()
    if not reranker:  #se download fallito or altri problemi
        return results[:top_k]  #return solo i primi top_k senza aver fatto reranking technique
    pairs = [ (query, r["payload"].get("text", "")) for r in results ]   #per ogni item in results, couple {myquery, r["payload"].get("text")}
    scores = reranker.predict(pairs)  #il modello valuta ogni coppia, e assegna un punteggio di rilevanza. più alto è il punteggio, più rilevante è il chunk rispetto alla query.
    for result, score in zip(results, scores):  #zip accoppia gli elementi che sono nello stesso index (xk sono in 2 liste separate) 
        result["rerank_score"] = float(score)   #update
    reranked = sorted(results, key=lambda x: x.get("rerank_score", 0), reverse=True)
    logger.debug(f"Reranking: {len(results)} → {top_k} chunk")
    return reranked[:top_k]

async def _async_cross_encoder_rerank(query: str, results: list[dict], top_k: int) -> list[dict]:
    """Versione async di _cross_encoder_rerank — eseguita in thread pool per non bloccare l'event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _cross_encoder_rerank, query, results, top_k)


