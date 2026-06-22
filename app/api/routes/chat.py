# =============================================================
# app/api/routes/chat.py
# Route per la chat RAG: query sincrona e streaming SSE.
# =============================================================

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita
import json  #serve x i mexs SSE
from typing import Annotated  #per type hint migliori
from fastapi import APIRouter, Depends, HTTPException   #apirouter x le routes, depends x DI(dependency injection) di fastapi, HTTPException x error handling
from fastapi.responses import StreamingResponse  #🔥x streaming response, fastapi apre connessione http lunga 
from loguru import logger   #x log strutturato
from sqlalchemy.ext.asyncio import AsyncSession   
from app.api.deps import CurrentDB, CurrentRedis, CurrentTenant   #ur custom
from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest   #ur custom
from app.services.chat_service import ChatService   #ur custom

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/query", response_model=ChatResponse)
async def chat_query(
    request: ChatRequest,
    tenant: CurrentTenant,  #fastapi esegue get_current_tenant() prima di eseguire questa route!
    db: CurrentDB,   #session sqlalchemy
    redis: CurrentRedis,  # è il get_tenant_redis() di file deps.py
) -> ChatResponse:
    """
    Query RAG completa, risposta no streaming!
    Utile per integrazioni API che non supportano SSE.
    """
    service = ChatService(
        db=db,
        redis=redis,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
        user_id=tenant.user_id,
    )
    result = await service.query(   #qua parte tutto
        question=request.question,
        conversation_id=request.conversation_id,
        collection_id=request.collection_id,
    )
    return ChatResponse(**result)  #Trasforma il dict in ur schema Pydantic!


@router.post("/stream")
async def chat_stream(  
    request: ChatRequest,
    tenant: CurrentTenant,
    db: CurrentDB,
    redis: CurrentRedis,
) -> StreamingResponse:
    """
    Query RAG con streaming SSE quindi token per token!
    Il frontend riceve i token man mano che vengono generati.
    Formato SSE:
        data: {"token": "ciao"}
        data: {"token": " come"}
        data: {"done": true, "conversation_id": "uuid", "sources": [...]}
    """
    service = ChatService(
        db=db,
        redis=redis,
        tenant_id=tenant.tenant_id,
        tenant_slug=tenant.tenant_slug,
        user_id=tenant.user_id,
    )
    async def event_generator():
        try:
            meta: dict = {}
            async for token in service.stream_query(
                question=request.question,
                conversation_id=request.conversation_id,
                collection_id=request.collection_id,
            ):
                if token.startswith("\x1e"):
                    # Sentinel dal service: contiene sources + conversation_id + latency_ms.
                    # Non viene inviato raw: diventa il payload dell'evento "done".
                    meta = json.loads(token[1:])
                else:
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, **meta})}\n\n"
        except Exception as e:
            logger.error(f"Errore streaming: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    return StreamingResponse(  #FASTAPI APRE CONNESSIONE HTTP LUNGA
        event_generator(),  #ogni yield viene inviato immediatamente 
        media_type="text/event-stream",  #🔥 fondamentale il browser DEVE sapere che questo è SSE
        headers={
            "Cache-Control": "no-cache",   #no cache
            "X-Accel-Buffering": "no",    #🔥disabilita buffering nginx, altrimenti nginx potrebbe accumulare tutto e restituire tutto solo alla fine!!
        },
    )


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    tenant: CurrentTenant,
    db: CurrentDB,
) -> dict:
    """Salva feedback thumbs up/down su un messaggio."""
    from sqlalchemy import text
    await db.execute(   #inserimento feedback nel db con raw sql, non uso orm x semplicità
        text("""
            INSERT INTO message_feedback (message_id, user_id, rating, comment)
            VALUES (:msg_id, :user_id, :rating, :comment)
        """),
        {
            "msg_id": request.message_id,
            "user_id": tenant.user_id,
            "rating": request.rating,
            "comment": request.comment,
        }
    )
    return {"message": "Feedback salvato"}

