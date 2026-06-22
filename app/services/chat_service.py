# =============================================================
# app/services/chat_service.py
# Orchestrazione completa di una query RAG.
# Coordina: cache → retrieval → generation → memory → DB.
# =============================================================

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import hashlib   #x creare le hash x le queries
import json   #x fare json.dumps() converts python obj in corrisponding json formatted string
import time
from typing import AsyncGenerator, Any  
from uuid import uuid4
from loguru import logger   #x logging strutturato
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession  #x session db asyncrona
from app.core.redis_client import TenantRedis
from app.core.settings import get_settings
from app.rag.retrieval.retriever import retrieve
from app.rag.generation.chain import arun_rag_chain, astream_rag_chain  #versione normale e versione streaming sse
from app.rag.memory.context_builder import format_sources_for_response


settings = get_settings()

class ChatService:
    """
    Servizio che gestisce il ciclo completo di una query RAG.
    Flusso completo:
    1. Check cache Redis (risposta già calcolata?)
    2. Carica sessione chat da Redis (short-term memory)
    3. Retrieval: dense + sparse -> RRF -> MMR -> reranker
    4. Generation: prompt -> LLM -> risposta
    5. Salva messaggio in SQL Server
    6. Aggiorna sessione Redis
    7. Salva in cache Redis
    8. Incrementa usage stats
    """

    def __init__(
        self,
        db: AsyncSession,
        redis: TenantRedis,
        tenant_id: str,
        tenant_slug: str,
        user_id: str,
    ):
        self.db = db
        self.redis = redis
        self.tenant_id = tenant_id
        self.tenant_slug = tenant_slug
        self.user_id = user_id

    async def query(
        self,
        question: str,
        conversation_id: str | None = None,
        collection_id: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """
        Esegue una query RAG completa (non streaming).
        Returns:
            dict con answer, conversation_id, message_id, sources, ecc.
        """
        conv_id = conversation_id or str(uuid4())   #se l'utente non ha una conversazione, crei un uuid4 nuovo
        query_hash = _hash_query( question, conv_id )   #_hash_query() è here in basso a file
        cached = await self.redis.get_query_cache(query_hash)  #cerchi risposta gia cachata 
        if cached:
            logger.debug("Cache hit per query RAG")
            return json.loads(cached)   #ovviamente se il result di questa target query è ancora valida in cache, allora usa quella e risparmi energia computazionale
        session_messages = await self.redis.get_session(conv_id)  #🔥carichi session target (short-term memory)
        chunks = await retrieve(  #retrieval (async — non blocca l'event loop)
            query=question,
            tenant_slug=self.tenant_slug,
            tenant_id=self.tenant_id,
            collection_id=collection_id,
        )
        result = await arun_rag_chain(   #runni versione normale (no stream SSE)
            question=question,
            chunks=chunks,
            session_messages=session_messages,
        )
        message_id = await self._save_messages(   #salva mexs in sqlserver
            conv_id=conv_id,
            question=question,
            answer=result["answer"],
            sources=result["sources"],
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
            latency_ms=result.get("latency_ms", 0),
        )
        await self.redis.append_message( conv_id, {
            "role": "user", "content": question
        }, settings.memory_short_term_turns)  #alla sessione target di redis aggiungi nella cache {conversationid , {user, content}, limite turni(per mantenere solo gli ultimi N turni) }.
        #AGGIUNGI IL MEX ALLA CRONOLOGIA DELLA CONVERSAZIONE(sessione) gestita da redis; pero se vuoi sapere se una query è gia stata fatta dovresti leggere tutta la cronologia->cercare la domanda->verificare che sia identica 🥵🥵🥵, quindi in quel caso meglio salvare obj in cache sotto una key target!(lo fai here qua sotto w set_query_cache()!!)
        await self.redis.append_message(conv_id, {
            "role": "assistant", "content": result["answer"]
        }, settings.memory_short_term_turns)   #fai la stessa cosa per role 'assistant'🔥!! cosi hai chat multi-turno!
        #in questo modo su redis in target session, salvi sia la domanda dell'user che la risposta!
        response = {  #build obj 
            "answer": result["answer"],
            "conversation_id": conv_id,
            "message_id": message_id,
            "sources": result["sources"],   #citazioni
            "tokens_in": result.get("tokens_in"),
            "tokens_out": result.get("tokens_out"),
            "latency_ms": result.get("latency_ms"),
        }
        await self.redis.set_query_cache( query_hash, json.dumps(response) )   #salvi la risposta su cache, json.dumps() converts python obj in corrisponding json formatted string. CON QUESTO SALVI EFFETTIVAMENTE IN CACHE UN OBJ sotto una key target.
        await self._increment_usage_stats(
            tokens_in=result.get("tokens_in", 0),  #0 is fallback
            tokens_out=result.get("tokens_out", 0),
        )
        return response

    async def stream_query(   #stream SSE token-by-token!
        self,
        question: str,
        conversation_id: str | None = None,
        collection_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Esegue una query RAG in streaming — genera token per token.
        Controlla la cache prima di iniziare; se hit, yield risposta cached in un colpo solo.
        """
        conv_id = conversation_id or str(uuid4())
        query_hash = _hash_query(question, conv_id)
        cached = await self.redis.get_query_cache(query_hash)
        if cached:
            logger.debug("Cache hit per query RAG (streaming)")
            cached_data = json.loads(cached)  #converts json strutturato in corrisponding python obj
            yield cached_data.get("answer", "")  #"" as fallback
            # Emette il sentinel anche in cache-hit così il client riceve sources e conversation_id
            yield "\x1e" + json.dumps({  #⚡️⚡️usi char SENTINELLA ("\x1e") cosi che dopo che hai passato il text normale per ultimo passi anche e.g. '\x1e{"sources":[...],"conversation_id":"abc"}' CHE SONO I METADATI che vuoi che il frontend riceva!
                "sources": cached_data.get("sources", []),
                "conversation_id": conv_id,
                "latency_ms": cached_data.get("latency_ms"),
            })
            return
        session_messages = await self.redis.get_session(conv_id)
        chunks = await retrieve(
            query=question,
            tenant_slug=self.tenant_slug,
            tenant_id=self.tenant_id,
            collection_id=collection_id,
        )
        start = time.time()
        full_answer = ""
        async for token in astream_rag_chain(   #ora che hai tutto quello che ti serve, lo passi al frontend via stream
            question=question,
            chunks=chunks,
            session_messages=session_messages,
        ):
            full_answer += token
            yield token
        latency_ms = round((time.time() - start) * 1000)
        await self._save_messages(   #salvi su tabelle sqlserver conversations e messages
            conv_id=conv_id,
            question=question,
            answer=full_answer,
            sources=format_sources_for_response(chunks),
            latency_ms=latency_ms,
        )
        await self.redis.append_message(conv_id, {"role": "user", "content": question}, settings.memory_short_term_turns)
        await self.redis.append_message(conv_id, {"role": "assistant", "content": full_answer}, settings.memory_short_term_turns)
        response_to_cache = {   #obj da salvare su cache sotto key target
            "answer": full_answer,
            "conversation_id": conv_id,
            "sources": format_sources_for_response(chunks),
            "latency_ms": latency_ms,
        }
        await self.redis.set_query_cache(query_hash, json.dumps(response_to_cache))
        yield "\x1e" + json.dumps({  #⚡️⚡️usi char SENTINELLA ("\x1e") cosi che dopo che hai passato il text normale per ultimo passi anche e.g. '\x1e{"sources":[...],"conversation_id":"abc"}' CHE SONO I METADATI che vuoi che il frontend riceva!
            "sources": format_sources_for_response(chunks),
            "conversation_id": conv_id,
            "latency_ms": latency_ms,
        })

    async def _save_messages(
        self,
        conv_id: str,
        question: str,
        answer: str,
        sources: list[dict],   #citazioni
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: int = 0,
    ) -> int:
        """Salva domanda + risposta in SQL Server. Ritorna message_id della risposta."""
        from app.core.settings import get_settings
        settings = get_settings()
        await self.db.execute(   #query raw 
            text("""
                IF NOT EXISTS (SELECT 1 FROM conversations WHERE id = :id)
                INSERT INTO conversations (id, user_id, mode)
                VALUES (:id, :user_id, 'rag')
            """),   #i ':' sono x i placeholders
            {"id": conv_id, "user_id": self.user_id}
        )  #crei la conversazione se non esiste

        await self.db.execute(
            text("""
                INSERT INTO messages (conversation_id, role, content)
                VALUES (:conv_id, 'user', :content)
            """),
            {"conv_id": conv_id, "content": question}
        )  #salvi mex utente

        result = await self.db.execute(
            text("""
                INSERT INTO messages
                    (conversation_id, role, content, sources, tokens_in, tokens_out, latency_ms)
                OUTPUT INSERTED.id
                VALUES (:conv_id, 'assistant', :content, :sources, :tokens_in, :tokens_out, :latency_ms)
            """),   #output inserted.id ritorna l'id della riga appena inserita
            {
                "conv_id": conv_id,
                "content": answer,
                "sources": json.dumps(sources),  #json.dumps() converts python obj in corrisponding json formatted string
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "latency_ms": latency_ms,
            }
        )  #salvi risposta dell'assistant!
        row = result.fetchone()
        return row[0] if row else 0


    async def _increment_usage_stats( self, tokens_in: int, tokens_out: int ) -> None:
        """Incrementa contatori Redis per il rollup notturno. serve x analytics!"""
        from datetime import date
        today = date.today().isoformat()   #data di oggi e.g.2026-06-09
        base = f"tenant:{self.tenant_id}:stats:{today}"
        pipe = self.redis._redis.pipeline()   # crea pipeline= batch di operazioni (piu veloce)
        #incrementa i contatori tuoi di redis
        pipe.incrby(f"{base}:tokens_in", tokens_in)   #incrementa tokens_in del redis session target
        pipe.incrby(f"{base}:tokens_out", tokens_out)  #**
        pipe.incr(f"{base}:queries")   #incrementa queries di 1 ogni volta che fai una query, senza tokens_in/out, solo numero query totali
        #setta l'expire dei contatori
        pipe.expire(f"{base}:tokens_in", 172800)   #48h TTL(time-to-live), redis cancella automaticamente la chiave dopo 48h, cosi non accumuli dati vecchi inutili
        pipe.expire(f"{base}:tokens_out", 172800)
        pipe.expire(f"{base}:queries", 172800)
        await pipe.execute()   #invia batch di operazioni a redis


def _hash_query(question: str, conv_id: str) -> str:
    """Hash deterministica per la cache query."""
    normalized = question.strip().lower()  #elimini spazi laterali e rendi tutto minuscolo
    return hashlib.md5(f"{conv_id}:{normalized}".encode()).hexdigest()   #🔥🔥crei hash md5 di conv_id + domanda normalizzata, cosi se stessa domanda in conversazione diversa, hai hash diverso, e.g. conv1:ciao -> hash1, conv2:ciao -> hash2 diverso da hash1

