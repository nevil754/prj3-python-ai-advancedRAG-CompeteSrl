# app/workers/celery_app.py
# Celery factory: definisce l'app, le code e il routing dei task.
# Importato da tutti i worker e da chi fa il dispatch dei task.

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
from celery import Celery  #x celery
from kombu import Queue  #kombu è la lib AMQP(Advanced Message Queuing Protocol) usata internamente da celery per gestire code, mexs, routing, ecc
from app.core.settings import get_settings

settings = get_settings()

def create_celery_app() -> Celery:  #this is a factory function, non è singleton
    """
    Crea e configura l'istanza Celery.
    Code:
        high    — task urgenti: chat realtime, retrieval
        default — task normali: ingestion singola
        low     — task bulk: ingestion massiva, cleanup
        shared_cleanup — manutenzione piattaforma (non tenant-specific)
    """
    app = Celery(
        "rag_worker",                #nome app
        broker=settings.redis_url,   #il broker, ora celery inserisce i tasks nelle liste redis 
        backend=settings.redis_url,  #dove vengono salvati SUCCESS|FAILURE|PENDING e i risultati delle tasks
    )

    app.conf.update(   #aggiorna la configurazione di Celery con questi params
        #x Serializzazione
        task_serializer="json",  #quando mandi e.g. task.delay(user_id=10) celery converte tutto in json
        result_serializer="json",  #anche il result viene convertito in json prima di essere salvato nel backend
        accept_content=["json"],  #accetta solo mexs in formato json, anche x security
        #x Risultati
        result_expires=86400,          #i results scadono dopo 24h in Redis
        task_track_started=True,       #traccia anche quando il task inizia (cioe STARTED) aggiunto ai 3 di default SUCCESS|FAILURE|PENDING)
        #x Affidabilità — CRITICI
        task_acks_late=True,           #ACK di conferma di task completata
        worker_prefetch_multiplier=1,  #OGNI WORKER PRENDE 1 SOLO TASK ALLA VOLTA, di default un worker prende 4 task alla volta
        task_reject_on_worker_lost=True,    #se worker crasha, task torna in coda
        #x Code
        task_queues=[  #🔥definisce le QUEUES, e.g.per un upload bulk di many docs allora il task è consigliato utilizzare il 'low'
            Queue("high",           routing_key="high"),
            Queue("default",        routing_key="default"),
            Queue("low",            routing_key="low"),
            Queue("shared_cleanup", routing_key="shared_cleanup"),
        ],
        task_default_queue="default",  #default queue, se e.g. dimentichi il routering di una task
        task_routes={   #instradamento automatico dei task nelle queues, in base al nome del task!!
            "app.workers.ingestion_tasks.ingest_document":   {"queue": "default"},
            "app.workers.ingestion_tasks.reprocess_document":{"queue": "low"},
            "app.workers.cleanup_tasks.purge_tenant":        {"queue": "shared_cleanup"},
            "app.workers.cleanup_tasks.expire_sessions":     {"queue": "shared_cleanup"},
            "app.workers.scheduled_tasks.rollup_usage":      {"queue": "shared_cleanup"},
        },
        task_max_retries=3,            #massimo 3 tentativi per task prima di failure
        task_default_retry_delay=60,   #60s prima di riprovare
        timezone="UTC",
        enable_utc=True,  #🔥 forza utc ovunque, evita problemi italia england ect
        #🔥⚡️Redbeat scheduler (task periodici persistiti su Redis), see more in notesGo.txt !
        redbeat_redis_url=settings.redis_url,  #redbeat, see more in notesGo.txt
        redbeat_key_prefix="redbeat:",   #le keys di redis diventano e.g. "redbeat:app.workers.scheduled_tasks.rollup_usage"
    )
    return app

celery_app = create_celery_app()    #istanza globale, importata dai moduli worker


