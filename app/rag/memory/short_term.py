# =============================================================
# app/rag/memory/short_term.py
# Short-term memory: ultimi N turni conversazione in Redis.
# TTL configurabile, scade automaticamente dopo inattività.
# =============================================================

from __future__ import annotations     #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
import json
from dataclasses import dataclass  #decoratore da mettere sulla classe e ti da auto __init__, __repr__, __eq__ e altri metodi utili 
from loguru import logger
from app.core.redis_client import TenantRedis
from app.core.settings import get_settings


settings = get_settings()

@dataclass
class ChatMessage:
    role: str       #user | assistant | system
    content: str

class ShortTermMemory:
    """
    Gestisce la memoria a breve termine di una conversazione.
    I messaggi vivono in Redis con TTL — scadono automaticamente.
    Uso:
        mem = ShortTermMemory(redis, conversation_id="uuid")
        await mem.add("user", "Qual è la scadenza del contratto?")
        await mem.add("assistant", "La scadenza è il 31/12/2024.")
        messages = await mem.get_all()
    """
    def __init__(self, redis: TenantRedis, conversation_id: str):
        self.redis = redis
        self.conversation_id = conversation_id
        self.max_turns = settings.memory_short_term_turns

    async def add(self, role: str, content: str) -> None:
        """Aggiunge un messaggio alla sessione."""
        await self.redis.append_message(   #append_message() è il tuo custom
            session_id=self.conversation_id,
            message={"role": role, "content": content},
            max_turns=self.max_turns,
        )

    async def get_all(self) -> list[ChatMessage]:
        """Ritorna tutti i messaggi della sessione corrente."""
        raw = await self.redis.get_session(self.conversation_id)
        return [ChatMessage(role=m["role"], content=m["content"]) for m in raw]

    async def get_formatted(self) -> str:
        """Formatta la storia per includerla nel prompt."""
        messages = await self.get_all()  #here function qua sopra
        if not messages:
            return "Nessuna conversazione precedente."
        lines = []
        for msg in messages:
            prefix = "Utente" if msg.role == "user" else "Assistente"
            lines.append(f"{prefix}: {msg.content}")  #costruzione str
        return "\n".join(lines)  #separa ogni elemento con '\n'

    async def clear(self) -> None:
        """Cancella tutta la sessione."""
        await self.redis.clear_session(self.conversation_id)

    async def count(self) -> int:
        """Numero di messaggi in sessione."""
        messages = await self.get_all()   #here function qua sopra
        return len(messages)


