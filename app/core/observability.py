# app/core/observability.py
# Configura tutto il sistema di logging e tracing.
# Chiamato UNA VOLTA all'avvio in main.py lifespan.
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import sys
import os
from typing import TYPE_CHECKING 
from loguru import logger   #plugin x logging avanzato

if TYPE_CHECKING:
    from app.core.settings import AppSettings   #questo import avviene solo a livello di type checking, non a runtime, così eviti problemi di import circolari quando settings importa questa funzione e questa funzione importa settings per leggere i valori di configurazione. In questo modo puoi usare "AppSettings" come tipo senza che venga importato realmente a runtime, evitando errori di importazione circolare.

def setup_all(settings: "AppSettings") -> None:
    """
    Entry point unico, chiamato da main.py lifespan.
    Configura logging, LangSmith e OpenTelemetry in sequenza!
    """
    setup_logging(settings)
    setup_langsmith(settings)
    setup_opentelemetry(settings)

def setup_logging(settings: "AppSettings") -> None:
    """
    Configura Loguru come sistema di logging globale.
    Rimuove il handler di default e ne aggiunge uno configurato.
    """
    logger.remove()    #loguru ha gia un handler di default, here lo elimino
    level = settings.log_level.upper()
    if settings.log_json_output:  #ricorda che il '_' è per indicare un annidamento
        # Formato JSON per produzione — parsabile da Loki/Datadog/Elastic
        logger.add(  #aggiunge nuovo output handler
            sys.stdout,
            level=level,   #minimo level log e.g. "INFO"
            format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} {level} {name}:{line} {message} {extra}",
            serialize=True,    #🔥🔥CONVERTS LOGS -> JSON
            backtrace=False,   #non show stack trace avanzati
            diagnose=False,    #⚠️evita dump env local nei traceback, FONDAMENTALE IN PRODUCTION!!
        )
    else:
        fmt = (  #formato human-redable per development
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )
        if settings.log_colored:
            logger.add(sys.stdout, level=level, format=fmt, colorize=True)
        else:
            logger.add(sys.stdout, level=level, format=fmt, colorize=False)

    #intercetta i log stdlib (uvicorn, sqlalchemy, ecc.) e li passa a Loguru
    _intercept_stdlib_logging()
    logger.info(
        "Logging configurato",
        level=level,
        json=settings.log_json_output,
        env=settings.app_environment,
    )

def setup_langsmith(settings: "AppSettings") -> None:
    """
    Abilita il tracing LangSmith per debug pipeline LLM.
    Imposta le variabili d'ambiente che LangChain legge automaticamente.
    """
    if not settings.langsmith_enabled:
        logger.debug("LangSmith disabilitato")
        return
    if not settings.langsmith_api_key:
        logger.warning("LangSmith abilitato ma LANGSMITH_API_KEY mancante — skip")
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key  #set new value di settings["LANGCHAIN_API_KEY"]
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
    logger.info(
        "LangSmith tracing attivato",
        project=settings.langsmith_project,
        endpoint=settings.langsmith_endpoint,
    )

def setup_opentelemetry(settings: "AppSettings") -> None:
    """
    Configura OpenTelemetry per tracing distribuito.
    Attivo solo se opentelemetry_enabled=true in config
    """
    if not settings.opentelemetry_enabled:
        logger.debug("OpenTelemetry disabilitato")
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider   #core tracing engine
        from opentelemetry.sdk.trace.export import BatchSpanProcessor   #gestisce esportazione trace
        from opentelemetry.sdk.resources import Resource   
        resource = Resource.create({    #metadata del servizio
            "service.name": settings.app_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.app_environment,
        })
        provider = TracerProvider(resource=resource)  #crea tracer principale
        trace.set_tracer_provider(provider)   #registra tracer globale
        logger.info("OpenTelemetry configurato", service=settings.app_name)
    except ImportError:
        logger.warning("opentelemetry-sdk non installato — skip")

def _intercept_stdlib_logging() -> None:
    """
    Fa sì che i log di librerie stdlib (uvicorn, sqlalchemy, httpx)
    vengano gestiti da Loguru invece che dal logger stdlib.
    """
    import logging  #stdlib logging Python
    class InterceptHandler(logging.Handler):   #handler custom che intercetta i log stdlib e li passa a Loguru
        def emit(self, record: logging.LogRecord) -> None:    #riceve log stdlib
            try:
                level = logger.level(record.levelname).name   #converte logging.INFO -> Loguru INFO
            except ValueError:
                level = record.levelno     #type: ignore
            frame, depth = sys._getframe(6), 6   #serve a trovare il vero caller del log, è molto avanzato.
            while frame and frame.f_code.co_filename == logging.__file__:   #salta frame interni di logging fino a trovare il vero caller
                frame = frame.f_back     #type: ignore
                depth += 1
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )  #re-invia log a loguru con livello corretto e info eccezione

    #intercetta root logger e logger specifici
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi",
                 "sqlalchemy.engine", "celery", "httpx"):   #tutti i logs che vuoi intercettare
        logging.getLogger(name).handlers = [InterceptHandler()]   #sostituisce handler originali
        logging.getLogger(name).propagate = False   #evita che i log vengano propagati al root logger dopo essere stati intercettati



