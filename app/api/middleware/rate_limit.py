# =============================================================
# app/api/middleware/rate_limit.py
# Rate limiting per tenant via Redis.
# Blocca richieste eccessive prima che raggiungano le route.
# =============================================================

from __future__ import annotations    #x python legacy in prj big soprattutto, trasforma 'def get_user()->User:' in 'def get_user() -> "User":' quindi tutte le annotazioni vengono conservate come str
from starlette.middleware.base import BaseHTTPMiddleware    #fastapi usa Starlette sotto, questo è il middleware base
from starlette.requests import Request     #obj req http
from starlette.responses import Response, JSONResponse   #obj res http
from app.core.settings import get_settings


settings = get_settings()

# Route escluse dal rate limiting
EXCLUDED_PATHS = { "/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json" }

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting per tenant basato su Redis sliding window.
    Limite: requests_per_minute da config.yaml.
    Ritorna 429 Too Many Requests se superato.
    """
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)   #salta il rate limit per queste rotte (health check, docs, ecc)
        tenant_id = getattr(request.state, "tenant_id", None)  #from request.state, get "tanant_id" (None is fallback)
        user_id = getattr(request.state, "user_id", None)
        if not tenant_id or not user_id:
            return await call_next(request)  #request non autenticata — lascia passare, gestita dall'auth
        try:
            from app.core.redis_client import TenantRedis
            redis = TenantRedis(tenant_id=tenant_id)
            allowed, count = await redis.check_rate_limit(
                user_id=user_id,
                limit=settings.rate_limit_requests_per_minute,
            )   #esegue il controllo del rate limit, ritorna (allowed: bool, count: int)
            if not allowed:
                return JSONResponse(
                    status_code=429,   #HTTP 429 Too Many Requests
                    content={
                        "error": "Rate limit superato",
                        "detail": f"Max {settings.rate_limit_requests_per_minute} richieste/minuto",
                        "retry_after": 60,
                    },
                    headers={"Retry-After": "60"},
                )
        except Exception:
            #se Redis non risponde, lascia passare (fail open)
            pass
        return await call_next(request)


