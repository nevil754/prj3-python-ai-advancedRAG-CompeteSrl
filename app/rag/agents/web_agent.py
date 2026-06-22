# =============================================================
# app/rag/agents/web_agent.py
# Agent per la ricerca web: usa Tavily (preferito) o DDGS.
# Attivato solo se web_search.enabled = true in config.yaml.
# =============================================================

from __future__ import annotations
from loguru import logger
from app.core.settings import get_settings


settings = get_settings()

async def web_search_and_answer(
    question: str,
    max_results: int | None = None,
) -> dict:
    """
    Cerca su web e genera una risposta con le fonti trovate.
    Args:
        question: domanda da cercare
        max_results: numero max risultati (default da config)
    Returns:
        dict con answer, sources, provider_used
    """
    if not settings.web_search_enabled:
        return {
            "answer": "La ricerca web non è abilitata in questa installazione.",
            "sources": [],
            "provider": None,
        }
    # Le parentesi sono necessarie: senza, Python parserebbe come
    # (max_results or settings.web_search_max_results) if hasattr(...) else 5
    # che ignora max_results quando il campo non esiste.
    k = max_results or (settings.web_search_max_results if hasattr(settings, 'web_search_max_results') else 5)
    provider = settings.web_search_provider.lower()
    if provider == "tavily" and settings.tavily_api_key:
        return await _search_tavily(question, k)
    else:
        return await _search_ddgs(question, k)


async def _search_tavily(question: str, k: int) -> dict:  #usa plugin tavily-python (https://www.tavily.com/)  
    """Ricerca con Tavily — risultati già pronti per LLM."""
    import asyncio   #x async functions
    from tavily import TavilyClient
    client = TavilyClient( api_key=settings.tavily_api_key )
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(  
        None,
        lambda: client.search( question, max_results=k, include_answer=True )  #esegue tavily
    )
    answer = results.get("answer", "")
    sources = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", "")[:300],
            "score": r.get("score", 0.0),
        }
        for r in results.get("results", [])
    ]
    if not answer and sources:
        # Genera risposta con LLM se Tavily non la fornisce
        answer = await _generate_from_web_results(question, sources)
    return {"answer": answer, "sources": sources, "provider": "tavily"}


async def _search_ddgs(question: str, k: int) -> dict:   #usa plugin ddgs (free web search)
    """Ricerca con DuckDuckGo — solo links, poi scraping + LLM."""
    from ddgs import DDGS
    with DDGS() as ddgs:
        raw = list( ddgs.text(question, max_results=k) )
    sources = [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", "")[:300],
            "score": 1.0,
        }
        for r in raw
    ]
    answer = await _generate_from_web_results(question, sources)   #function here qua sotto
    return { "answer": answer, "sources": sources, "provider": "ddgs" }

async def _generate_from_web_results(question: str, sources: list[dict]) -> str:
    """Genera risposta con LLM dai risultati web."""
    from app.core.llm_factory import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    context = "\n\n".join(
        f"[{s['title']}] ({s['url']})\n{s['snippet']}" for s in sources
    )
    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content="Sei un assistente che risponde usando risultati di ricerca web. Cita sempre le fonti con URL."),
        HumanMessage(content=f"""RISULTATI WEB:
            {context}

            DOMANDA: {question}

            RISPOSTA (cita le fonti con URL):""")
    ])
    return response.content


