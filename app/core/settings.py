# UNICA fonte di verità per tutta la CONFIGURAZIONE (mischi insieme vars di config.yaml + .env ) 🔥
# ˅  config.yaml 
# ˅  .env    sovrascrivono config.yaml se trova match
# ˅  env vars OS   sovrascrivono il result finora, sempre se trovano match
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import os  #x variabili d'ambiente
from functools import lru_cache   #@lru_cache(maxsize=1), serve per cache automatica python, quando questa funzione viene chiamata, la esegue UNA SOLA VOLTA e poi ricorda il risultato
from pathlib import Path  #molto meglio di os.path, supporta operazioni più complesse sui path in modo più intuitivo
from typing import Literal  #x typing python, serve per dire che una var puo essere solo di valori specificati e.g.Literal["development", "staging", "production"] = "development"
import yaml   #x leggere file config.yaml
from pydantic import Field, field_validator   #x validazione campi
from pydantic_settings import BaseSettings, SettingsConfigDict   #x settings avanzati, BaseSettings legge auto .env file

BASE_DIR = Path(__file__).resolve().parent.parent.parent  #__file__ è il path di this file, resolve() lo risolve in un path assoluto, parent.parent.parent sale di 3 livelli fino alla root del progetto, ok. Quindi BASE_DIR è la root del progetto, da cui poi costruisci il path per config.yaml e .env, ok.
CONFIG_FILE = BASE_DIR / "config" / "config.yaml"  #str '/project/config/config.yaml'

def _load_yaml() -> dict:
    """Carica config.yaml come dizionario piatto per i default."""
    if not CONFIG_FILE.exists():
        return {}    #se file non esiste return {}
    with open( CONFIG_FILE, encoding="utf-8" ) as f:
        return yaml.safe_load(f) or {}   #safe_load evita esecuzione codice malevolo YAML.
    #trasforma file config.yaml -> dict python, altrimenti {} se il file è vuoto

#classes x the yaml sections del tuo file originale config.yaml

class LLMSettings:
    pass  #valori letti direttamente in Settings

