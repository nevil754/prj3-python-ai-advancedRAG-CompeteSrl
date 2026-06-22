# =============================================================
# app/rag/generation/citations.py
# Estrazione e formattazione citazioni nella risposta LLM.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import re   #x regex
from dataclasses import dataclass   #messo sopra una classe, ti da automaticamente __init__, __repr__, __eq__, ect
from app.rag.retrieval.retriever import RetrievedChunk   #ur custom

@dataclass
class Citation:
    index: int
    filename: str
    page_number: int | None
    chunk_id: str
    document_id: str
    snippet: str

def extract_citations(
    answer: str,
    chunks: list[RetrievedChunk],
) -> tuple[str, list[Citation]]:
    """
    Estrae le citazioni dalla risposta LLM e le abbina ai chunk sorgente.
    Il LLM usa il formato [Fonte N: filename, p.X] — questa funzione le parsa.
    Args:
        answer: risposta grezza dell'LLM con citazioni inline
        chunks: chunk usati come contesto (ordinati come inviati al LLM)
    Returns:
        Tuple (answer_clean, citations)
        answer_clean: risposta con citazioni normalizzate [1], [2], ...
        citations: lista Citation con metadata completi
    e.g.
    prende risposta llmn con citazioni
    [Fonte 1: file.pdf, p.12]
    le trasforma in citazioni numeriche: [1] [2]  lista finale di fonti strutturate (Citation)
    """
    citations: list[Citation] = []
    citation_map: dict[str, int] = {}  # filename -> indice citazione
    pattern = r'\[Fonte\s*(\d+):\s*([^\],]+?)(?:,\s*p\.(\d+))?\]'   #matcha pattern  [Fonte N: filename, p.X] oppure [Fonte N: filename]

    def replace_citation( match: re.Match ) -> str:  #questa funct viene chiamata x ogni match trovato nel regex pattern
        source_idx = int(match.group(1)) - 1  #gruppo 1 = numero fonte, -1 perché lista Python è 0-based
        filename = match.group(2).strip()   #prende il filename e cancella spazi laterali 
        page = int(match.group(3)) if match.group(3) else None  #se esiste pagina → int, altrimenti None
        chunk = None
        if 0 <=  source_idx < len(chunks):   #l'indice non deve essere negativo/==0, e l'indice deve essere dentro la lunghezza della lista len(chunks)
            chunk = chunks[source_idx]  #get chunk
        else:  #altrimenti, get chunk cercando per filename (potrebbe essere che il LLM abbia cambiato l'ordine dei chunk, quindi non matcha più l'indice)
            for c in chunks:
                if c.filename == filename:
                    chunk = c
                    break
        if not chunk:
            return match.group(0)  #return lascia citazione originale invariata se non trovato
        # Crea o riusa indice citazione
        key = f"{chunk.document_id}:{chunk.chunk_index}"  #crea str key, identifica univocamente un chunk
        if key not in citation_map:
            idx = len(citations) + 1   #nuovo numero citazione, 1-based
            citation_map[key] = idx   #update local dict citation_map
            citations.append( Citation(  #aggiungi alla list
                index=idx,
                filename=chunk.filename,
                page_number=page or chunk.page_number,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                snippet=chunk.text[:200],
            ) )
        else:
            idx = citation_map[key]   #update
        return f"[{idx}]"
    
    answer_clean = re.sub(pattern, replace_citation, answer)  #replace_citation() here qua sopra annidato viene chiamata per ogni match trovato. re.sub(patternToFind, newPatternThatWillReplacePatternFound, allTextWhereSearch)
    return answer_clean, citations


def format_citations_markdown(citations: list[Citation]) -> str:
    """Formatta le citazioni come sezione markdown in fondo alla risposta."""
    if not citations:
        return ""
    lines = ["\n\n---\n**Fonti:**"]
    for c in citations:  #per ogni citation
        page_info = f", p. {c.page_number}" if c.page_number else ""
        lines.append(f"[{c.index}] {c.filename}{page_info}")
    return "\n".join(lines)  #join() unisce tutti gli elementi della lista lines in un'unica stringa, separati da "\n" (newline)


