# =============================================================
# app/workers/scheduled_tasks.py
# Task periodici schedulati con Redbeat (Celery Beat su Redis).
# Registrati all'avvio del celery-beat container.
# =============================================================

from __future__ import annotations   #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from datetime import timedelta
from celery.schedules import crontab   #x linux cron e.g. crontab(hour=0, minute=0) vuol dire ogni giorno a mezzanotte
from loguru import logger
from sqlalchemy import text
from app.workers.celery_app import celery_app   #istanza celery globale


# Questi vengono letti da celery-beat all'avvio
#registrazione tasks periodici
celery_app.conf.beat_schedule = {
    "rollup-usage-daily": {   #x rollup usage stats per billling
        "task": "app.workers.scheduled_tasks.rollup_usage",
        "schedule": crontab(hour=0, minute=0),  #ogni giorno a mezzanotte
    },
    "expire-sessions-hourly": {    #x pulizia sessioni orfane
        "task": "app.workers.cleanup_tasks.expire_sessions",
        "schedule": timedelta(hours=1),   #ogni ora
    },
}


@celery_app.task(
    name="app.workers.scheduled_tasks.rollup_usage",
    acks_late=True,   #🔥il task viene confermato successfully solo DOPO il completamento
)
def rollup_usage() -> dict:
    """
    Aggrega e salva usage stats giornaliero per tutti i tenant.
    Legge i contatori Redis accumulati durante il giorno
    e li persiste in shared.usage_stats su SQL Server.
    Chiamato ogni notte da celery-beat.  MA UTILIZZO REDBEAT per persistere vero??
    """
    import asyncio   #x async funct
    from app.db.sqlserver import tenant_db   #ur custom
    from app.core.redis_client import get_redis

    async def _get_all_tenants():   #legge tutti i tentants attivi
        async with tenant_db._async_factory() as session:
            result = await session.execute(
                text("SELECT id, slug FROM shared.tenants WHERE is_active = 1")
            )
            return result.fetchall()  #fetches all (or all remaining) rows of a query result, return list of tuples
    async def _get_tenant_stats( tenant_id: str ):
        """Legge contatori Redis per il tenant."""
        client = get_redis()
        today = __import__("datetime").date.today().isoformat()   #e.g. 2026-06-15
        base = f"tenant:{tenant_id}:stats:{today}"  #e.g. tenant:123:stats:2026-06-15
        pipe = client.pipeline()    #crea pipeline= batch di operazioni (piu veloce)
        pipe.get(f"{base}:tokens_in")   #lettura e.g. tenant:123:stats:2026-06-15:tokens_in
        pipe.get(f"{base}:tokens_out")
        pipe.get(f"{base}:queries")
        pipe.get(f"{base}:docs_ingested")
        results = await pipe.execute()   #esecuzione
        return {
            "tokens_in": int(results[0] or 0),   #è il valore di pipe.get(f"{base}:tokens_in")
            "tokens_out": int(results[1] or 0),
            "queries_count": int(results[2] or 0),
            "docs_ingested": int(results[3] or 0),
        }
    loop = asyncio.new_event_loop()    #event loop manuale x chiamare funzione async da sync, in questo caso per invalidare cache query dopo ingestion, altrimenti la cache sarebbe stale (il doc è nuovo ma la cache non lo sa)
    tenants = loop.run_until_complete( _get_all_tenants() )  #function annidata here qua sopra 
    saved = 0
    for tenant in tenants:
        stats = loop.run_until_complete( _get_tenant_stats(str(tenant.id)) )   #function annidata here qua sopra 
        if stats["queries_count"] == 0 and stats["docs_ingested"] == 0:   #skip tenants inattivi! (di oggi)
            continue
        # Usa _sync_factory() direttamente: SA ha accesso allo schema shared senza impersonation.
        # get_session("shared") cercherebbe usr_tenant_shared che non esiste.
        with tenant_db._sync_factory() as session:
            session.execute(
                text("""
                    MERGE shared.usage_stats AS target
                    USING (VALUES (:tenant_id, CAST(SYSUTCDATETIME() AS DATE),
                           :tokens_in, :tokens_out, :queries_count, :docs_ingested))
                    AS source (tenant_id, stat_date, tokens_in, tokens_out,
                               queries_count, docs_ingested)
                    ON target.tenant_id = source.tenant_id
                       AND target.stat_date = source.stat_date
                    WHEN MATCHED THEN UPDATE SET
                        tokens_in = target.tokens_in + source.tokens_in,
                        tokens_out = target.tokens_out + source.tokens_out,
                        queries_count = target.queries_count + source.queries_count,
                        docs_ingested = target.docs_ingested + source.docs_ingested
                    WHEN NOT MATCHED THEN INSERT
                        (tenant_id, stat_date, tokens_in, tokens_out,
                         queries_count, docs_ingested)
                    VALUES (source.tenant_id, source.stat_date, source.tokens_in,
                            source.tokens_out, source.queries_count, source.docs_ingested);
                """),
                {
                    "tenant_id": str(tenant.id),
                    **stats,  # {"tokens_in": ..., "tokens_out": ..., "queries_count": ..., "docs_ingested": ...}
                }
            )
            session.commit()
        saved += 1
    loop.close()
    logger.info(f"Usage rollup completato: {saved} tenant salvati")
    return {"tenants_saved": saved}


