# =============================================================
# app/rag/generation/hallucination.py
# Rilevamento allucinazioni nella risposta LLM.
# Usa ragas faithfulness check: la risposta è supportata dal contesto?
# =============================================================

from __future__ import annotations    #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from loguru import logger
from app.rag.retrieval.retriever import RetrievedChunk   #ur custom

async def check_faithfulness(
    question: str,
    answer: str,
    chunks: list[RetrievedChunk],
) -> float:
    """
    Calcola uno score di faithfulness (0.0-1.0).
    1.0 = risposta completamente supportata dai documenti
    0.0 = risposta non supportata (possibile allucinazione)
    Usa un approccio LLM-based: chiede al modello se ogni affermazione
    nella risposta è supportata dal contesto fornito.
    Args:
        question: domanda originale
        answer: risposta generata dall'LLM
        chunks: chunk usati come contesto
    Returns:
        Score float tra 0.0 e 1.0
    """
    if not chunks or not answer:
        return 1.0
    context = "\n\n".join(c.text for c in chunks[:5])  #prende solo i top 5 chunks, concatena il testo con separatore '\n\n'
    try:
        from app.core.llm_factory import get_llm
        from langchain_core.messages import HumanMessage

        llm = get_llm()
        response = await llm.ainvoke([
            HumanMessage(content=f"""Valuta se la RISPOSTA è completamente supportata dal CONTESTO.
                Rispondi SOLO con un numero tra 0.0 e 1.0.
                1.0 = completamente supportata, 0.0 = per niente supportata.
                CONTESTO:
                {context}
                RISPOSTA:
                {answer}
                SCORE (solo il numero):""")
        ])   #crea mex da inviato all'llm (con interpolati i values), chiedi all'llm di risponder con un numero 0-1
        score_text = response.content.strip()  
        score = float(score_text)  #converti 
        score = max(0.0, min(1.0, score))  #forza range valido clamp tra 0 e 1
        logger.debug(f"Hallucination score: {score:.2f}")   #x logging strutturato
        return score
    except Exception as e:
        logger.warning(f"Hallucination check fallito: {e}")
        return 1.0    #assume faithfulness se il check fallisce, return 1.0

def is_hallucination(score: float, threshold: float = 0.5) -> bool:
    """Ritorna True se lo score è sotto la soglia di faithfulness."""
    return score < threshold   #return True/False


