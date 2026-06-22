# app/api/deps.py
# Dipendenze FastAPI condivise — iniettate via Depends().
# Ogni route che ha bisogno di DB, Redis, tenant usa queste funzioni.

from __future__ import annotations
from typing import Annotated, AsyncGenerator
from fastapi import Depends, Header, HTTPException, status   #depends per iniettare dipendenze
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession   #per sessioni DB asincrone, SQLAlchemy puo leggere vari types of db SqlServer/PostgreSQL/ect
from app.core.redis_client import TenantRedis  #ur custom
from app.core.security import decode_access_token, extract_bearer_token, hash_api_key  #ur custom
from app.db.sqlserver import tenant_db  #ur custom

class TenantContext:
    """
    Contesto del tenant estratto dal JWT.
    Iniettato in ogni route che richiede autenticazione.
    """
    def __init__(
        self,
        tenant_id: str,
        tenant_slug: str,
        user_id: str,
        user_role: str,
        user_email: str,
    ):
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id
        self.user_role = user_role
        self.user_email = user_email

    @property  #trasforma function -> proprieta leggibile come attributo (quindi ora fai settings.sqlserver_url come se fosse una var normale)
    def is_admin(self) -> bool:
        return self.user_role == "admin"

    @property  #trasforma function -> proprieta leggibile come attributo (quindi ora fai settings.sqlserver_url come se fosse una var normale)
    def is_viewer(self) -> bool:
        return self.user_role == "viewer"


async def get_current_tenant(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> TenantContext:
    """
    Estrae e valida l'identità dal JWT o dalla API Key.
    Iniettata in ogni route protetta con Depends(get_current_tenant).
    Supporta due metodi di autenticazione:
    1. Bearer JWT: Authorization: Bearer <token>
    2. API Key (PER INTEGRAZIONI ESTERNE):  X-API-Key: rag_xxx...
    Returns:
        TenantContext con tenant_id, user_id, role, ecc.
    Raises:
        HTTPException 401 se token assente o invalido
    """
    if authorization:
        token = extract_bearer_token(authorization)
        if token:
            payload = decode_access_token(token)
            if payload:
                return TenantContext(
                    tenant_id=payload.get("tenant_id", ""),
                    tenant_slug=payload.get("tenant_slug", ""),
                    user_id=payload.get("sub", ""),
                    user_role=payload.get("role", "user"),
                    user_email=payload.get("email", ""),
                )
    if x_api_key:
        context = await _validate_api_key(x_api_key)
        if context:
            return context
    raise HTTPException(  #rilancia eccezione 401 se nessun metodo di autenticazione valido
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token non valido o scaduto",
        headers={"WWW-Authenticate": "Bearer"},  #per il client
    )

async def _validate_api_key(api_key: str) -> TenantContext | None:
    """
    Valida una API key cercando il suo hash nel DB.
    Ritorna TenantContext se valida, None altrimenti.
    """
    try:
        key_hash = hash_api_key(api_key)
        #Cerca la key nel DB shared (non è tenant-specific)
        async with tenant_db._async_factory() as session:  #ur custom
            from sqlalchemy import text  #sqlalchemy legge vari tipi di db, ma per query raw serve text() per scrivere query SQL testuali
            result = await session.execute(
                text("""
                    SELECT
                        ak.tenant_id,
                        t.slug as tenant_slug,
                        ak.scopes
                    FROM shared.api_keys ak
                    JOIN shared.tenants t ON ak.tenant_id = t.id
                    WHERE ak.key_hash = :hash
                      AND ak.is_active = 1
                      AND (ak.expires_at IS NULL OR ak.expires_at > GETUTCDATE())
                """),
                {"hash": key_hash}  #sql parameter binding, 🔥🔥EVITA SQL INJECTION!!
            )
            row = result.fetchone()
            if not row:
                return None
            await session.execute(
                text("UPDATE shared.api_keys SET last_used = GETUTCDATE() WHERE key_hash = :hash"),  #update last_used
                {"hash": key_hash}  #sql parameter binding, 🔥🔥EVITA SQL INJECTION!!
            )
            await session.commit()  #ur custom
            return TenantContext(
                tenant_id=str(row.tenant_id),
                tenant_slug=row.tenant_slug,
                user_id=f"api_key_{key_hash[:8]}",  #pseudo user_id, solo i primi 8 chars dell'hash per identificare la key senza esporre tutto
                user_role="api",
                user_email="",
            )
    except Exception as e:
        logger.error(f"Errore validazione API key: {e}")
        return None

async def get_db(
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],  #Annotated blocca il type che puo essere solo di quel tipo, 🔥Depends(...) dice a fastpi di eseguire PRIMA get_current_tenant e poi SOLO DOPO questa funct
) -> AsyncGenerator[AsyncSession, None]:  #questa funzione async produce oggetti AsyncSession usando yield, guarda ur notes about Yield, vedi che devi return un Generator!
    """
    Ritorna sessione DB già configurata per lo schema del tenant.
    Usata con Depends(get_db) nelle route che accedono al DB.
    Esempio:
        @router.get("/documents")
        async def list_documents(db: Annotated[AsyncSession, Depends(get_db)]):
            result = await db.execute(text("SELECT * FROM documents"))
    """
    async with tenant_db.aget_session(tenant.tenant_slug) as session:
        yield session

def get_tenant_redis(
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],
) -> TenantRedis:
    """
    Ritorna istanza TenantRedis configurata per il tenant corrente.
    Esempio:
        @router.get("/session")
        async def get_session(
            redis: Annotated[TenantRedis, Depends(get_tenant_redis)]
        ):
    """
    return TenantRedis(tenant_id=tenant.tenant_id)

async def require_admin(
    tenant: Annotated[TenantContext, Depends(get_current_tenant)],  #questa funzione async produce oggetti AsyncSession usando yield, guarda ur notes about Yield, vedi che devi return un Generator!
) -> TenantContext:
    """
    Verifica che l'utente abbia ruolo admin.
    Usata per route di gestione (create user, delete document, ecc.)
    Raises:
        HTTPException 403 se l'utente non è admin
    """
    if not tenant.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato agli amministratori",
        )
    return tenant

#Type aliases, usati nelle routes e.g. CurrentTenant invece di Annotated[TenantContext, Depends(...)]
CurrentTenant = Annotated[TenantContext, Depends(get_current_tenant)]  #depends per iniettare le dipendenze, quindi ogni volta che usi CurrentTenant in una route, FastAPI sa di dover eseguire get_current_tenant() per ottenere il TenantContext
CurrentDB = Annotated[AsyncSession, Depends(get_db)]
CurrentRedis = Annotated[TenantRedis, Depends(get_tenant_redis)]
AdminOnly = Annotated[TenantContext, Depends(require_admin)]

