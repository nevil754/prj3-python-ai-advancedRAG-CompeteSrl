# Middleware che estrae tenant_id dal JWT ad ogni request
# e lo inietta in request.state per accesso rapido.
from __future__ import annotations
from starlette.middleware.base import BaseHTTPMiddleware  #starlette è cioe che c'è sotto il cofano di fastapi
from starlette.requests import Request
from starlette.responses import Response
from app.core.security import decode_access_token, extract_bearer_token  #ur custom

class TenantMiddleware(BaseHTTPMiddleware):
    """
    Estrae tenant_id e user_id dal JWT ad ogni request.
    Non blocca le request senza token, quelle vengono gestite da get_current_tenant.
    Questo middleware arricchisce solo il request.state per uso nei log e nel rate limiter.
    Iniettato in main.py con:
        app.add_middleware(TenantMiddleware)
    """

    PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}  #questi path non richiedono auth

    async def dispatch(self, request: Request, call_next) -> Response:  #request è la richiesta corrente, call_next è la funzione che chiama il prossimo middleware o route handler
        #🔥🔥la requesta quando arriva gia contiene headers,body,query params,cookie. HERE UTILIZZO request.state (che è uno spazio vuoto) per salvare dati custom!!
        #🔥inizializzo i fields che voglio in request.state!!
        request.state.tenant_id = None
        request.state.tenant_slug = None
        request.state.user_id = None
        request.state.user_role = None
        if request.url.path in self.PUBLIC_PATHS:  #skip x routes pubbliche
            return await call_next(request)
        #estrai token dall'header Authorization
        auth_header = request.headers.get("Authorization")  #estrai auth da header 
        token = extract_bearer_token(auth_header)  #estrai token (toglie il 'Bearer')
        if token:
            payload = decode_access_token(token)
            if payload:
                #ora fai l'update dello state
                request.state.tenant_id = payload.get("tenant_id")
                request.state.tenant_slug = payload.get("tenant_slug")
                request.state.user_id = payload.get("sub")
                request.state.user_role = payload.get("role")
        return await call_next(request)  #continua la pipeline


