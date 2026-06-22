# per ogni HTTP req, si deve creare id univoco - misura tempo di risposta - salva status code - log strutturati.

from __future__ import annotations  #abilita forward references e typing moderno python, nelle new versions python non serve piu, ma io sto usando python 3.11.19, evita errori che non runni def test() -> MyClass: prima che MyClass sia definita

import time
import uuid

from loguru import logger  #plugin x logging avanzato
from starlette.middleware.base import BaseHTTPMiddleware  #fastapi usa Starlette sotto, questo è il middleware base
from starlette.requests import Request  #obj req http
from starlette.responses import Response  #obj res http

class LoggingMiddleware(BaseHTTPMiddleware):   #custom middleware 
    """
    Logga ogni request HTTP con:
    - request_id univoco (utile per correlare log di una stessa request)
    - metodo e path
    - status code risposta
    - durata in millisecondi
    - tenant_id e user_id (se autenticato)
    Il request_id viene poi anche aggiunto all'header di risposta
    X-Request-ID così il client può correlare richiesta e log.
    """

    SKIP_PATHS = {"/health", "/ready", "/metrics"}  #non loggare questi paths, 

    async def dispatch(self, request: Request, call_next) -> Response:   #called ad ogni req
        request_id = str(uuid.uuid4())[:8]  #8 char ok bastano per leggibilità
        request.state.request_id = request_id
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)  #jump to the next
        start = time.perf_counter()  #TIMER AD ALTA PRECISIONE
        with logger.contextualize(   #aggiunge contesto automatico a tutti i logs
            request_id=request_id,
            tenant_id=getattr(request.state, "tenant_id", None),
            user_id=getattr(request.state, "user_id", None),
        ):
            logger.info(
                f"→ {request.method} {request.url.path}",
                method=request.method,
                path=request.url.path,
                client=request.client.host if request.client else None,
            )
            try:
                response = await call_next(request)
            except Exception as e:
                duration_ms = round((time.perf_counter() - start) * 1000)  #time.perf_counter() is TIMER AD ALTA PRECISIONE
                logger.error(
                    f"✗ {request.method} {request.url.path} — eccezione non gestita",
                    error=str(e),
                    duration_ms=duration_ms,
                )
                raise  #🔥rilancia l'eccezione dopo aver loggato, così da non nascondere errori imprevisti
            duration_ms = round((time.perf_counter() - start) * 1000)
            level = "info" if response.status_code < 400 else "warning"
            if response.status_code >= 500:
                level = "error"
            logger.log(
                level.upper(),
                f"← {response.status_code} {request.method} {request.url.path} [{duration_ms}ms]",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        response.headers["X-Request-ID"] = request_id  #aggiungi request_id all'header della response
        return response


