# app/core/redis_client.py
# TenantRedis: wrapper Redis con namespace isolation per tenant.
# Ogni chiave è prefissata con tenant:{id}: per isolamento completo.
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import json
from functools import lru_cache  #x singleton cache
from typing import Any  #x typing generico python
import redis.asyncio as aioredis   #x Redis asincrono🔥 (non blocca FastAPI!)
from loguru import logger

@lru_cache(maxsize=1)   #decoratore che trasforma la funzione in un singleton, quindi get_qdrant_client() ritorna sempre la stessa istanza di QdrantClient, evitando overhead di connessioni multiple
def get_redis() -> aioredis.Redis:  #crea una sola connessione x processo
    """
    Ritorna il client Redis asincrono (singleton).
    Connesso al DB 0, questo verra utilizzato x sessioni, broker, rate limit
    """
    from app.core.settings import get_settings
    settings = get_settings()
    logger.info("Connessione Redis", url=settings.redis_url)
    return aioredis.from_url(    #return client Redis async (xk utilizzo aioredis)
        settings.redis_url,
        decode_responses=True,      #redis return stringhe non bytes
        socket_connect_timeout=5,   #timeout connessione Redis
        socket_timeout=5,         #timeout operazioni Redis
        retry_on_timeout=True,    #resilienza contro timeout temporanei
    )

@lru_cache(maxsize=1)
def get_cache_redis() -> aioredis.Redis:
    """
    Client Redis per il DB 1, cache RAG separata dal broker.
    serve x cache RAG, cosi puoi fare FLUSH cache senza rompere code Celery!!
    """
    from app.core.settings import get_settings
    settings = get_settings()
    return aioredis.from_url(  #crea client Redis async
        settings.redis_cache_url,   #GET L'URL DAI SETTINGS PER LA CACHE!!
        decode_responses=True,  #redis return stringhe non bytes
        socket_connect_timeout=5,  #timeout connessione Redis
        socket_timeout=5,  #timeout operazioni Redis
    )

