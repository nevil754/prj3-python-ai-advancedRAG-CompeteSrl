# =============================================================
# app/rag/ingestion/chunker.py
# Divide il testo in chunk ottimizzati per il retrieval.
# =============================================================

from __future__ import annotations   #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from dataclasses import dataclass, field    #x creare classi leggere, e.g. con @dataclass python genera auto init,repr, eq. invece field è usato per default_factory che permette di avere un dict vuoto come default senza condividere lo stesso dict tra istanze
from typing import Any
from langchain.text_splitter import MarkdownTextSplitter, RecursiveCharacterTextSplitter   #uno usa struttura markdown, l'altro divide il testo in modo intelligente usando i separatori "\n\n", "\n", ". ", " "
from loguru import logger   #x logging strutturato
from app.core.settings import get_settings


settings = get_settings()

@dataclass
class Chunk:
    """Un singolo chunk di testo pronto per l'embedding"""
    text: str
    chunk_index: int
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)  #default_factory evita di condividere lo stesso dict tra istanze, ogni chunk ha suo dict vuoto di metadata

def chunk_document(
    text: str,
    pages: list[str] | None = None,
    base_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """
    Divide il testo in chunk con la strategia configurata.
    Strategie:
    - markdown: rispetta titoli e sezioni (ottimo per contratti strutturati)
    - recursive: fallback generico con separatori multipli
    - sentence: divide per frasi (ottimo per testi continui)
    Args:
        text: testo completo del documento
        pages: testo diviso per pagina (per tracciare page_number)
        base_metadata: metadata di base da includere in ogni chunk
    Returns:
        Lista di Chunk pronti per l'embedding
    """
    strategy = settings.ingestion_chunk_strategy
    chunk_size = settings.ingestion_chunk_size
    overlap = settings.ingestion_chunk_overlap
    if strategy == "markdown":
        splitter = MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
        )
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=["\n\n", "\n", ". ", " ", ""],  #separatore vuoto alla fine per forzare chunk anche se superano chunk_size
        )
    raw_chunks = splitter.split_text(text)  #splitta
    # Filtra chunk troppo piccoli (meno di min_chunk_size caratteri)
    min_size = max(50, chunk_size // 20)   #e.g. 1000 / 20 = 50, allora è 50, se veniva 40 allora era 50, perche con max(va1,val2) prende il valore piu alto 
    raw_chunks = [c for c in raw_chunks if len(c.strip()) >= min_size]   #🔥rimuove i chunk troppo piccoli
    chunks: list[Chunk] = []
    for i, chunk_text in enumerate(raw_chunks):  #itera per ogni elemento della lista, quindi itera su ogni chunk
        page_num = _find_page_number(chunk_text, pages) if pages else None
        chunks.append( Chunk(
            text=chunk_text.strip(),  #elimina spazi laterali
            chunk_index=i,  #l'index
            page_number=page_num,  #quindi qua puo essere i | none
            metadata={ **(base_metadata or {}), "chunk_index": i }, #passa  metadata base (in forma **kargs xk è un dict quindi key-value) + chunk_index
        ))
    logger.debug(
        f"Chunking completato: {len(raw_chunks)} → {len(chunks)} chunk validi",
        strategy=strategy,
        chunk_size=chunk_size,
    )   #x logging strutturato
    return chunks

def _find_page_number(chunk_text: str, pages: list[str]) -> int | None:
    """Trova in quale pagina appare il chunk cercando il testo."""
    for i, page_text in enumerate(pages, 1):   #enumerate() prende un lista su cui deve iterare & il num start
        if chunk_text[:100] in page_text:   #prende i primi 100chars del chunk e li cerca nella pagina page_text
            return i  #se trovato, ritorna l'indice della pagina 
    return None   #altrimenti return null


