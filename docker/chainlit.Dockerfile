#=============================================================
# docker/chainlit.Dockerfile
# Immagine leggera per il frontend Chainlit.
# Context: root del progetto  (docker-compose build context: .)
#=============================================================

FROM python:3.11-slim

WORKDIR /app

#installa dipendenze Python
COPY chainlit_app/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt  
  #--no-cache-dir non salva cache wheel(riduce dimensione immagine)

COPY chainlit_app/app.py app.py
COPY chainlit_app/.chainlit/ .chainlit/
  #copia sorgente app e configurazione Chainlit

# Utente non privilegiato per sicurezza
RUN addgroup --system appgroup \
 && adduser --system --ingroup appgroup --no-create-home appuser \
 && chown -R appuser:appgroup /app
  #crea utente appuser, lo aggiunge al gruppo appgroup (non crea /home/appuser !), e dà a questo utente la proprietà della directory /app (dove risiede l'app) (prima era di default /app owner=root ), -R significa ricorsivo cioe , ora quando chainlit partira il processo sara = utente appuser ottimo cosi x security se qualcuno prova a hackerare visto che abbiamo cambaito root->appuser vara permessi limitati

USER appuser

EXPOSE 8080

# --headless non esiste in Chainlit; si avvia direttamente senza aprire browser
CMD ["chainlit", "run", "app.py", "--host", "0.0.0.0", "--port", "8080"]   
  #con 0.0.0.0 ascolta su tutte le interfacce di rete!, necessario per Docker. Port 8080 è quello configurato in Chainlit (puoi cambiarlo ma ricordati di aggiornare anche docker-compose.yml)

#ora se fai una build allora questo container chainlit avra all'interno
#   /app
# │
# ├── app.py
# ├── requirements.txt
# └── .chainlit/
#e all'avvio eseguira il comando  chainlit run app.py --host 0.0.0.0 --port 8080