
questo prj batterà app RAG internazionalmente famose come Legora/Harvey/ LexRoom (italiana)

//in futuro fovrai pensare anche al GDPR per la privacy, quindi anonimizzare i dati sensibili!
//⚠️⚠️ TODO FUTURE/ATTENTIONS!!!
-manca tabella tsql 'conversation_summaries' chiamata in conversation_repo.py & long_term.py !!
-TODO: 
--check se readbeat (x celry cosi che salva i tasks periodici in modo persistente su redis)
--agents con flow Supervisore , ... ect..
--files dentro mcp/



############################################################################

# RAG Enterprise Legal — Struttura Progetto Completa

```
rag-enterprise/
│
├── main.py                          # Entry point FastAPI — app factory, lifespan, router include
│
├── docker-compose.yml               # Stack produzione completo
├── docker-compose.override.yml      # Override sviluppo locale (hot reload, meno RAM, no password)
│
├── .env                             # Segreti reali (NON committato — nel .gitignore)
├── .env.example                     # Template variabili d'ambiente (committato)
├── .gitignore
├── .dockerignore
│
├── requirements.txt                 # Lock file generato da pip-compile (dipendenze + transitive)
├── requirements-dev.txt             # Lock file dev (test, linting)
├── pyproject.toml                   # Config Ruff, Mypy, Pytest
├── README.md                        
│
├── config/                          # Configurazione centralizzata — committata, no segreti
│   ├── config.yaml                  # ★ Parametri app: LLM, embeddings, retriever, chunking, ecc.
│   ├── prompts.yaml                 # Tutti i prompt LLM centralizzati qui
│   ├── metadata.yaml                # Mapping metadati documenti per classificazione automatica
│   └── logging.yaml                 # Configurazione Loguru
│
│
├── docker/                          # Dockerfile e script infrastruttura
│   ├── fastapi.Dockerfile           # Multi-stage build: builder + runtime leggero
│   ├── celery.Dockerfile            # Separato da FastAPI: pre-scarica modelli embedding
│   └── sqlserver/
│       ├── init.sql                 # ★ Script SQL eseguito al primo avvio del container
│       └── entrypoint.sh            # Attende SQL Server pronto poi esegue init.sql
│
│
├── app/
│   │
│   ├── core/                        # Infrastruttura condivisa — singleton, caricati una volta
│   │   ├── settings.py              # ★ Pydantic-settings: merge config.yaml + .env + OS vars
│   │   ├── observability.py         # Setup Loguru, LangSmith, OpenTelemetry
│   │   ├── security.py              # JWT encode/decode, bcrypt, API key generation
│   │   ├── llm_factory.py           # Factory LLM: ollama | openai | google da config
│   │   ├── embeddings.py            # fastembed BAAI/BGE-M3 wrapper + reranker cross-encoder
│   │   ├── vectorstore.py           # Qdrant client + gestione collection per tenant
│   │   └── redis_client.py          # TenantRedis: namespace isolation tenant:{id}:*
│   │
│   ├── api/
│   │   ├── deps.py                  # ★ Depends FastAPI: CurrentTenant, CurrentDB, CurrentRedis
│   │   │
│   │   ├── middleware/
│   │   │   ├── tenant.py            # Estrae tenant_id dal JWT → request.state
│   │   │   ├── logging.py           # Structured logging con request_id per ogni request
│   │   │   └── rate_limit.py        # Rate limiting per tenant via Redis (fail open)
│   │   │
│   │   └── routes/
│   │       ├── health.py            # GET /health (liveness) e /ready (readiness + checks)
│   │       ├── auth.py              # POST /login, /refresh, /logout · GET /me
│   │       ├── chat.py              # POST /chat/query (sync) e /chat/stream (SSE)
│   │       ├── documents.py         # POST /upload · GET /documents · DELETE /{id}
│   │       ├── collections.py       # CRUD collection (cartelle logiche documenti)
│   │       ├── jobs.py              # GET /jobs, /{id} · POST /{id}/cancel
│   │       ├── users.py             # CRUD utenti (solo admin)
│   │       └── tenants.py           # Provisioning tenant (solo superadmin)
│   │
│   ├── db/
│   │   ├── sqlserver.py             # ★ TenantDB: engine + schema switching per tenant
│   │   │
│   │   ├── models/
│   │   │   └── shared.py            # SQLAlchemy models schema shared (Tenant, AuditLog, ecc.)
│   │   │
│   │   └── repositories/            # Pattern repository: tutta la logica SQL qui
│   │       ├── base.py              # BaseRepository con execute/fetchone/fetchall/scalar
│   │       ├── document_repo.py     # DocumentRepository + IngestionJobRepository
│   │       ├── conversation_repo.py # ConversationRepository + summary long-term memory
│   │       └── user_repo.py         # UserRepository CRUD
│   │
│   ├── rag/
│   │   │
│   │   ├── ingestion/               # Pipeline: file → vettori in Qdrant
│   │   │   ├── parser.py            # docling (PDF/DOCX) → unstructured (fallback) → openpyxl
│   │   │   ├── cleaner.py           # Pulizia testo: null bytes, page numbers, header/footer
│   │   │   ├── chunker.py           # MarkdownTextSplitter / RecursiveCharacterTextSplitter
│   │   │   ├── metadata.py          # Classificazione doc type + payload Qdrant
│   │   │   └── pipeline.py          # ★ Orchestratore: parse→clean→chunk→embed→upsert
│   │   │
│   │   ├── retrieval/
│   │   │   └── retriever.py         # ★ dense + sparse → RRF fusion → MMR → cross-encoder reranker
│   │   │
│   │   ├── generation/
│   │   │   ├── prompts.py           # Carica prompt da prompts.yaml + fallback hardcodati
│   │   │   ├── chain.py             # LangChain chain: context + prompt → LLM → risposta
│   │   │   ├── citations.py         # Estrae e formatta citazioni [Fonte N: file, p.X]
│   │   │   └── hallucination.py     # LLM-as-judge: score faithfulness 0.0-1.0
│   │   │
│   │   ├── memory/
│   │   │   ├── short_term.py        # Redis: ultimi N turni con TTL (ShortTermMemory class)
│   │   │   ├── long_term.py         # SQL: summary + fact extraction stile Zep (v2, off di default)
│   │   │   └── context_builder.py   # ★ Assembla: chunks + history + facts → prompt context
│   │   │
│   │   ├── agents/
│   │   │   ├── router_agent.py      # Classifica query: rag | web | sql | general
│   │   │   ├── web_agent.py         # Ricerca web: Tavily (preferito) | DDGS + LLM
│   │   │   └── tools/               # Tool singoli per gli agent (date, calculator, ecc.)
│   │   │
│   │   └── graph/                   # LangGraph workflow
│   │       ├── state.py             # RAGState TypedDict condiviso tra tutti i nodi
│   │       ├── nodes.py             # Un nodo per step: route, retrieve, generate, ecc.
│   │       ├── edges.py             # Logica routing condizionale post-route
│   │       └── graph.py             # ★ Assembla + compila grafo (singleton @lru_cache)
│   │
│   ├── services/                    # Orchestration layer: coordina DB + RAG + Redis
│   │   ├── chat_service.py          # ★ cache → retrieval → generation → memory → DB → stats
│   │   ├── document_service.py      # 🔥🔥TODO upload → hash check → DB → dispatch Celery job
│   │   └── tenant_service.py        # provision: SQL schema + Qdrant collection + admin user
│   │
│   ├── workers/                     # Celery tasks asincroni
│   │   ├── celery_app.py            # Factory Celery: code high/default/low/shared_cleanup
│   │   ├── ingestion_tasks.py       # ★ ingest_document: pipeline + retry backoff esponenziale
│   │   ├── cleanup_tasks.py         # purge_tenant (offboarding) + expire_sessions
│   │   └── scheduled_tasks.py       # rollup_usage giornaliero (celery-beat + redbeat)
│   │
│   └── schemas/                     # Pydantic v2 request/response — separati dai modelli DB
│       ├── common.py                # PaginatedResponse, ErrorResponse, SuccessResponse
│       ├── chat.py                  # ChatRequest, ChatResponse, MessageSchema, FeedbackRequest
│       └── document.py              # DocumentSchema, UploadResponse, IngestionJobSchema
│
│
├── tests/
│   ├── conftest.py                  # Fixtures condivise: app, client, tenant_context, sample_chunks
│   ├── unit/
│   │   ├── test_chunker.py          # TestCleaner, TestChunker, TestContextBuilder
│   │   └── test_security.py         # TestPasswordHashing, TestJWT, TestAPIKey
│   └── integration/
│       └── test_health.py           # Test /health e /ready endpoint
│
│
└── scripts/                         # Utility CLI
    ├── create_tenant.py             # python scripts/create_tenant.py --slug acme --name "Acme"
    ├── seed_demo_data.py            # Inserisce documenti demo per tenant demo-corp
    └── benchmark_retrieval.py       # Misura qualità RAG: keyword score + faithfulness score
```
---

