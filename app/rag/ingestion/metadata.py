# =============================================================
# app/rag/ingestion/metadata.py
# Estrazione e arricchimento metadata da documenti.
# Legge metadata.yaml per la classificazione automatica.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import re
from datetime import datetime, timezone  #x timestamp
from pathlib import Path
from typing import Any
import yaml
from loguru import logger
from app.core.settings import get_settings   #ur custom


settings = get_settings()
_metadata_config: dict | None = None

def build_chunk_metadata(
    tenant_id: str,
    collection_id: str | None,
    document_id: str,
    filename: str,
    chunk_index: int,
    page_number: int | None,
    file_type: str,
    document_text_sample: str = "",
) -> dict[str, Any]:
    """
    Costruisce il payload metadata per un chunk Qdrant.
    Questo payload viene salvato con ogni vettore e
    permette i filtri nel retrieval.
    Args:
        document_text_sample: primi 500 caratteri del documento
                              per classificazione automatica del tipo
    """
    doc_type = _classify_document(document_text_sample, filename)  #è questa function here qua sotto
    metadata: dict[str, Any] = {
        # Campi obbligatori per isolamento multi-tenant
        "tenant_id": tenant_id,
        "collection_id": collection_id,
        "document_id": document_id,
        "filename": filename,
        "file_type": file_type.lstrip(".").lower(),
        "doc_type": doc_type,
        # Posizione nel documento
        "chunk_index": chunk_index,
        "page_number": page_number,
        # Timestamp per filtri temporali
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    return metadata

def _classify_document(text_sample: str, filename: str) -> str:
    """
    Classifica automaticamente il tipo di documento
    cercando keyword nel testo e nel nome file.
    """
    cfg = get_metadata_config()
    doc_types = cfg.get("document_types", {})
    text_lower = ( text_sample + " " + filename ).lower()
    for doc_type, type_cfg in doc_types.items():
        if doc_type == "generic":
            continue
        keywords = type_cfg.get("detect_keywords", [])
        if any( kw.lower() in text_lower for kw in keywords ):  #'in text_lower' è e.g."redis" in "sto studiando redis e fastapi" -> True
            logger.debug(f"Documento classificato come: {doc_type}")
            return doc_type  
    #quindi return SOLO IL PRIMO MATCH!! 
    return "generic"

def get_metadata_config() -> dict:
    """Carica metadata.yaml una sola volta."""
    global _metadata_config
    if _metadata_config is None:
        config_path = Path( settings.metadata_config_file if hasattr( settings, 'metadata_config_file' ) else "/app/config/metadata.yaml" )   #se settings ha metadata_config_file -> usa quello, altrimenti fallback "/app/config/metadata.yaml"
        if config_path.exists():  #check se file yaml esiste davvero
            with open(config_path) as f:
                _metadata_config = yaml.safe_load(f) or {}    #safe_load() x caricare anche da untrusted sources
        else:
            _metadata_config = {}
    return _metadata_config

