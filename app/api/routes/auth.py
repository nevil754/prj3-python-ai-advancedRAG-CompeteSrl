# app/api/routes/auth.py
# Autenticazione: login, token refresh, logout, profilo utente.

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from datetime import timedelta
from typing import Annotated   #per type hint più chiari, es. Annotated[]
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from loguru import logger   #plugin x logging avanzato
from pydantic import BaseModel, EmailStr
from sqlalchemy import text

from app.api.deps import CurrentTenant, get_current_tenant   #ur custom
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)   #ur custom
from app.core.settings import get_settings   #ur custom
from app.db.sqlserver import tenant_db  #ur custom

router = APIRouter(prefix="/auth", tags=["auth"])   #tags serve x Swagger ui per grouping all routers x auth sotto tag "auth"
settings = get_settings()

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int                  #in secs
    user_id: str
    user_role: str
    tenant_slug: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_slug: str                 #tenant si identifica con il suo slug!

class UserProfile(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    tenant_id: str
    tenant_slug: str

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:
    """
    Autentica un utente e ritorna un JWT.
    flow:
    1. Trova il tenant tramite slug in shared.tenants
    2. Cerca l'utente in tenant_{slug}.users per email
    3. Verifica la password con bcrypt
    4. Genera JWT con tenant_id, user_id, role nel payload
    """
    #1.trova il tenant
    async with tenant_db._async_factory() as session:
        tenant_row = await session.execute(
            text("""
                SELECT id, slug, is_active
                FROM shared.tenants
                WHERE slug = :slug
            """),   #cerca tenant globale per slug, se non esiste o è disabilitato blocca subito
            {"slug": request.tenant_slug}  #sql parameter binding, 🔥🔥EVITA SQL INJECTION!!
        )
        tenant = tenant_row.fetchone()  #prende la prima riga
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )
    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account tenant disabilitato",
        )
    #2.cerca l'utente nello schema del tenant
    async with tenant_db.aget_session(request.tenant_slug) as session:  #ENTRI NEL TENANT target
        user_row = await session.execute(
            text("""
                SELECT id, email, full_name, password_hash, role, is_active
                FROM users
                WHERE email = :email
            """),  #non specifichi il tenant xk sei gia dentro!, cerca user (nel tenant target) per email
            {"email": request.email}
        )
        user = user_row.fetchone()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account utente disabilitato",
        )
    #3.verifica password
    if not verify_password(request.password, user.password_hash):  #check se request.password == user.password_hash
        logger.warning(
            "Tentativo login fallito",
            email=request.email,
            tenant=request.tenant_slug,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide",
        )
    #4.aggiorna last_login
    async with tenant_db.aget_session(request.tenant_slug) as session:
        await session.execute(
            text("UPDATE users SET last_login = SYSUTCDATETIME() WHERE id = :id"),  #update ora ultimo login
            {"id": user.id}   #paramenter binding x evitare sql injection
        )
    #5.genera JWT
    token = create_access_token(data={  #crea token jwt con payload
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "tenant_id": str(tenant.id),
        "tenant_slug": tenant.slug,
    })
    logger.info("Login effettuato", user_id=str(user.id), tenant=request.tenant_slug)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        user_id=str(user.id),
        user_role=user.role,
        tenant_slug=tenant.slug,
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(tenant: CurrentTenant) -> TokenResponse:
    """
    Rinnova il JWT senza richiedere password.
    Il vecchio token deve essere ancora valido.
    """
    new_token = create_access_token(data={
        "sub": tenant.user_id,
        "email": tenant.user_email,
        "role": tenant.user_role,
        "tenant_id": tenant.tenant_id,
        "tenant_slug": tenant.tenant_slug,
    })
    return TokenResponse(
        access_token=new_token,
        expires_in=settings.jwt_expire_minutes * 60,
        user_id=tenant.user_id,
        user_role=tenant.user_role,
        tenant_slug=tenant.tenant_slug,
    )

@router.get("/me", response_model=UserProfile)
async def get_profile(tenant: CurrentTenant) -> UserProfile:
    """Ritorna il profilo dell'utente corrente."""
    async with tenant_db.aget_session(tenant.tenant_slug) as session:
        row = await session.execute(
            text("SELECT id, email, full_name, role FROM users WHERE id = :id"),
            {"id": tenant.user_id}
        )
        user = row.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return UserProfile(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
    )

@router.post("/logout")
async def logout(tenant: CurrentTenant) -> dict:
    """
    Logout — invalida le sessioni Redis dell'utente.
    Il JWT rimane tecnicamente valido fino a scadenza
    (per invalidarlo completamente servirebbe una blacklist in Redis —
    da implementare in v2 se vuoi 🔥).
    """
    from app.core.redis_client import TenantRedis
    redis = TenantRedis(tenant_id=tenant.tenant_id)  #cliente redis tenant-scoped
    # Cancella tutte le sessioni chat dell'utente
    pattern = f"tenant:{tenant.tenant_id}:session:*"
    client = redis._redis
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = await client.scan(cursor=cursor, match=pattern, count=50)  #redis scan incrementale 
        if keys:
            await client.delete(*keys)   #cancella batch chiavi!!
            deleted += len(keys)
        if cursor == 0:
            break
    logger.info("Logout", user_id=tenant.user_id, sessions_deleted=deleted)  #log w loguru, che crea record tipo
    # {
    #     "message": "Logout",
    #     "extra": {
    #         "user_id": "...",
    #         "sessions_deleted": 5
    #     }
    # }
    #pero nel tuo observability.py hai
    #fmt = (
    #    "<green>{time}</green> | "
    #    "<level>{level}</level> | "
    #    "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
    #    "<level>{message}</level>"
    #) quindi non hai {extra}, quindi in console non renderizzerai anche e.g. user_id e sessions_deleted, ma questi SERVONO CMNQ NEL RECORD LOGURU xk e.g. Grafana/OpenTelemetry/ELK li usano!!!
    return {"message": "Logout effettuato", "sessions_deleted": deleted}


