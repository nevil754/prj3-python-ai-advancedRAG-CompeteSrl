# app/db/sqlserver.py
# TenantDB: gestione connessioni SQL Server con schema switching.
# Ogni request imposta lo schema del tenant sulla connessione.
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from contextlib import asynccontextmanager, contextmanager  #x creare context manager sincroni e asincroni
from functools import lru_cache        #x singleton cache
from typing import AsyncGenerator, Generator   #quando @asynccontextmanager su una funzione allora quella funzione ritorna un AsyncGenerator, mentre quando @contextmanager su una funzione quella funzione ritorna un Generator
from loguru import logger
from sqlalchemy import create_engine, event, text   #SQLAlchemy sync, sqlalchemy puo leggere sia sqlserver/postresql/mysql, text è per query raw
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine    #versione async di sqlanchemy, async_sessionmaker è la versione async di sessionmaker, create_async_engine è la versione async di create_engine
from sqlalchemy.orm import Session, sessionmaker  #Session è la classe base per le sessioni sincrone, sessionmaker è una factory per creare sessioni


class TenantDB:
    """
    Gestisce sessioni SQL Server con schema switching per tenant.
    Il pattern è:
    1. Ottieni sessione con get_session(tenant_slug)
    2. SQLAlchemy esegue "USE RAGChat; SET SCHEMA tenant_acme"
    3. Tutte le query successive trovano le tabelle del tenant corretto
    4. La sessione viene chiusa automaticamente (context manager)
    Uso (sincrono — nei worker Celery):
        with tenant_db.get_session("acme") as session:
            session.execute(text("SELECT * FROM documents"))
    Uso (asincrono — nelle route FastAPI):
        async with tenant_db.aget_session("acme") as session:
            await session.execute(text("SELECT * FROM documents"))
    """
    def __init__(self):
        self._sync_factory = sessionmaker(   #set machine che creerà sessioni pronte sincrone per il db 
            bind= get_sync_engine(),   #function here qua sotto
            autocommit= False,   #x non salvare auto le modifiche fino a quando non chiami session.commit()
            autoflush= False,  #x non mandare auto la query al db fino a quando non chiami session.commit()
        )
        self._async_factory = async_sessionmaker(   #version ASYNC 
            bind=get_async_engine(),   #function here qua sotto
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,  #dopo ogni commit, gli objs restano validi in memoria 
        )

    @contextmanager
    def get_session(self, tenant_slug: str) -> Generator[Session, None, None]:
        """
        Context manager sincrono per sessioni tenant.
        Esegue EXECUTE AS USER all'inizio e REVERT nel finally per ripristinare il contesto.
        """
        session = self._sync_factory()
        impersonated = False
        try:
            self._set_schema_sync(session, tenant_slug)
            impersonated = True
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            if impersonated:
                try:
                    session.execute(text("REVERT"))
                    session.commit()
                except Exception:
                    pass
            session.close()

    @asynccontextmanager
    async def aget_session(
        self, tenant_slug: str
    ) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager asincrono per sessioni tenant.
        Esegue EXECUTE AS USER all'inizio e REVERT nel finally per ripristinare il contesto.
        """
        async with self._async_factory() as session:
            impersonated = False
            try:
                await self._set_schema_async(session, tenant_slug)
                impersonated = True
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                if impersonated:
                    try:
                        await session.execute(text("REVERT"))
                        await session.commit()
                    except Exception:
                        pass

    def _set_schema_sync(self, session: Session, tenant_slug: str) -> None:
        """
        Imposta il contesto di esecuzione al tenant via EXECUTE AS USER.
        EXECUTE AS USER è session-scoped (il REVERT nel finally del context manager
        ripristina il contesto SA originale a fine sessione).
        Richiede che l'utente usr_tenant_{slug} esista nel DB (creato da sp_provision_tenant).
        """
        schema_name = _slug_to_schema(tenant_slug)
        result = session.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :schema"),
            {"schema": schema_name}
        ).fetchone()
        if not result:
            raise ValueError(
                f"Schema tenant '{schema_name}' non trovato. "
                f"Eseguire sp_provision_tenant prima."
            )
        user_name = _slug_to_user(tenant_slug)
        session.execute(text(f"EXECUTE AS USER = N'{user_name}'"))

    async def _set_schema_async(
        self, session: AsyncSession, tenant_slug: str
    ) -> None:
        """Versione async di _set_schema_sync."""
        schema_name = _slug_to_schema(tenant_slug)
        result = await session.execute(
            text("SELECT 1 FROM sys.schemas WHERE name = :schema"),
            {"schema": schema_name}
        )
        if not result.fetchone():
            raise ValueError(
                f"Schema tenant '{schema_name}' non trovato."
            )
        user_name = _slug_to_user(tenant_slug)
        await session.execute(text(f"EXECUTE AS USER = N'{user_name}'"))

    async def provision_tenant(
        self,
        slug: str,
        display_name: str,
        plan: str = "starter",
    ) -> None:
        """
        Chiama la stored procedure sp_provision_tenant su SQL Server.
        Crea schema + tabelle per un nuovo tenant.
        Idempotente, cioe lo puoi chiamare 1 o 100volte e non rompe nulla
        """
        async with self._async_factory() as session:
            try:
                await session.execute(  #eseguiamo la store procedure (creata in init.sql)
                    text("""
                        EXEC shared.sp_provision_tenant
                            @slug = :slug,
                            @display_name = :display_name,
                            @plan = :plan
                    """),  #🔥🔥EXECUTE stored procedure target (shared.sp_provision_tenant) con params!!
                    {"slug": slug, "display_name": display_name, "plan": plan}
                )
                await session.commit()   #async
                logger.info(
                    "Tenant provisionato",
                    slug=slug,
                    schema=_slug_to_schema(slug),
                )  #here aggiungi i metadati strutturati, sono utili e.g. a opentelemetry/ELK/ect
            except Exception as e:
                await session.rollback()   #esegui rollerback
                logger.error(f"Errore provisioning tenant {slug}: {e}")
                raise  #rilanci l'errore

    @staticmethod   #when a function logically belongs to a class but does not need access to self or cls
    async def ping() -> bool:
        """Verifica connessione SQL Server. Usato in /health"""
        try:
            engine = get_async_engine()
            async with engine.connect() as conn:  #apre connessione temp
                await conn.execute(text("SELECT 1"))  #test query
            return True
        except Exception as e:
            logger.error(f"SQL Server ping fallito: {e}")
            return False

def _slug_to_schema(slug: str) -> str:
    """
    Converte slug tenant nel nome dello schema SQL Server.
    "acme-corp" -> "tenant_acme_corp"
    """
    return "tenant_" + slug.replace("-", "_").lower()

def _slug_to_user(slug: str) -> str:
    """
    Genera il nome dell'utente SQL Server per EXECUTE AS USER.
    "acme-corp" -> "usr_tenant_acme_corp"
    Questo utente viene creato da sp_provision_tenant con DEFAULT_SCHEMA = tenant_acme_corp.
    EXECUTE AS USER è session-scoped: a differenza di ALTER USER che modifica il DB in modo
    globale e permanente, rompendo l'isolamento multi-tenant sotto concorrenza.
    """
    return "usr_" + _slug_to_schema(slug)


tenant_db = TenantDB()   #singleton globale, importato da deps.py e dai worker Celery


@lru_cache(maxsize=1)   #decoratore che trasforma la funzione in un singleton, quindi get_qdrant_client() ritorna sempre la stessa istanza di QdrantClient, evitando overhead di connessioni multiple
def get_sync_engine():
    """Engine SQLAlchemy sincrono, usato nei worker Celery."""
    from app.core.settings import get_settings
    settings = get_settings()
    engine = create_engine(    #crea connection sqlalchemy
        settings.sqlserver_url,
        pool_size=5,               #5 connessioni aperte
        max_overflow=10,           #fino a 10 connessioni extra temp
        pool_pre_ping=True,        #prima di usare una connessione esegue SELECT 1 per verificare che sia viva
        pool_recycle=3600,         #dopo 1ora fa chiudi->riapri, per evitare timeout
        echo=settings.app_debug,   #settings.app_debug è True allora vedi tutte le query sql generate da sqlalchemy nei log
    )
    logger.info("Engine SQL Server sincrono creato")
    return engine

@lru_cache(maxsize=1)
def get_async_engine():
    """
    Engine SQLAlchemy asincrono, usato nelle route FastAPI.
    Usa aioodbc come driver async per SQL Server.
    """
    from app.core.settings import get_settings
    settings = get_settings()
    #URL async: sostituisce mssql+pyodbc con mssql+aioodbc
    async_url = settings.sqlserver_url.replace(
        "mssql+pyodbc", "mssql+aioodbc"
    )  #replace mssql+pyodbc -> mssql+aioodbc, quindi utilizzi driver aioodbc CHE E' ASYNC🔥!!
    engine = create_async_engine(   #crea connection ASYNC sqlalchemy
        async_url,  
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.app_debug,
    )
    logger.info("Engine SQL Server asincrono creato")
    return engine