class AppSettings(BaseSettings):
    """
    Ogni campo può essere sovrascritto uso case-insensitive
    """
    model_config = SettingsConfigDict(   #config pydantic settings
        env_file= str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",  #encoding file
        case_sensitive=False,
        extra="ignore",          #🔥🔥ignora variabili env sconosciute, ALTRIMENTI CRASHA!!
        populate_by_name=True,   #permette di popolare i campi anche usando il nome del campo invece del nome della variabile d'ambiente e.g. llm_provider invece di LLM_PROVIDER, utile se vuoi usare nomi più leggibili nel codice (non vuoi che siano tutti sempre in maiuscolo)
    )

    app_name: str = "RAG Enterprise Compet-e Legal"  #here il value è quello di default, se in .env esiste allora vince quello di .env !!
    app_version: str = "0.1.0"
    app_debug: bool = False
    app_environment: Literal["development", "staging", "production"] = "development"

    llm_provider: str = "ollama"     #ollama | openai | google
    llm_model: str = "llama3.1"
    llm_base_url: str = "http://ollama:11434"
    llm_api_key: str = ""
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2048
    llm_timeout: int = 120
    llm_streaming: bool = True
    llm_num_ctx: int = 2048    #finestra contesto massima, piu è alto più memoria conversazionale ma piu ram

    embeddings_provider: str = "fastembed"
    embeddings_model: str = "BAAI/BGE-M3"
    embeddings_base_url: str = ""
    embeddings_batch_size: int = 64
    embeddings_cache_dir: str = "/app/.cache/embeddings"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "collection-rag-v2"
    qdrant_use_sparse: bool = True
    qdrant_force_recreate: bool = False
    qdrant_distance: str = "Cosine"
    qdrant_on_disk_payload: bool = True

    sqlserver_host: str = "sqlserver"
    sqlserver_port: int = 1433
    sqlserver_db: str = "RAGChat"
    sqlserver_password: str = ""
    sqlserver_driver: str = "ODBC Driver 18 for SQL Server"

    @property   #trasforma function -> proprieta leggibile COME ATTRIBUTO (quindi ora fai settings.sqlserver_url come se fosse una var normale)
    def sqlserver_url(self) -> str:
        """connection string che verra usata da SQLAlchemy per SQL Server via pyodbc"""
        return (  #costruzione della stringa finale
            f"mssql+pyodbc://SA:{self.sqlserver_password}@"  #psw SA(System Admin)
            f"{self.sqlserver_host}:{self.sqlserver_port}/"  #host e port
            f"{self.sqlserver_db}"
            f"?driver={self.sqlserver_driver.replace(' ', '+')}"   #sostituisce spazi con +, necessario per pyodbc
            f"&TrustServerCertificate=yes"
            f"&Encrypt=yes"
        )   #crea e.g. "mssql+pyodbc://SA:password@sqlserver:1433/RAGChat?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=yes"

    redis_url: str = "redis://redis:6379/0"         #db 0, x broker celery + sessioni + rate limit
    redis_cache_url: str = "redis://redis:6379/1"   #db 1, x cache RAG separata
    redis_password: str = ""

    retriever_search_type: str = "hybrid"
    retriever_strategy: str = "mmr"
    retriever_top_k: int = 20
    retriever_mmr_lambda: float = 0.5
    retriever_auto_filter: bool = False

    reranker_enabled: bool = True
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_top_k: int = 5
    reranker_initial_k: int = 20

    ingestion_prefer_docling: bool = True
    ingestion_extract_tables: bool = True
    ingestion_chunk_size: int = 1000
    ingestion_chunk_overlap: int = 200
    ingestion_chunk_strategy: str = "markdown"
    ingestion_max_file_mb: int = 100

    memory_short_term_turns: int = 10
    memory_long_term_enabled: bool = False
    memory_session_ttl_hours: int = 24

    cache_query_ttl_seconds: int = 3600
    cache_session_ttl_seconds: int = 86400

    jwt_secret_key: str = Field(default="change-me-in-production-min-32-chars")   #chiave fake x development
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    api_key_length: int = 32
    password_min_length: int = 12

    rate_limit_requests_per_minute: int = 60
    rate_limit_tokens_per_day: int = 100_000

    langsmith_enabled: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "rag-enterprise-legal"
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"
    langchain_tracing_v2: bool = True
    opentelemetry_enabled: bool = False

    log_level: str = "INFO"
    log_console_output: bool = True
    log_colored: bool = True
    log_json_output: bool = False

    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    tavily_api_key: str = ""

    celery_broker_url: str = "redis://redis:6379/0"   #uso database logico 0 (sempre all'interno sempre della stessa istanza Redis)
    celery_result_backend: str = "redis://redis:6379/0"  #uso database logico 0 (sempre all'interno sempre della stessa istanza Redis)

    openai_api_key: str = ""
    google_api_key: str = ""
    ollama_api_key: str = ""

    #quando fai settings = AppSettings(), 🔥pydantic fa legge .env -> legge env var -> crea obj settings -> valida tutti i campi -> ESEGUE I VALIDATORS -> solo ora run the app
    @field_validator("jwt_secret_key")   #custom validator, check il field jwt_secret_key
    @classmethod  #dice a python che questa funzione appartiene alla classe e NON all'istanza. per validator pydantic è lo standart
    def validate_jwt_secret(cls, v: str) -> str:   #cls è la classe corrente, v è il valore del campo jwt_secret_key
        if v == "change-me-in-production-min-32-chars":   #chiave fake di development 
            return v  #ok in dev
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY deve essere almeno 32 caratteri")
        return v

    @field_validator("log_level")   #custom validator, check il filed log_level
    @classmethod
    def validate_log_level(cls, v: str) -> str:   #cls è la classe corrente, v è il valore del campo log_level
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in allowed:
            raise ValueError(f"log_level deve essere uno di {allowed}")
        return v

