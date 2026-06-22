# =============================================================
# app/db/repositories/document_repo.py
# Tutte le query SQL per documenti e ingestion jobs.
# Le route non toccano mai SQLAlchemy direttamente — usano questo.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.repositories.base import BaseRepository


class DocumentRepository(BaseRepository):

    async def get_by_id(self, document_id: str) -> dict | None:
        row = await self.fetchone(
            "SELECT * FROM documents WHERE id = :id",
            {"id": document_id}
        )
        return dict(row._mapping) if row else None   #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale

    async def get_by_hash(self, file_hash: str) -> dict | None:
        row = await self.fetchone(
            "SELECT id FROM documents WHERE file_hash = :hash",
            {"hash": file_hash}
        )
        return dict(row._mapping) if row else None   #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale

    async def update_status(
        self,
        document_id: str,
        status: str,
        chunk_count: int | None = None,
        page_count: int | None = None,
    ) -> None:
        await self.execute(
            """
            UPDATE documents
            SET status = :status,
                chunk_count = COALESCE(:chunks, chunk_count),
                page_count = COALESCE(:pages, page_count),
                updated_at = SYSUTCDATETIME()
            WHERE id = :id
            """,
            {"status": status, "chunks": chunk_count, "pages": page_count, "id": document_id}
        )  #COALESCE return il primo valore not null (da sx a dx) tra quelli passati

    async def soft_delete(self, document_id: str) -> None:
        await self.execute(
            "UPDATE documents SET status = 'deleted', updated_at = SYSUTCDATETIME() WHERE id = :id",
            {"id": document_id}
        )

    async def list_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        collection_id: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict], int]:
        where = "WHERE 1=1"
        params: dict = { "limit":page_size,  "offset": (page-1)*page_size }
        if collection_id:
            where += " AND collection_id = :coll_id"
            params["coll_id"] = collection_id
        if status:
            where += " AND status = :status"
            params["status"] = status
        total = await self.scalar( f"SELECT COUNT(*) FROM documents {where}", params)   #scalar() è un fetch che ritorna prima row, gli passi where(cioe tutto il text restante per completare la quer) e visto che where usa anche i placeholders e.g. :coll_id allora gli passi anche i params = {"coll_id":collection_id, "status":status}  (dizionario con i valori da sostituire ai placeholders)
        rows = await self.fetchall(
            f"""SELECT * FROM documents {where}
            ORDER BY created_at DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY""",
            params
        )
        return [dict(r._mapping) for r in rows], total or 0    #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale

class IngestionJobRepository(BaseRepository):

    async def get_by_document(self, document_id: str) -> dict | None:
        row = await self.fetchone(
            "SELECT * FROM ingestion_jobs WHERE document_id = :id",
            {"id": document_id}
        )
        return dict(row._mapping) if row else None   #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale

    async def update_status(
        self,
        document_id: str,
        status: str,
        celery_task_id: str | None = None,
        error_msg: str | None = None,
        progress_pct: int = 0,
    ) -> None:
        await self.execute(
            """
            UPDATE ingestion_jobs
            SET status = :status,
                celery_task_id = COALESCE(:task_id, celery_task_id),
                error_msg = :err,
                progress_pct = :pct,
                started_at = CASE WHEN :status = 'running' THEN SYSUTCDATETIME() ELSE started_at END,
                finished_at = CASE WHEN :status IN ('done','failed') THEN SYSUTCDATETIME() ELSE NULL END
            WHERE document_id = :doc_id
            """,
            {
                "status": status,
                "task_id": celery_task_id,
                "err": error_msg,
                "pct": progress_pct,
                "doc_id": document_id,
            }
        )


