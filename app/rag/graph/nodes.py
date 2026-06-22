# =============================================================
# app/rag/graph/nodes.py
# Ogni funzione è un nodo del grafo LangGraph.
# Riceve lo stato, lo aggiorna, ritorna le chiavi modificate.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import time
from loguru import logger
from app.rag.graph.state import RAGState


async def node_route(state: RAGState) -> dict:
    """Classifica la query e imposta il percorso."""
    from app.rag.agents.router_agent import route_query
    route = await route_query(state["question"])
    logger.debug(f"Grafo: route → {route}")
    return {"route": route}

async def node_load_session(state: RAGState) -> dict:
    """Carica la short-term memory dalla sessione Redis."""
    from app.core.redis_client import TenantRedis
    redis = TenantRedis( tenant_id=state["tenant_id"] )
    messages = await redis.get_session( state["conversation_id"] )
    return {"session_messages": messages}

async def node_retrieve(state: RAGState) -> dict:
    """Retrieval ibrido: dense + sparse search → RRF → MMR → reranker."""
    from app.rag.retrieval.retriever import retrieve
    start = time.perf_counter()
    chunks = await retrieve(
        query=state["question"],
        tenant_slug=state["tenant_slug"],
        tenant_id=state["tenant_id"],
        collection_id=state.get("collection_id"),
    )
    elapsed = round( (time.perf_counter() - start) * 1000 )   #tempo trascorso in ms
    logger.debug(f"Retrieval: {len(chunks)} chunk in {elapsed}ms")
    return {"retrieved_chunks": chunks}

async def node_web_search(state: RAGState) -> dict:
    """Ricerca web con Tavily/DDGS."""
    from app.rag.agents.web_agent import web_search_and_answer
    results = await web_search_and_answer(state["question"])
    return {"web_results": results}

async def node_generate(state: RAGState) -> dict:
    """Genera la risposta RAG con l'LLM."""
    from app.rag.generation.chain import arun_rag_chain
    start = time.perf_counter()
    result = await arun_rag_chain(   #version no streaming
        question=state["question"],
        chunks=state.get("retrieved_chunks", []),
        session_messages=state.get("session_messages", []),
    )
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "tokens_in": result.get("tokens_in", 0),
        "tokens_out": result.get("tokens_out", 0),
        "latency_ms": result.get("latency_ms", 0),
    }

async def node_generate_web(state: RAGState) -> dict:
    """Ritorna la risposta dal web agent."""
    web = state.get("web_results") or {}
    return {
        "answer": web.get("answer", "Nessun risultato trovato."),
        "sources": web.get("sources", []),
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
    }

async def node_check_hallucination(state: RAGState) -> dict:
    """Calcola hallucination score sulla risposta."""
    from app.rag.generation.hallucination import check_faithfulness
    score = await check_faithfulness(
        question=state["question"],
        answer=state.get("answer", ""),
        chunks=state.get("retrieved_chunks", []),
    )
    return {"hallucination_score": score}

async def node_save_to_memory(state: RAGState) -> dict:
    """Aggiorna la sessione Redis con i nuovi messaggi."""
    from app.core.redis_client import TenantRedis
    redis = TenantRedis(tenant_id=state["tenant_id"])
    await redis.append_message(
        state["conversation_id"],
        {"role": "user", "content": state["question"]},
    )
    await redis.append_message(
        state["conversation_id"],
        {"role": "assistant", "content": state.get("answer", "")},
    )
    return {}

