# =============================================================
# app/schemas/document.py
# Modelli Pydantic per documenti, collection e job di ingestion.
# =============================================================

from __future__ import annotations  #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from datetime import datetime
from pydantic import BaseModel, Field


class CollectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None

class CollectionSchema(BaseModel):
    id: str
    name: str
    description: str | None
    qdrant_name: str
    is_active: bool
    created_at: datetime
    class Config:
        from_attributes = True

class DocumentSchema(BaseModel):
    id: str
    collection_id: str | None
    filename: str
    original_name: str
    file_size: int
    mime_type: str | None
    status: str          #pending | processing | ready | error | deleted
    chunk_count: int | None
    page_count: int | None
    language: str | None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class IngestionJobSchema(BaseModel):
    id: str
    document_id: str
    celery_task_id: str | None
    status: str          #queued | running | done | failed | cancelled
    progress_pct: int
    error_msg: str | None
    retry_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    class Config:
        from_attributes = True

class UploadResponse(BaseModel):
    """Risposta immediata dopo upload — il job è in coda."""
    document_id: str
    job_id: str
    task_id: str
    status: str = "queued"
    message: str = "Documento in coda per l'elaborazione"

