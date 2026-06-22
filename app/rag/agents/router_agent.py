# =============================================================
# app/rag/agents/router_agent.py
# Classifica la query e decide quale agent/tool usare.
# rag → retrieval documenti locali
# web → ricerca web con Tavily
# sql → NL→SQL su dati strutturati
# general → risposta diretta LLM
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from typing import Literal
from langchain_core.messages import HumanMessage
from loguru import logger
from app.core.llm_factory import get_llm
from app.core.settings import get_settings


settings = get_settings()
QueryRoute = Literal["rag", "web", "sql", "general"]   #Literal quindi possono essere solo di questi 4 valori specificati

async def route_query(question: str) -> QueryRoute:
    """
    Classifica la query dell'utente per scegliere il percorso di risposta.
    Logica:
    - Se web_search disabilitato → sempre "rag" o "general"
    - Altrimenti chiede all'LLM di classificare
    Returns:
        "rag" | "web" | "sql" | "general"
    """
    if not settings.web_search_enabled:
        return "rag"
    llm = get_llm()
    from app.rag.generation.prompts import _load_prompts
    prompts = _load_prompts()
    classify_prompt = prompts.get("router", {}).get("classify", _DEFAULT_CLASSIFY)
    try:
        response = await llm.ainvoke([
            HumanMessage( content=classify_prompt.format(question=question) )   #usa il tuo template classify_prompt (passandogli a sua volta i valori per il placeholder)
        ])  #dato il setted prompt, il llm return e.g. 'rag'
        route = response.content.strip().lower()
        if route not in {"rag", "web", "sql", "general"}:
            logger.warning(f"Route non valida '{route}', default rag")
            route = "rag"
        logger.debug(f"Query routed to: {route}")
        return route
    except Exception as e:
        logger.warning(f"Router fallito: {e}, default rag")
        return "rag"


_DEFAULT_CLASSIFY = """Classifica la domanda in UNA di queste categorie:
    - rag: domanda su documenti caricati nel sistema
    - web: richiede informazioni aggiornate da internet
    - sql: domanda su dati strutturati o statistiche
    - general: domanda generica non legata a documenti
    Rispondi con SOLO la categoria, nessuna spiegazione.
    Domanda: {question}
Categoria:"""   #here vedi che hai il palceholder!

