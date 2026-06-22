# =============================================================
# app/db/repositories/base.py
# Repository base con operazioni CRUD comuni.
# Tutti i repository tenant-specific ereditano da questo.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Repository base. Ogni metodo riceve la sessione già configurata per il tenant."""
    def __init__(self, db: AsyncSession):
        self.db = db
    async def execute(self, query: str, params: dict | None = None):
        return await self.db.execute(text(query), params or {})
    async def fetchone(self, query: str, params: dict | None = None):
        result = await self.execute(query, params)
        return result.fetchone()
    async def fetchall(self, query: str, params: dict | None = None):
        result = await self.execute(query, params)
        return result.fetchall()
    async def scalar(self, query: str, params: dict | None = None):
        result = await self.execute(query, params)
        return result.scalar()

