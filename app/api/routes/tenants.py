# =============================================================
# app/api/routes/tenants.py
# Gestione tenant: solo superadmin può creare/disabilitare tenant.
# Usato internamente da Compete Srl per onboarding clienti.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from fastapi import APIRouter, HTTPException, status   #apirouter x le routes, status x codici http
from pydantic import BaseModel
from sqlalchemy import text
from app.api.deps import CurrentTenant
from app.services.tenant_service import provision_tenant


router = APIRouter(prefix="/tenants", tags=["tenants"])

class TenantCreate(BaseModel):
    slug: str
    display_name: str
    plan: str = "starter"
    admin_email: str | None = None
    admin_password: str | None = None

class TenantResponse(BaseModel):
    tenant_id: str
    slug: str
    plan: str
    admin_user_id: str | None = None

def _require_superadmin(tenant: CurrentTenant) -> None:
    """Solo utenti con role='superadmin' possono gestire i tenant."""
    if tenant.user_role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accesso riservato ai superadmin",
        )

@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    tenant: CurrentTenant,
) -> TenantResponse:
    """Crea un nuovo tenant. Solo superadmin."""
    _require_superadmin(tenant)
    result = await provision_tenant(
        slug=body.slug,
        display_name=body.display_name,
        plan=body.plan,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
    )
    return TenantResponse(**result)

@router.get("")
async def list_tenants(tenant: CurrentTenant) -> list[dict]:
    """Lista tutti i tenant. Solo superadmin."""
    _require_superadmin(tenant)
    from app.db.sqlserver import tenant_db
    async with tenant_db._async_factory() as session:
        rows = await session.execute(
            text("""
                SELECT id, slug, display_name, plan, is_active, created_at
                FROM shared.tenants
                ORDER BY created_at DESC
            """)
        )
        return [ dict(r._mapping) for r in rows ]  #_mapping converte row sqlalchemy in dict-like, dict() converte in dict normale

@router.patch("/{slug}/disable")  #http patch edit solo targets from the source 
async def disable_tenant(slug: str, tenant: CurrentTenant) -> dict:
    """Disabilita un tenant. Solo superadmin."""
    _require_superadmin(tenant)
    from app.db.sqlserver import tenant_db
    async with tenant_db._async_factory() as session:
        await session.execute(
            text("UPDATE shared.tenants SET is_active = 0 WHERE slug = :slug"),
            {"slug": slug}
        )
        await session.commit()  #commit changes to the database
    return { "message": f"Tenant {slug} disabilitato" }


