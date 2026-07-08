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

_TRUTHY = {"1", "true", "yes", "on"}


def _api_key_id(request: Request) -> str:
    u = getattr(request.state, "authed_user", None)
    if u is not None:
        return f"key:{u.api_key_id}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def _resolve_storage_uri() -> str:
    """Resolve the slowapi storage backend, failing loud in production (F-ARCH-3).

    In-memory storage is per-process and NOT shared across workers, so it is not
    a real rate limit under horizontal scaling. Silently falling back to it in
    production is a lie. When RELEASE is set (production) we require a real
    REDIS_URL; the documented off-switch RATE_LIMIT_ALLOW_MEMORY=1 lets an
    operator explicitly opt into in-memory limiting. Dev/test (no RELEASE) keep
    the memory:// convenience default.
    """
    redis_url = os.getenv("REDIS_URL")
    if redis_url and redis_url != "memory://":
        return redis_url

    release = os.getenv("RELEASE")
    allow_memory = os.getenv("RATE_LIMIT_ALLOW_MEMORY", "0").strip().lower() in _TRUTHY
    if release and not allow_memory:
        raise RuntimeError(
            "RELEASE is set (production) but REDIS_URL is missing or 'memory://'. "
            "Rate limiting would silently fall back to per-process in-memory "
            "storage, which is not shared across workers and is not a real rate "
            "limit. Set REDIS_URL to a real Redis, or set RATE_LIMIT_ALLOW_MEMORY=1 "
            "to explicitly opt into in-memory rate limiting."
        )
    return "memory://"


limiter = Limiter(
    key_func=_api_key_id,
    storage_uri=_resolve_storage_uri(),
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
