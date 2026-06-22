# =============================================================
# app/schemas/common.py
# Modelli Pydantic condivisi tra tutte le route.
# Separati dai modelli SQLAlchemy (db/models) — i modelli Pydantic
# sono per la validazione API, i modelli SQLAlchemy per il DB.
# =============================================================

from __future__ import annotations   #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from datetime import datetime
from typing import Any, Generic, TypeVar   #Generic per tipi generici, TypeVar per definire variabili di tipo generico
from uuid import UUID
from pydantic import BaseModel, Field    #BaseModel è la classe base per i modelli pyndatic, Field è usato per aggiungere validazione e metadata ai campi dei modelli

T = TypeVar("T")   #crea un tipo generico

class PaginatedResponse( BaseModel, Generic[T] ):
    """Response paginata generica. Usata da tutte le route che listano risorse."""
    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool
    @classmethod   #dice a python che questa funzione appartiene alla classe e NON all'istanza. per validator pydantic è lo standart
    def build(cls, items: list[T], total: int, page: int, page_size: int):
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,  #calcola se ci sono altre pagine, is True/False
        )

class ErrorResponse(BaseModel):
    """Risposta di errore standardizzata."""
    error: str
    detail: str | None = None
    request_id: str | None = None

class SuccessResponse(BaseModel):
    """Risposta di successo generica per operazioni senza body."""
    message: str
    data: dict[str, Any] | None = None
