# =============================================================
# app/rag/graph/graph.py
# Assembla e compila il grafo LangGraph completo.
# Il grafo è il motore che orchestra tutti i nodi RAG.
# =============================================================


from __future__ import annotations    #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from functools import lru_cache
from langgraph.graph import END, StateGraph
from app.rag.graph.state import RAGState
from app.rag.graph.nodes import (
    node_route,
    node_load_session,
    node_retrieve,
    node_web_search,
    node_generate,
    node_generate_web,
    node_check_hallucination,
    node_save_to_memory,
)  #ur custom
from app.rag.graph.edges import edge_route_decision   #ur custom


@lru_cache(maxsize=1)    #decoratore che trasforma la funzione in un singleton, quindi get_rag_graph() ritorna sempre la stessa istanza di StateGraph, evitando overhead di connessioni multiple (sfrutta la cache)
def get_rag_graph():
    """
    Costruisce e compila il grafo LangGraph.
    Singleton — compilato una sola volta all'avvio.
    Grafo:
        START
          ↓
        route → classifica query
          ↓ (condizionale)
        ┌─ retrieve → generate ─────────────────┐
        └─ web_search → generate_web ───────────┤
                                                 ↓
                                    check_hallucination
                                                 ↓
                                    save_to_memory
                                                 ↓
                                               END
    """
    graph = StateGraph(RAGState)
    #add nodes
    graph.add_node("route",               node_route)
    graph.add_node("load_session",        node_load_session)
    graph.add_node("retrieve",            node_retrieve)
    graph.add_node("web_search",          node_web_search)
    graph.add_node("generate",            node_generate)
    graph.add_node("generate_web",        node_generate_web)
    graph.add_node("check_hallucination", node_check_hallucination)
    graph.add_node("save_to_memory",      node_save_to_memory)
    #entry point
    graph.set_entry_point("load_session")
    #edges
    graph.add_edge("load_session", "route")
    #conditiona edge after node 'route'
    graph.add_conditional_edges(
        "route",
        edge_route_decision,
        {
            "retrieve":   "retrieve",
            "web_search": "web_search",
        }
    )
    graph.add_edge("retrieve",    "generate")
    graph.add_edge("web_search",  "generate_web")
    graph.add_edge("generate",    "check_hallucination")
    graph.add_edge("generate_web","check_hallucination")
    graph.add_edge("check_hallucination", "save_to_memory")
    graph.add_edge("save_to_memory", END)
    return graph.compile()  #compila il grafo

async def run_rag_graph(
    question: str,
    conversation_id: str,
    tenant_id: str,
    tenant_slug: str,
    user_id: str,
    collection_id: str | None = None,
    mode: str = "rag",
) -> RAGState:
    """
    Esegue il grafo LangGraph completo per una query.
    Args:
        question: domanda utente
        conversation_id: UUID conversazione
        tenant_id: UUID tenant
        tenant_slug: slug per schema SQL + collection Qdrant
        user_id: UUID utente
        collection_id: filtra per collection (opzionale)
        mode: rag | web | sql | general
    Returns:
        RAGState finale con answer, sources, scores, ecc.
    """
    graph = get_rag_graph()   #here funct qua sopra, save in var
    initial_state: RAGState = {
        "question": question,
        "conversation_id": conversation_id,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "user_id": user_id,
        "collection_id": collection_id,
        "mode": mode,
        "route": None,
        "retrieved_chunks": [],
        "session_messages": [],
        "web_results": None,
        "answer": "",
        "sources": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": 0,
        "hallucination_score": None,
        "error": None,
    }
    final_state = await graph.ainvoke(initial_state)  #execute
    return final_state