## Flusso dati — dalla query alla risposta

```
Browser / Client
      ↓ HTTPS
   nginx (rev proxy, SSL, buffering off per SSE)
      ↓ :8000
   FastAPI (main.py)
      ↓
   Middleware stack (tenant → logging → rate_limit)
      ↓
   Route /chat/stream
      ↓
   ChatService.stream_query()
      ├── Redis: check cache query
      ├── Redis: load session (short-term memory)
      ├── retriever.retrieve()
      │     ├── fastembed: embed query
      │     ├── Qdrant: dense search (semantic)
      │     ├── Qdrant: sparse search (BM25)
      │     ├── RRF fusion
      │     ├── MMR diversification
      │     └── CrossEncoder: reranker (20→5 chunk)
      ├── context_builder.build_rag_context()
      ├── chain.astream_rag_chain() → LLM tokens via SSE
      ├── SQL Server: INSERT messages
      ├── Redis: append to session
      └── Redis: set query cache
```

## Flusso dati — upload documento

```
POST /api/v1/documents/upload
      ↓
   DocumentService.upload_and_queue()
      ├── SHA-256 hash → deduplication check SQL Server
      ├── Save file to /app/uploads/{tenant}/{uuid}.pdf
      ├── INSERT documents (status=pending) → SQL Server
      ├── INSERT ingestion_jobs (status=queued) → SQL Server
      └── ingest_document.apply_async(queue="default")
                              ↓
                        Celery Worker
                              ↓
                        ingestion_tasks.ingest_document()
                              ├── UPDATE status=running → SQL Server
                              ├── parser.parse_document() → docling/unstructured
                              ├── cleaner.clean_text()
                              ├── chunker.chunk_document()
                              ├── embeddings.embed_texts() → fastembed batch
                              ├── Qdrant: upsert points (batch 100)
                              ├── UPDATE status=done + chunk_count → SQL Server
                              └── Redis: invalidate query cache tenant
```

