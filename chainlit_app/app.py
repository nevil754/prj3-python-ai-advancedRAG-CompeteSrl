"""
Chainlit UI per il sistema RAG Enterprise Compet-e.
Flusso:
  1. Login → chiama POST /api/v1/auth/login su FastAPI, ottiene JWT.
  2. Ogni messaggio → chiama POST /api/v1/chat/stream via SSE server-side.
  3. I token SSE vengono streamati in tempo reale nella chat.
  4. Al termine ("done") mostra le fonti come elementi espandibili.

Il tenant_slug si configura tramite la variabile d'ambiente CHAINLIT_DEFAULT_TENANT
(default "demo-corp").  Per usare un tenant diverso il login accetta il formato:
    username:  email@example.com|mio-tenant
    password:  (normale)
"""
from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import json
import os
import httpx  #lib http async, più performante di requests, supporta SSE streaming e timeout avanzati
import chainlit as cl

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")
DEFAULT_TENANT = os.getenv("CHAINLIT_DEFAULT_TENANT", "demo-corp")

# AUTH
@cl.password_auth_callback   #decoratore chainlit, viene chiamato auto quando utente fa login
async def auth_callback(username: str, password: str) -> cl.User | None:
    """
    Autentica l'utente chiamando /api/v1/auth/login su FastAPI.
    Formato username supportati:
      - email@example.com            → usa DEFAULT_TENANT
      - email@example.com|mio-tenant → override tenant
    """
    email = username
    tenant_slug = DEFAULT_TENANT
    if "|" in username:
        email, tenant_slug = username.split("|", 1)
        email = email.strip()
        tenant_slug = tenant_slug.strip()
    try:
        async with httpx.AsyncClient( timeout=10.0 ) as client:   #apre client http async 
            resp = await client.post(
                f"{FASTAPI_URL}/api/v1/auth/login",
                json={"email": email, "password": password, "tenant_slug": tenant_slug},  #manda json con email, password e tenant_slug al backend FastAPI
            )
        if resp.status_code == 200:
            data = resp.json()
            return cl.User(  #crea utente chainlit, con email come identifier e metadata con access_token- user_role-user_id-tenant_slug
                identifier=email,
                metadata={
                    "access_token": data["access_token"],
                    "user_role": data.get("user_role", "user"),
                    "user_id": data.get("user_id", ""),
                    "tenant_slug": data.get("tenant_slug", tenant_slug),
                },
            )
    except Exception:
        pass
    return None


# INIZIO SESSIONE
@cl.on_chat_start   #chiamato auto quando si apre una nuova chat
async def on_chat_start() -> None:
    """Inizializza la sessione e mostra il messaggio di benvenuto."""
    user: cl.User = cl.user_session.get("user")   #type: ignore[assignment]. recupera utente authenticato
    tenant = user.metadata.get("tenant_slug", DEFAULT_TENANT)   
    role = user.metadata.get("user_role", "user")   
    cl.user_session.set("conversation_id", None)   #inizializza la conversazione!!
    await cl.Message(   #invia mex iniziale
        content=(
            f"Benvenuto nel sistema **RAG Enterprise Compet-e**!\n\n"
            f"Tenant: `{tenant}` | Ruolo: `{role}`\n\n"
            "Poni una domanda sui documenti caricati nel sistema. "
            "Uso retrieval semantico ibrido (dense + sparse) + reranking per trovare le risposte più precise."
        ),
    ).send()


# GESTIONE MESSAGGI — SSE STREAMING
@cl.on_message    #chiamato auto quando utente invia un messaggio
async def on_message(message: cl.Message) -> None:   #riceve il mex dell'utente
    """
    Gestisce ogni messaggio dell'utente:
      1. Chiama /api/v1/chat/stream su FastAPI via SSE (server-side).
      2. Streama i token in tempo reale nel messaggio di risposta.
      3. Al "done" aggiorna conversation_id e mostra le fonti.
    """
    user: cl.User = cl.user_session.get("user")   #type: ignore[assignment]. recupera utente authenticato
    access_token: str = user.metadata.get("access_token", "")
    conversation_id: str | None = cl.user_session.get("conversation_id")   #recupera id conversazione corrente
    answer_msg = cl.Message(content="")   #mex vuoto
    await answer_msg.send()  #invia mex vuoto
    meta: dict = {}
    try:
        timeout = httpx.Timeout(120.0, connect=10.0)  #max 10sec connessione e 120sec risposta
        async with httpx.AsyncClient(timeout=timeout) as client:    #apre client http async
            async with client.stream(  #apre connessione streaming
                "POST",
                f"{FASTAPI_URL}/api/v1/chat/stream",
                json={
                    "question": message.content,
                    "conversation_id": conversation_id,
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "text/event-stream",   #🔥🔥dice che vuole SSE streaming! 
                },
            ) as resp:
                if resp.status_code == 401:   #sessione scaduta
                    await answer_msg.update(
                        content="Sessione scaduta. Ricarica la pagina ed esegui nuovamente il login."
                    )
                    return
                if resp.status_code != 200:   #errore backend
                    await answer_msg.update(
                        content=f"Errore backend: HTTP {resp.status_code}. Riprova tra qualche istante."
                    )
                    return
                async for line in resp.aiter_lines():   #legge riga per riga
                    if not line.startswith("data: "):   #ignora tutte le altre righe che non iniziano con "data: "
                        continue
                    raw = line[6:]   #rimuove "data: "(semplicemente non catturandolo) dalla riga
                    try:
                        payload = json.loads(raw)  #converts json strutturato in corrisponding python obj
                    except json.JSONDecodeError:
                        continue
                    if "token" in payload:  #e.g. ricevi un pezzo {token:"Hello", ...}
                        await answer_msg.stream_token( payload["token"] )  #streama il token immediatamente, ora sarà renderizzato nella chat
                    elif payload.get("done"):   #se arriva (è l'ultimo pezzo) {done:true, ...}
                        meta = payload   #salva metadati finali!
                    elif "error" in payload:
                        await answer_msg.stream_token( f"\n\nErrore: {payload['error']}" )

    except httpx.ReadTimeout:
        await answer_msg.stream_token(
            "\n\nTimeout: il modello ha impiegato troppo tempo a rispondere."
        )
    except Exception as exc:
        await answer_msg.stream_token( f"\n\nErrore imprevisto: {exc}" )
    await answer_msg.update()   #🔥dice a chainlit streaming completato!
    new_conv_id = meta.get("conversation_id")
    if new_conv_id:
        cl.user_session.set("conversation_id", new_conv_id)  #aggiorna conversation_id per il prossimo turno. cosi puoi fare conversazioni multi-turn mantenendo il contesto!!
    #mostra le fonti (sources)(se presenti)
    sources: list[dict] = meta.get("sources", [])  #recupera le fonti
    if not sources:
        return
    elements: list[cl.Text] = []   #contenitori espandibili laterali
    lines: list[str] = ["**Fonti utilizzate:**"]    #testo principale che elenca le fonti con filename page_number e score
    for i, src in enumerate(sources, 1):   #1-based index
        fname = src.get("filename", "—")
        page = src.get("page_number")
        score = src.get("score", 0.0)
        snippet = src.get("snippet", "")
        label = f"[{i}] {fname}"
        if page:
            label += f" — p. {page}"
        label += f"  `score: {score:.3f}`"
        #ora il label è stato costruito
        lines.append(label)
        if snippet:
            elements.append(
                cl.Text(
                    name=f"Fonte {i} — {fname}",
                    content=snippet,
                    display="side",
                )
            )
    await cl.Message(
        content="\n".join(lines),
        elements=elements,
    ).send()