class TenantRedis:
    """
    Wrapper Redis con namespace isolation per tenant.
    Tutte le chiavi sono prefissate con 'tenant:{tenant_id}:'.
    Uso:
        redis = TenantRedis(tenant_id="acme-uuid")
        await redis.set_session(session_id, messages)
        await redis.get_query_cache(query_hash)
    """
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._redis = get_redis()
        self._cache = get_cache_redis()

    def _key(self, *parts: str) -> str:
        """Costruisce chiave prefissata con tenant_id."""
        return f"tenant:{self.tenant_id}:" + ":".join(parts)  #e.g. self._key("session", "123") -> tenant:abc123:session:123

    async def get_session(self, session_id: str) -> list[dict]:   #session chat (short-term memory)
        """
        Ritorna gli ultimi N messaggi della conversazione da Redis.
        Usato dal context_builder prima di ogni query RAG.
        """
        key = self._key("session", session_id)  #ottieni e.g. tenant:abc123:session:123 la parte di 'session' e '123'(che sarebbe il session_id)
        raw = await self._redis.lrange(key, 0, -1)  #ur redis self (che è a sua volta un get_redis()), e prende la lista di messaggi (che sono stringhe JSON) con lrange (0,-1 prende tutta la lista!) utilizzando la key (ur custom)
        return [ json.loads(m) for m in raw ]   #la lista di mex in json (cioe raw), per ciascun mex lo converto in python e lo metto nella lista ('[]')
          #return a list of python dict

    async def append_message(
        self,
        session_id: str,
        message: dict,
        max_turns: int = 10,
    ) -> None:
        """
        Aggiunge un messaggio alla sessione e mantiene solo gli ultimi max_turns*2.
        (max_turns*2 perché ogni turno = 1 user + 1 assistant)
        """
        from app.core.settings import get_settings
        settings = get_settings()
        key = self._key("session", session_id)   #ottieni la key costruita e.g. tenant:abc123:session:123
        ttl = settings.cache_session_ttl_seconds   #time-to-live
        pipe = self._redis.pipeline()   #pipeline= batch di operazioni (piu veloce)
        pipe.rpush(key, json.dumps(message, ensure_ascii=False))  #aggiunge message alla pipeline, json.dumps() converts in json, ensure_ascii=False per supportare caratteri unicode senza escape
        pipe.ltrim(key, -(max_turns * 2), -1)  #avendo tutta la pipeline, mantiene solo i mex dalla coda max_turn*2 cioe (xk ogni turno = 1 user+1 assistant)
        pipe.expire(key, ttl)   #setta l'expire della target session ad 1h, quindi dopo 1h di inattività la sessione viene cancellata automaticamente da Redis evitando cosi l'accumulo di dati vecchi e inutili
        await pipe.execute()   #esegue tutte le operazioni in pipeline in un colpo solo

    async def clear_session(self, session_id: str) -> None:
        """Cancella la sessione, chiamato quando l'utente chiude la chat."""
        await self._redis.delete(self._key("session", session_id))  #dopo aver ottenuto la key costruita e.g. tenant:abc123:session:123 cancella la session target

    async def get_query_cache(self, query_hash: str) -> str | None:    #cache query RAG
        """
        Cerca risposta cached per questa query.
        query_hash: hash MD5/SHA del testo della query normalizzato.
        """
        return await self._cache.get(self._key("cache", "query", query_hash))   #costruisce chiave e.g. tenant:abc123:cache:query:hash123 e cerca la risposta cached in Redis, ritorna stringa o None se non trovata

    async def set_query_cache(
        self,
        query_hash: str,
        response: str,
        ttl: int | None = None,
    ) -> None:
        """Salva risposta RAG in cache con TTL configurabile."""
        from app.core.settings import get_settings
        settings = get_settings()
        key = self._key("cache", "query", query_hash)  #costruisce chiave e.g. tenant:abc123:cache:query:hash123
        await self._cache.setex(key,  ttl or settings.cache_query_ttl_seconds,  response)  #setta la risposta RAG in cache con ttl!
        #setex = set + expire insieme

    async def invalidate_query_cache(self) -> int:
        """
        Invalida tutta la cache query di questo tenant.
        Chiamato dopo ogni nuova ingestion🔥🔥, i nuovi doc cambiano le risposte.
        """
        pattern = self._key("cache", "query", "*")  #pattern e.g. tenant:abc123:cache:query:* per trovare tutte le cache query di questo tenant
        keys = await self._cache.keys(pattern)
        if keys:
            await self._cache.delete(*keys)   #cancella tutte le chiavi trovate, *keys espande la lista in argomenti separati
        return len(keys)   #return only the lenght of the keys deleted

    async def check_rate_limit(
        self,
        user_id: str,
        limit: int | None = None,
        window_seconds: int = 60,   #finestra di tempo in secondi per il rate limit, default 60s (1 minuto)
    ) -> tuple[bool, int]:   #tuple è come una list, ma mantiene l'ordine e non è mutabile 
        """
        Verifica e incrementa il rate limit per un utente.
        Returns:
            Tuple (allowed, current_count)
            allowed: True se sotto il limite, False se superato
        """
        from app.core.settings import get_settings
        settings = get_settings()
        max_requests = limit or settings.rate_limit_requests_per_minute
        key = self._key("ratelimit", user_id)  #costruisce chiave e.g. tenant:abc123:ratelimit:user123 per tracciare le richieste di questo utente
        pipe = self._redis.pipeline()
        pipe.incr(key)  #ogni req, incrementa il contatore (🔥VIENE SALVATO IN REDIS SOTTO QUESTA KEY, non la salviamo in una variabile particolare)
        pipe.expire(key, window_seconds)    #setta l'expire della target session ad X, quindi dopo X di inattività la sessione viene cancellata automaticamente da Redis evitando cosi l'accumulo di dati vecchi e inutili
        results = await pipe.execute()   #esegue tutte le operazioni in pipeline in un colpo solo
        count = results[0]   #results è un array cioè  [ 1 (è il risultato di INCR), True (è il risultato di EXPIRE) ]
        return ( count <= max_requests, count )   #return tupla (True/False, numero attuale di richieste fatte)


    async def set_job_status(
        self,
        job_id: str,
        status: dict,
        ttl: int = 86400,  #1 day
    ) -> None:
        """Salva status di un job di ingestion, polling dal frontend"""
        key = self._key("job", job_id)   #costruisce chiave e.g. tenant:abc123:job:job123 per tracciare lo status di questo job
        await self._redis.setex(key, ttl, json.dumps(status))   #json.dumps converte il dict in stringa JSON, setex salva la stringa in Redis con TTL
        #setex = set + expire insieme

    async def get_job_status(self, job_id: str) -> dict | None:
        """Legge status job, ritorna None se scaduto o inesistente."""
        raw = await self._redis.get( self._key("job", job_id) )  #ur redis self (che è a sua volta un get_redis()), e prende prende quello con key target
        return json.loads(raw) if raw else None   #json.loads converte la stringa JSON in dict python, se raw è None ritorna None

    async def flush_tenant(self) -> int:   #delete completo utente
        """
        Cancella TUTTE le chiavi di questo tenant da Redis.
        Chiamato durante l'offboarding (⚠️ QUANDO IL CLIENT CANCELLA IL SUO ACCOUNT).
        remmeber: usa SCAN non KEYS per non bloccare Redis in prod!
        """
        pattern = f"tenant:{self.tenant_id}:*"
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(  #scan itera su tutte le chiavi che matchano il pattern, evitando di bloccare Redis come farebbe KEYS in prod!!
                cursor=cursor, match=pattern, count=100  #count è N keys per iterazione
            )   #scan() di redis return a tupla (nuovo_cursor, lista_chiavi[]), il cursor è il 'segnalibro' ed avanza fino a quando arriva a fine 'libro' quindi torna all'inizio a [0]
            if keys:
                await self._redis.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        #fai stessa cosa x DB cache 🔥🔥
        cursor = 0
        while True:
            cursor, keys = await self._cache.scan(
                cursor=cursor, match=pattern, count=100
            )
            if keys:
                await self._cache.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        logger.info(f"Flush tenant Redis completato", tenant=self.tenant_id, deleted=deleted)  #log con dati strutturati, utile per e.g.opentelemetry/ELK/ect
        return deleted

    @staticmethod
    async def ping() -> bool:   #test if ok
        """Verifica che Redis sia raggiungibile. Usato in /health endpoint."""
        try:
            client = get_redis()
            return await client.ping()
        except Exception as e:
            logger.error(f"Redis ping fallito: {e}")
            return False


