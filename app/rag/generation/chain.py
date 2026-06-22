# =============================================================
# app/rag/generation/chain.py
# Chain RAG: contesto + prompt → LLM → risposta con citazioni.
# =============================================================

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import time
from typing import AsyncGenerator, Any  #AsyncGenerator per generatore asyncrono che quindi userai yield
from langchain_core.messages import HumanMessage, SystemMessage  
from loguru import logger   #x logging strutturato 
from app.core.llm_factory import get_llm  #ur custom
from app.rag.generation.prompts import (
    get_rag_system_prompt,
    get_rag_user_prompt,
    get_no_context_message,
)
from app.rag.retrieval.retriever import RetrievedChunk
from app.rag.memory.context_builder import build_rag_context, format_sources_for_response


async def arun_rag_chain(   #version no streaming, visto che non utilizzi Asyncgenerator & yield
    question: str,
    chunks: list[RetrievedChunk],
    session_messages: list[dict],
    tenant_name: str = "Compet-e Compliance AI",
) -> dict[str, Any]:
    """
    Esegue la chain RAG completa in modalità non-streaming.
    Returns:
        dict con answer, sources, tokens_in, tokens_out, latency_ms
    """
    start = time.perf_counter()   #inizia cronometro
    if not chunks:
        return {
            "answer": get_no_context_message(),
            "sources": [],
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": 0,
        }
    ctx = build_rag_context(chunks, session_messages)
    # Costruisci messaggi
    system_msg = SystemMessage( content= get_rag_system_prompt(tenant_name) )   #systemmessage è x istruzioni/context da dire all'llm prima di iniziare la conversazione
    user_msg = HumanMessage( content=get_rag_user_prompt(   #humamessage rappresenta il mex dell'utente (fornito anche di context /history ect) che passi all'llm
        context=ctx["context"],
        history=ctx["history"],
        question=question,
    ))
    llm = get_llm()
    response = await llm.ainvoke([system_msg, user_msg])  #🔥🔥qua avviene la chiamata vera 
    answer = response.content
    usage = getattr( response, "usage_metadata", None ) or {}  #estrazione token usage (questo field usage_metadata non sempre tutti i llm lo restituiscono!!), con get_attr() eviti il crash
    tokens_in = usage.get("input_tokens", 0)  #quanti token hai mandato all'llm
    tokens_out = usage.get("output_tokens", 0)   #quanti token ha generato l'llm nella risposta
    latency_ms = round((time.perf_counter() - start) * 1000)   #tempo totale e.g.1234ms
    logger.debug(
        "RAG chain completata",
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        sources=len(chunks),
    )
    return {
        "answer": answer,
        "sources": format_sources_for_response(chunks),  #citazioni formattate per la risposta
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "latency_ms": latency_ms,
    }


async def astream_rag_chain(   #streaming version, con AsyncGenerator & yield
    question: str,
    chunks: list[RetrievedChunk],
    session_messages: list[dict],
    tenant_name: str = "Compet-e Compliance AI",
) -> AsyncGenerator[str, None]:
    """
    Esegue la chain RAG in modalità streaming.
    Genera token per token via async generator.
    Usato dalla route /chat con SSE.
    """
    if not chunks:
        yield get_no_context_message()
        return
    ctx = build_rag_context(chunks, session_messages)
    system_msg = SystemMessage( content=get_rag_system_prompt(tenant_name) )
    user_msg = HumanMessage( content=get_rag_user_prompt(
        context=ctx["context"],
        history=ctx["history"],
        question=question,
    ))
    llm = get_llm()
    async for chunk in llm.astream([system_msg, user_msg]):   #here langchain restituisce picooli pezzi
        token = chunk.content
        if token:
            yield token

