# =============================================================
# app/api/routes/collections.py
# Gestione collection (cartelle logiche di documenti per tenant).
# =============================================================

from __future__ import annotations   #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from fastapi import APIRouter, HTTPException, status  #apirouter x le routes, status x codici http
from sqlalchemy import text   #x query sql manuali
from app.api.deps import AdminOnly, CurrentDB, CurrentTenant
from app.core.vectorstore import ensure_collection, get_collection_name
from app.schemas.common import PaginatedResponse
from app.schemas.document import CollectionCreate, CollectionSchema


router = APIRouter(prefix="/collections", tags=["collections"])

@router.post("", response_model=CollectionSchema, status_code=status.HTTP_201_CREATED)  #risposta type CollectionSchema validata con pydantic
async def create_collection(
    body: CollectionCreate,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> CollectionSchema:
    """Crea una nuova collection per il tenant."""
    from uuid import uuid4
    from python_slugify import slugify   #x trasformare "Fatture 2025" -> "fatture-2025"

    coll_id = str(uuid4())  #genera e formatta in str
    qdrant_name = f"tenant_{tenant.tenant_slug.replace('-','_')}_{slugify(body.name)}"   #nome collection qdrant, unico per tenant. e.g. tenant "acme-corp" e collection "Fatture 2025"  -> tenant_acme_corp_fatture-2025
    ensure_collection( tenant.tenant_slug )   #assicura che la collection base esista
    await db.execute(
        text("""
            INSERT INTO collections (id, name, description, qdrant_name, created_by)
            VALUES (:id, :name, :desc, :qdrant_name, :user_id)
        """),
        {
            "id": coll_id,
            "name": body.name,
            "desc": body.description,
            "qdrant_name": qdrant_name,
            "user_id": tenant.user_id,
        }  #i ':' sono i placeholder
    )
    row = await db.execute(
        text("SELECT * FROM collections WHERE id = :id"), {"id": coll_id}  #recupera record appena creato
    )
    return CollectionSchema.model_validate( dict(row.fetchone()._mapping) )   #fetchone() prende 1 row, _mapping converte row sqlalchemy in dict-like, dict() converte in dict normale, model_validate() valida e trasforma in CollectionSchema


@router.get("", response_model=PaginatedResponse[CollectionSchema])   #risposta type PaginatedResponse con items di tipo CollectionSchema, validata con pydantic
async def list_collections(
    tenant: CurrentTenant,
    db: CurrentDB,
    page: int = 1,
    page_size: int = 20,   #dimensione pagina
) -> PaginatedResponse[CollectionSchema]:
    """Lista collection del tenant."""
    offset = (page - 1) * page_size  #calcola offset per paginazione, cioe quanti elems ignorare prima di inziare a laggere quindi e.g. per page 2 salti i primi 20 (quelli che appartengono a page1)
    total = ( await db.execute( text("SELECT COUNT(*) FROM collections WHERE is_active = 1") ) ).scalar() or 0   #scalar() prende il primo valore della prima riga (puo fare solo read), in questo caso il count totale di collection attive, se è None allora 0
    rows = await db.execute(
        text("""
            SELECT id, name, description, qdrant_name, is_active, created_at
            FROM collections WHERE is_active = 1
            ORDER BY created_at DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
        """),  #OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY significa "salta :offset rows e prendi le prossime :limit rows", e.g. per page 2 con page_size 20 -> OFFSET 20 ROWS FETCH NEXT 20 ROWS ONLY, quindi salta i primi 20 e prendi i successivi 20 
        {"offset": offset, "limit": page_size}
    )
    items = [CollectionSchema.model_validate(dict(r._mapping)) for r in rows]   #_mapping converte row sqlalchemy in dict-like, dict() converte in dict normale, model_validate() valida e trasforma in CollectionSchema, crea lista di CollectionSchema
    return PaginatedResponse.build( items=items, total=total, page=page, page_size=page_size )   #run the ur funct


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str,
    tenant: AdminOnly,   
    db: CurrentDB,
) -> None:
    """Disabilita una collection (soft delete)."""
    await db.execute(
        text("UPDATE collections SET is_active = 0 WHERE id = :id"),
        {"id": collection_id}
    )

