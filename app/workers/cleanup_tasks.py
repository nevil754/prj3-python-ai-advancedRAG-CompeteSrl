# =============================================================
# app/workers/cleanup_tasks.py
# Task Celery per manutenzione e pulizia.
# =============================================================

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from loguru import logger  #x logging strutturato
from sqlalchemy import text   #x query sql manuali
from app.workers.celery_app import celery_app  #ur custom


@celery_app.task(
    name="app.workers.cleanup_tasks.purge_tenant",   #the name
    acks_late=True,  #🔥🔥il task viene confermato successfully solo DOPO il completamento 
)
def purge_tenant(tenant_id: str, tenant_slug: str) -> dict:  #funct fa DELETE COMPLETO e irreversibile X L'UTENTE, cancella sql schema - qdrant collections - redis keys
    """
    Offboarding completo di un tenant.
    Cancella: schema SQL Server, collection Qdrant, chiavi Redis.
    IRREVERSIBILE — usare con cautela.
    """
    import asyncio   #x async functions
    from app.db.sqlserver import tenant_db
    from app.core.vectorstore import adelete_tenant_collections
    from app.core.redis_client import TenantRedis

    logger.warning(f"Purge tenant avviato: {tenant_slug}")
    loop = asyncio.new_event_loop()  #crea event loop manuale  
    loop.run_until_complete( adelete_tenant_collections(tenant_slug) )   #esegue il delete sul tenant tenant_{safe_slug}_documents e anche sul tenant tenant_{safe_slug}_memory
    loop.close()  
    loop = asyncio.new_event_loop()   #crea event loop manuale 
    redis = TenantRedis( tenant_id = tenant_id )
    deleted_keys = loop.run_until_complete( redis.flush_tenant() )   #cancella tutte le chiavi redis del tenant!
    loop.close()
    schema_name = "tenant_" + tenant_slug.replace("-", "_")
    with tenant_db._sync_factory() as session:
        session.execute(
            text("UPDATE shared.tenants SET is_active = 0 WHERE slug = :slug"),
            {"slug": tenant_slug}
        )   #disabilita tenant prima di cancellarlo!
        session.execute(text(f"DROP SCHEMA IF EXISTS [{schema_name}]"))  #⚠️⚠️ DROP SCHEMA è irreversibile, IN VERA PRODUCTION magari è consigliato solo disabilitare!
        session.commit()   #senza commit le modifiche vengono rollbacked al close()
            #lo schema deve essere completamente vuoto!! altrimenti potresti avere errori t-sql tipo  'Cannot drop schema 'X' because it is being referenced by object 'Y''
    logger.info(
        "Purge tenant completato",
        tenant=tenant_slug,
        redis_keys_deleted=deleted_keys,
    )   #x logging strutturato
    return {"status": "purged", "tenant": tenant_slug}   #return dict


@celery_app.task(
    name="app.workers.cleanup_tasks.expire_sessions",   #the name
    acks_late=True,    #🔥🔥il task viene confermato successfully solo DOPO il completamento 
)
def expire_sessions() -> dict:
    """
    Pulizia sessioni Redis scadute.
    Eseguito periodicamente da celery-beat!
    Redis gestisce i TTL automaticamente, ma questo task
    fa pulizia esplicita per chiavi senza TTL o orfane.
    """
    import asyncio   #x async functs
    from app.core.redis_client import get_redis   #ur custom

    async def _cleanup():
        client = get_redis()
        #cerca chiavi sessione senza TTL(time-to-live) cioe anomalie
        cursor = 0   #paginazione redis scan
        fixed = 0    #contatore modifiche
        while True:
            cursor, keys = await client.scan( cursor=cursor, match="tenant:*:session:*", count=200 )  #cerca chiavi redis con pattern session tenant, e prende a batchs di 200
            for key in keys:
                ttl = await client.ttl(key)  #check ttl della key target
                if ttl == -1:  #se è -1, cioe quindi nessun TTL impostato
                    await client.expire(key, 86400)  #imposta ttl a 24h
                    fixed += 1
            if cursor == 0:  #se ritorna all'inizio cioe a 0, allora abbiamo finito di scansionare tutte le chiavi
                break
        return fixed
    
    loop = asyncio.new_event_loop()
    fixed = loop.run_until_complete( _cleanup() )
    loop.close()
    logger.info(f"Session cleanup: {fixed} chiavi senza TTL corrette")
    return {"fixed_keys": fixed}


