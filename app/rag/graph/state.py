# =============================================================
# app/rag/graph/state.py
# Definisce il TypedDict di stato del grafo LangGraph.
# Ogni nodo legge e scrive su questo stato condiviso.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from typing import Any, TypedDict
from app.rag.retrieval.retriever import RetrievedChunk  #ur custom


class RAGState(TypedDict):
    """
    Stato condiviso tra tutti i nodi del grafo LangGraph.
    Ogni nodo riceve questo dict e ritorna un dict con le chiavi aggiornate.
    """
    #Input
    question: str
    conversation_id: str
    tenant_id: str
    tenant_slug: str
    user_id: str
    collection_id: str | None
    mode: str                          # rag | web | sql | general
    # Risultati intermedi
    route: str | None                  # decisione del router
    retrieved_chunks: list[RetrievedChunk]
    session_messages: list[dict]
    web_results: dict | None
    # Output finale
    answer: str
    sources: list[dict]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    hallucination_score: float | None
    error: str | None


