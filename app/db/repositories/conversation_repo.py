# =============================================================
# app/db/repositories/conversation_repo.py
# Query DB per conversazioni e messaggi.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import json
from app.db.repositories.base import BaseRepository


class ConversationRepository(BaseRepository):

    async def get_or_create(
        self,
        conversation_id: str,
        user_id: str,
        mode: str = "rag",
    ) -> dict:
        """Crea conversazione se non esiste, altrimenti ritorna quella esistente."""
        await self.execute(
            """
            IF NOT EXISTS (SELECT 1 FROM conversations WHERE id = :id)
                INSERT INTO conversations (id, user_id, mode)
                VALUES (:id, :user_id, :mode)
            """,
            {"id": conversation_id, "user_id": user_id, "mode": mode}
        )
        row = await self.fetchone(     #fetchone() prende 1 row
            "SELECT * FROM conversations WHERE id = :id",
            {"id": conversation_id}
        )
        return dict(row._mapping) if row else {}   #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        sources: list[dict] | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
        hallucination_score: float | None = None,
    ) -> int:
        """Salva un messaggio e ritorna il suo ID."""
        result = await self.execute(
            """
            INSERT INTO messages
                (conversation_id, role, content, sources, tokens_in, tokens_out, latency_ms, hallucination_score)
            OUTPUT INSERTED.id
            VALUES (:conv_id, :role, :content, :sources, :tokens_in, :tokens_out, :latency_ms, :hall_score)
            """,
            {
                "conv_id": conversation_id,
                "role": role,
                "content": content,
                "sources": json.dumps(sources or []),   #converts python obj in corrisponding json formatted string
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
                "hall_score": hallucination_score,
            }
        )  #OUTPUT INSERTED.id ritorna l'id del messaggio appena inserito, che viene catturato in result
        row = result.fetchone()
        return row[0] if row else 0   #ritorna id del mex appena inserito 

    async def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[dict]:
        # SELECT TOP (:limit) con named param non è supportato da SQL Server.
        # Si usa OFFSET/FETCH che funziona con parameterized queries.
        rows = await self.fetchall(
            """
            SELECT *
            FROM messages
            WHERE conversation_id = :conv_id
            ORDER BY created_at ASC
            OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
            """,
            {"conv_id": conversation_id, "limit": limit}
        )
        return [ dict(r._mapping) for r in rows ]  #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale

    async def list_conversations(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:  #tuple si data structure è come una list ma ordinata (mantiene l'ordine) ed è immutabile (non modificabile)
        offset = (page-1) * page_size   
        total = await self.scalar(
            "SELECT COUNT(*) FROM conversations WHERE user_id = :uid AND is_archived = 0",
            {"uid": user_id}
        )  #scalar() ritorna il primo valore della prima riga del result set, in questo caso il count totale di conversazioni per l'utente
        rows = await self.fetchall(  #.fetchall() ritorna tutte le righe del result set come lista di row, in questo caso tutte le conversazioni per l'utente con paginazione
            """
            SELECT * FROM conversations
            WHERE user_id = :uid AND is_archived = 0
            ORDER BY updated_at DESC
            OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
            """,
            {"uid": user_id, "offset": offset, "limit": page_size}  #'OFFSET :offset ROWS' number skipped rows, 'FETCH NEXT :limit ROWS ONLY' number of rows to return after offset
        )  #offset è quante rows iniziali 'salti'
        return [dict(r._mapping) for r in rows], total or 0    #_mapping converte row sqlalchemy (e.g. rows = await db.execute(....)) in dict-like, dict() converte in dict normale!

    async def save_summary(
        self,
        conversation_id: str,
        user_id: str,
        summary_text: str,
        turn_count: int,
    ) -> None:
        """Salva il summary di una conversazione (long-term memory)."""
        await self.execute(
            """
            INSERT INTO conversation_summaries
                (conversation_id, user_id, summary_text, turn_count, from_turn, to_turn)
            VALUES (:conv_id, :user_id, :summary, :turns, 0, :turns)
            """,
            {
                "conv_id": conversation_id,
                "user_id": user_id,
                "summary": summary_text,
                "turns": turn_count,
            }
        )

    async def get_recent_summaries(self, user_id: str, limit: int = 3) -> list[str]:
        rows = await self.fetchall(
            """
            SELECT summary_text
            FROM conversation_summaries
            WHERE user_id = :uid
            ORDER BY created_at DESC
            OFFSET 0 ROWS FETCH NEXT :limit ROWS ONLY
            """,
            {"uid": user_id, "limit": limit}
        )
        return [ r.summary_text for r in rows ]

