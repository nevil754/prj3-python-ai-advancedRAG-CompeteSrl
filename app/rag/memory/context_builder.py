# =============================================================
# app/rag/memory/context_builder.py
# Assembla il contesto completo da passare all'LLM:
# short-term memory + retrieved chunks + user facts.
# =============================================================

from __future__ import annotations   #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from typing import Any
from loguru import logger  #x logging strutturato
from app.rag.retrieval.retriever import RetrievedChunk  #ur custom

def build_rag_context(
    chunks: list[RetrievedChunk],
    session_messages: list[dict],
    user_facts: list[dict] | None = None, 
    max_context_chars: int = 12000,   #🔥max CONTEXT window!!
) -> dict[str, str]:
    """
    Assembla il contesto per il prompt RAG.
    Args:
        chunks: chunk recuperati dal retriever
        session_messages: ultimi N messaggi dalla sessione Redis
        user_facts: fatti estratti sull'utente (long-term memory, v2)
        max_context_chars: limite totale caratteri per il contesto
    Returns:
        dict con:
            context: testo dei chunk formattato
            history: storico conversazione formattato
            facts: fatti utente formattati (se presenti)
    """
    context_parts = []
    total_chars = 0
    for i, chunk in enumerate(chunks, 1):
        source_label = f"[Fonte {i}: {chunk.filename}"  #crea e.g. [Fonte 2: contratto.pdf
        if chunk.page_number:
            source_label += f", p.{chunk.page_number}"  #aggiungi concatenazione 
        source_label += "]"  #chiudi str con ']'
        chunk_text = f"{source_label}\n{chunk.text}"
        chunk_chars = len(chunk_text)
        if total_chars + chunk_chars > max_context_chars:  #importante!! NON DEVI SUPERARE IL LIMITE DI CHARS!!
            logger.debug(f"Contesto troncato a {i-1} chunk per limite caratteri!")
            break
        context_parts.append(chunk_text)
        total_chars += chunk_chars
    context = "\n\n---\n\n".join(context_parts) if context_parts else "" 
    history_parts = []
    for msg in session_messages:
        role = msg.get("role", "user")   #default a 'user' se manca il value della key 'role'
        content = msg.get("content", "")
        prefix = "Utente" if role == "user" else "Assistente"
        history_parts.append( f"{prefix}: {content}" )
    history = "\n".join(history_parts) if history_parts else "Nessuna conversazione precedente."
    facts_text = ""
    if user_facts:
        facts_parts = [ f"- { f['fact_key'] }: { f['fact_value'] }"  for f in user_facts ]  #array
        facts_text = "\n".join( facts_parts )
    logger.debug(
        "Context assemblato",
        chunks=len(context_parts),
        history_turns=len(session_messages),
        context_chars=total_chars,
    )
    return {
        "context": context,
        "history": history,        
        "facts": facts_text,
    }

def format_sources_for_response( chunks: list[RetrievedChunk] ) -> list[dict]:
    """
    Formatta i chunk come lista di sorgenti per la risposta API.
    Incluso nel ChatResponse.sources.
    """
    return [
        {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "page_number": chunk.page_number,
            "score": round(chunk.score, 4),   #4 decimali 
            "snippet": chunk.text[:200] + "..." if len(chunk.text) > 200 else chunk.text,   # theseare200chars... oppure se i chars sono <200 allora return l'intero chunk.text
        }
        for chunk in chunks
    ]