## Multi-tenant isolation — dove avviene

```
JWT payload
  {"tenant_id": "uuid", "tenant_slug": "acme", "role": "admin"}
      ↓
TenantMiddleware → request.state.tenant_id
      ↓
get_current_tenant() → TenantContext
      ↓
  ┌── get_db() → TenantDB.aget_session("acme")
  │               └── ALTER USER SA WITH DEFAULT_SCHEMA = [tenant_acme]
  │               └── ogni query trova automaticamente le tabelle di acme
  │
  ├── get_tenant_redis() → TenantRedis(tenant_id="uuid")
  │               └── ogni chiave prefissata: tenant:uuid:*
  │
  └── retriever.retrieve() → filtro Qdrant: tenant_id = "uuid"
                  └── vettori di altri tenant non vengono mai restituiti
```

---

## Conteggio file

| Area | File Python |
|---|---|
| app/core/ | 7 |
| app/api/ | 12 |
| app/db/ | 7 |
| app/rag/ | 16 |
| app/services/ | 3 |
| app/workers/ | 4 |
| app/schemas/ | 3 |
| tests/ | 5 |
| scripts/ | 3 |
| **Totale** | **60 file Python** |

| Area | File config/infra |
|---|---|
| config/ | 4 yaml |
| docker/ | 2 Dockerfile + 2 sql/sh |
| root | docker-compose x2, .env.example, pyproject.toml, requirements x2 |
| **Totale** | **14 file config/infra** |


Come funziona il flusso SSE end-to-end usando ChainLit x il frontend
```
  Browser → WebSocket → Chainlit (8080)
                            ↓ httpx POST /api/v1/chat/stream
                        FastAPI (8000)
                            ↓ stream_query() yields tokens
                            ↓ yield "\x1e{sources, conv_id}" [sentinel]
                        event_generator() intercetta →
                            data: {"token": "..."}   ×N
                            data: {"done": true, "sources": [...], "conversation_id": "..."}
                            ↓
                        Chainlit stream_token() → msg.update()
                        → mostra fonti come cl.Text elementi espandibili
```

  docker-compose up --build
  UI disponibile su http://localhost:8080
  Login: email + password + (opzionale) email|tenant-slug

  