def _apply_yaml_overrides() -> None:
    cfg = _load_yaml()   #legge file config.yaml 
    if not cfg:
        return
    mappings: list[tuple[str, str]] = [    #crea lista di coppie(cioe tuple)
        #mapping file config.yaml path -> nome env var (create here qua sopra)
        #ricordati che il '.' indica nested
        ("llm.provider",            "LLM_PROVIDER"),
        ("llm.model",               "LLM_MODEL"),
        ("llm.base_url",            "LLM_BASE_URL"),
        ("llm.temperature",         "LLM_TEMPERATURE"),
        ("llm.max_tokens",          "LLM_MAX_TOKENS"),
        ("llm.timeout",             "LLM_TIMEOUT"),
        ("llm.num_ctx",             "LLM_NUM_CTX"),
        ("embeddings.provider",     "EMBEDDINGS_PROVIDER"),
        ("embeddings.model",        "EMBEDDINGS_MODEL"),
        ("embeddings.batch_size",   "EMBEDDINGS_BATCH_SIZE"),
        ("embeddings.cache_dir",    "EMBEDDINGS_CACHE_DIR"),
        ("vectorstore.url",         "QDRANT_URL"),    #🔥🔥ora QDRANT_URL è la variabile d'ambiente che userai nel codice per connetterti a Qdrant, 
        #⚠️ QUINDI SE CAMBI IL NOMES NEL FILE CONFIG.YAML, RICORDATI DI CAMBIARLO ANCHE QUI!! ALTRIMENTI non link nell'app!! 
        #"QDRANT_URL" è il tuo "qdrant_url" here qua sopra in AppSettings, mentre "vectorstore.url" è il path in config.yaml
        ("vectorstore.collection_name", "QDRANT_COLLECTION_NAME"),
        ("vectorstore.use_sparse",  "QDRANT_USE_SPARSE"),
        ("retriever.top_k",         "RETRIEVER_TOP_K"),
        ("retriever.search_type",   "RETRIEVER_SEARCH_TYPE"),
        ("reranker.enabled",        "RERANKER_ENABLED"),
        ("reranker.top_k",          "RERANKER_TOP_K"),
        ("logging.level",           "LOG_LEVEL"),
        ("logging.json_output",     "LOG_JSON_OUTPUT"),
        ("observability.langsmith_enabled", "LANGSMITH_ENABLED"),
        ("memory.short_term_turns", "MEMORY_SHORT_TERM_TURNS"),
        ("memory.long_term_enabled","MEMORY_LONG_TERM_ENABLED"),
        ("cache.query_ttl_seconds", "CACHE_QUERY_TTL_SECONDS"),
    ]

    def _get_nested(d: dict, path: str):  #path -> una stringa con i livelli separati da .
        keys = path.split(".")
        for k in keys:
            if not isinstance(d, dict) or k not in d:   #check se non è un dict, e che k non è in d(il dict)
                return None
            d = d[k]
        return d

    for yaml_path, env_key in mappings:       #🔥da priorita alle var in .env se trova trova match
        if os.environ.get(env_key) is None:   #non sovrascrive se gia impostato come variabile d'ambiente
            value = _get_nested(cfg, yaml_path)
            if value is not None:
                os.environ[env_key] = str(value)

@lru_cache(maxsize=1)  #garantisce che venga creata 1 SOLA VOLTA (singleton), e.g. la prima volta settings = get_settings() viene eseguito completamente, mentre la seconda volte che viene chiamato settings = get_settings() allora sfrutta la cache e return l'obj gia esistente
def get_settings() -> AppSettings:    #return type of AppSettings!
    """
    🔥Usare sempre questa funzione, MAI AppSettings() direttamente!
    e.g. uso:
        from app.core.settings import get_settings
        settings = get_settings()
        print(settings.llm_model)
    """
    _apply_yaml_overrides()
    return AppSettings()

settings = get_settings()   #istanza globale, importa questa nei modules che lo vogliono!

