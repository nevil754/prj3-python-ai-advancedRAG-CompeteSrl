# RAG Enterprise Legal Compet-e Srl — FastAPI image
# Multi-stage build: 
# builder installa dipendenze,
# runtime è l'immagine finale leggera

FROM python:3.11-slim AS builder

# Installa driver ODBC per SQL Server (Microsoft)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    unixodbc-dev \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list \
       > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --no-deps -r requirements.txt



FROM python:3.11-slim AS runtime
#crei stage chiamato 'runtime', in questa farai solo runtime non quello che hai fatto in 'builder'. python:3.11-slim è immagine Debian minimal molto piu piccola della full
RUN apt-get update && apt-get install -y --no-install-recommends \
    unixodbc \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/lib/x86_64-linux-gnu/libodbc* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /opt/microsoft /opt/microsoft
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1   
      #PIP_NO_CACHE_DIR=1 disabilita cache pip, riduce dimensione immagine

WORKDIR /app

#copia codice applicazione
COPY config/ ./config/
COPY main.py .
COPY app/ ./app/
  #🔥 QUESTO ORDINE è TOP! se editi un file in app/ solo l'ultimo COPY viene rieseguito - i 3 layer precedenti (incluso il pesantissimo pip install) vengono presi dalla cache (non lo riesegui!).
  #copia anche code main.py, entry point FastAPI, questo è importante per uvicorn main:app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
#crea user Linux non privilegiato!
USER appuser
#da qui in poi processo gira come utente non privilegiato, ottima pratica x production!

RUN mkdir -p /app/.cache/embeddings
#🔥directory cache per modelli embedding, fastembed scarica i modelli qui

EXPOSE 8000
#porta usata dal container

# --workers 1 in dev — in prod usa gunicorn o aumenta i worker
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--loop", "uvloop", "--http", "httptools"]
#avvia FastAPI, --host 0.0.0.0 espone server all'esterno container, --port 8000 è porta standard FastAPI, --workers 1 per sviluppo (⚠️in prod aumentare o usare gunicorn), --loop uvloop e --http httptools migliorano performance FastAPI, ottimo per produzione!!

