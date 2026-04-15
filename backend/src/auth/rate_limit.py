"""slowapi limiter keyed by api_key_id, with GitHub-style 429 response.

Keyed on request.state.authed_user.api_key_id (set by require_api_key).
Falls back to client IP when no authed user is present (public routes).

Storage: Redis when REDIS_URL is set, else in-memory. With
in_memory_fallback_enabled=True, if Redis becomes unreachable slowapi
drops to local memory automatically (documented in 02-RESEARCH §13).
"""
from __future__ import annotations

import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


def _api_key_id(request: Request) -> str:
    u = getattr(request.state, "authed_user", None)
    if u is not None:
        return f"key:{u.api_key_id}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


limiter = Limiter(
    key_func=_api_key_id,
    storage_uri=os.getenv("REDIS_URL", "memory://"),
    strategy="fixed-window",
    headers_enabled=True,
    in_memory_fallback_enabled=True,
)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    retry_after = getattr(exc, "retry_after", None) or 3600
    reset = int(time.time()) + int(retry_after)
    limit_str = "60"
    try:
        limit_str = str(exc.limit.limit.amount)
    except Exception:
        pass
    return JSONResponse(
        status_code=429,
        headers={
            "Retry-After": str(int(retry_after)),
            "X-RateLimit-Limit": limit_str,
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset),
        },
        content={
            "code": "rate_limited",
            "message": "Rate limit exceeded. Retry after X-RateLimit-Reset.",
            "doc_url": "https://docs.cadverify.com/errors#rate_limited",
        },
    )
