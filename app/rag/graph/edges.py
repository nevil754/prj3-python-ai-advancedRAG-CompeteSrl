# =============================================================
# app/rag/graph/edges.py
# Logica di routing condizionale tra i nodi del grafo.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from app.rag.graph.state import RAGState  #ur custom

def edge_route_decision(state: RAGState) -> str:
    """
    Dopo il nodo route, decide quale percorso seguire.
    Ritorna il nome del prossimo nodo.
    """
    route = state.get("route", "rag")   #"rag" è fallback
    if route == "web":
        return "web_search"
    return "retrieve"    #in tutti gli altri casi e.g. rag | sql | general |... allora ritorna "retrieve" (che è il nome del nodo)


