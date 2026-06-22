# =============================================================
# RAG Enterprise Legal Compet-e Srl — Celery worker image
# Separato da FastAPI: i worker caricano modelli pesanti
# (fastembed, reranker) che non servono all'API server
#=============================================================

FROM python:3.11-slim AS builder
#crei stage chiamato 'builder', python:3.11-slim è immagine Debian minimal molto piu piccola della full
RUN apt-get update && apt-get install -y --no-install-recommends \  
    curl \
    gnupg2 \
    unixodbc-dev \
    build-essential \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
#installazione packs di sistema, --no-install-recommends installa SOLO dipendenze strettamente necessarie
#curl \     x per scaricare file da internet
#gnupg2 \   x verificare firme GPG, aggiungere chiavi repository, necessario per repository Microsoft
#unixodbc-dev \    x Headers/librerie sviluppo ODBC, necessario x compilare pyodbc aioodbc
#build-essential \   installa gcc g++ make servono per compilare pacchetti Python nativi, molti pack AI lo chiedono 
#&& curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -   scarica chiave GPG Microsoft, serve per fidarsi repository Microsoft
#&& curl https://packages.microsoft.com/config/debian/12/prod.list \
  #     > /etc/apt/sources.list.d/mssql-release.list
  #aggiunge repository Microsoft SQL Server
#&& apt-get update    ricarica repository
#&& ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18   installa driver ODBC Microsoft SQL Server, ACCEPT_EULA=Y  -> accetti licenza Microsoft automaticamente
#&& apt-get clean \ && rm -rf /var/lib/apt/lists/*    riduce dimensione immagine eliminando cache apt, MOLTO IMPORTANTE!

WORKDIR /build
#directory corrente del container, tutte le operazioni successive (COPY, RUN) useranno questa directory come base.
COPY requirements.txt .
#copia SOLO requirements.txt (file generato anche con dipendeze transitivo top), questo sfrutta la cache di Docker🔥: se requirements.txt non cambia, Docker riusa il layer precedente, velocizzando build successive
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --no-deps -r requirements.txt
#aggiorna pip, non salva cache wheel(riduce dimensione immagine), 🔥NON installare dipendenze automatiche, PERCHE IO INTANTO HO TUTTO(anche le dependencies transitive!) su requirements.txt e requirements-dev.txt FILES GENERATI

RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/BGE-M3')" \
    || echo "fastembed model preload skipped (no internet in build)"
#🔥DOWNLOAD IL MODEL LLM EMBEDDING DURANTE LA BUILD!! cosi container veloce no download runtime. se build env non ha internet, non fa fallire build.


FROM python:3.11-slim AS runtime
#crei stage chiamato 'runtime', in questa farai solo runtime non quello che hai fatto in 'builder'. python:3.11-slim è immagine Debian minimal molto piu piccola della full
RUN apt-get update && apt-get install -y --no-install-recommends \
    unixodbc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
#qui installo solo runtime ODBC

COPY --from=builder /usr/lib/x86_64-linux-gnu/libodbc* /usr/lib/x86_64-linux-gnu/
#copia librerie ODBC compilate
COPY --from=builder /opt/microsoft /opt/microsoft
#copia driver Microsoft SQL
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
#copia tutte librerie Python installate
COPY --from=builder /usr/local/bin /usr/local/bin
#copia eseguibili Python celery, uvicorn, gunicorn, ecc
COPY --from=builder /root/.cache /root/.cache
#COPIA MODELLI GIA SCARICATI, QUESTO EVITA re-download embedding model / start-up lento ect

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUNBUFFERED=1 \
    C_FORCE_ROOT=1
#ENV PYTHONDONTWRITEBYTECODE=1 \    disabilita .pyc, riduce scritture disco
#PYTHONUNBUFFERED=1 \    output log immediato, molto importante per Docker logs
#PYTHONUNBUFFERED=1 \     traceback completi anche per crash low-level, ottimo debugging
#C_FORCE_ROOT=1     permette Celery come root. ⚠️⚠️ IN PRODUZIONE NON USARE ROOT, CREA UTENTE DEDICATO E USA QUELLO!!

WORKDIR /app
#directory app
COPY app/ ./app/
COPY config/ ./config/
#copia code

#Il CMD viene sovrascritto dal docker-compose.yml per ogni worker
#(high priority vs default priority queue)
CMD ["celery", "-A", "app.workers.celery_app.celery_app", "worker", \
     "--loglevel=info", "--concurrency=2"]
#avvia worker Celery, -A specifica il modulo dell'app Celery (cioe path dove trovare istanza Celery), --loglevel=info per log informativi, --concurrency=2 limita a 2 processi worker (regolabile in base risorse)

