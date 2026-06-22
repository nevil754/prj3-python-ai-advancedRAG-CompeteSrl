from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from contextlib import asynccontextmanager  #import context manager async, serve x startup e shatdown dell'app
from typing import AsyncGenerator   #x typing python, serve per dire che la funzione produce un generatore async (yield) che non restituisce valori (None)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger   #plugin x logging avanzato
from app.core.observability import setup_all  #import tutta la parte di observability (logging, tracing, metrics, ect)
from app.core.settings import get_settings  #get_settings() lo userai dopo, serve per leggere file config.yaml

settings = get_settings()

@asynccontextmanager   #trasforma funct in startup/shutdown manager quindi fastapi esegue il code prima di Yield è lo startup, mentre il code dopo lo Yield è lo shutdown
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(f"Avvio {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment {settings.app_environment}")
    setup_all(settings)
    await _check_services()  #function here qua sotto
    if settings.app_environment != "development":   #se sei in production, ovviamente devi prima caricare tutti i models prima che l'utente possa usare l'app!
        await _preload_models()
    logger.info("Startup completato, app pronta")
    yield  #YIELD, qua sopra tutto il code di startup, qua sotto tutto il code di shutdown(cosa fare quando l'app viene chiusa dall'utente)
    logger.info("Shutdown in corso...")
    try:
        from app.db.sqlserver import get_async_engine  #import SQLAlchemy async engine
        await get_async_engine().dispose()  #chiude tutte le connessioni al db SQL Server
        logger.info("Engine SQL Server chiuso")
    except Exception as e:
        logger.warning(f"Errore chiusura engine: {e}")
    try:
        from app.core.redis_client import get_redis, get_cache_redis  #import da Redis le funzioni per ottenere le connessioni
        await get_redis().aclose()  #close
        await get_cache_redis().aclose()  #close
        logger.info("Connessioni Redis chiuse")
    except Exception as e:
        logger.warning(f"Errore chiusura Redis: {e}")
    logger.info("Shutdown completato")

def create_app() -> FastAPI:  #🔥app factory 
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        docs_url="/docs" if settings.app_debug else None,   #abilita docs_url="/docs" solo se app_debug=True. 
        redoc_url="/redoc" if settings.app_debug else None,   #abilita redoc_url="/redoc" solo se app_debug=True
        openapi_url="/openapi.json" if settings.app_debug else None,   #abilita openapi_url="/openapi.json" solo se app_debug=True
        #in questo modo in Production il settings.app_debug è False quindi meno logs, e anche questi 3 here si settano a None, ok.
        lifespan=lifespan,   #collega startup/shutdown manager
    )

    #chain middlewares

    # CORS, ovviamente in prod restringi origins alla tua app
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_debug else ["https://FRONTEND-OR-BACKENDASPNETCORE"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )  #🔥in production vedi bene come settare x security

    from app.api.middleware.logging import LoggingMiddleware  #import il tuo custom middleware, x logging strutturato for each req
    app.add_middleware(LoggingMiddleware)
    from app.api.middleware.tenant import TenantMiddleware  #import il tuo custom middleware, per estrre il tenant dal JWT
    app.add_middleware(TenantMiddleware)
    from app.api.routes.health import router as health_router   #import il tuo custom file
    from app.api.routes.auth import router as auth_router   #import il tuo custom file
    app.include_router(health_router)  #monta  '/health' endpoint
    app.include_router(auth_router, prefix="/api/v1")  #monta  '/api/v1/auth' prefix endpoint

    from app.api.routes.chat import router as chat_router
    app.include_router(chat_router, prefix="/api/v1")

    # from app.api.routes.documents import router as documents_router
    # from app.api.routes.collections import router as collections_router
    # from app.api.routes.users import router as users_router
    # from app.api.routes.jobs import router as jobs_router
    # app.include_router(documents_router, prefix="/api/v1")
    # app.include_router(collections_router, prefix="/api/v1")
    # app.include_router(users_router, prefix="/api/v1")
    # app.include_router(jobs_router, prefix="/api/v1")
    return app

async def _check_services() -> None:  #function health x startup
    from app.core.redis_client import TenantRedis    #ur custom
    from app.db.sqlserver import TenantDB    #ur custom
    from app.core.vectorstore import get_async_qdrant_client   #ur custom
    redis_ok = await TenantRedis.ping()  #check che redis sia raggiungibile
    if not redis_ok:
        logger.warning("Redis non raggiungibile all'avvio — retry automatici in corso")
    else:
        logger.info("Redis: connesso!")
    sql_ok = await TenantDB.ping()   #check che sql sia raggiungibile
    if not sql_ok:
        logger.warning("SQL Server non raggiungibile all'avvio")
    else:
        logger.info("SQL Server: connesso!")
    try:
        client = get_async_qdrant_client()
        await client.get_collections()  #check se riesci a connetterti alle collections di qdrant
        logger.info("Qdrant: connesso")
    except Exception as e:
        logger.warning(f"Qdrant non raggiungibile all'avvio: {e}")

async def _preload_models() -> None:
    try:
        import asyncio  #x use aync and await
        from app.core.embeddings import get_embedding_model, get_reranker_model    #ur custom
        loop = asyncio.get_event_loop()    #ottieni event loop corrente, x eseguire code async in parallelo
        await loop.run_in_executor(None, get_embedding_model)   #🔥CARICA MODELLO Embedding IN THREAD SEPARATO!!
        logger.info("Modello embedding pre-caricato")
        from app.core.settings import get_settings    #riprendi get_settings 
        if get_settings().reranker_enabled:
            await loop.run_in_executor(None, get_reranker_model)  #🔥CARICA MODELLO Reranker IN THREAD SEPARATO!!
            logger.info("Reranker pre-caricato")
    except Exception as e:
        logger.warning(f"Pre-caricamento modelli fallito: {e}")

app = create_app()  #uvicorn usa questa istanza


