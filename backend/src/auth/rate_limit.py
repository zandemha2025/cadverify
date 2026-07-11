"""slowapi limiter keyed by caller identity, with GitHub-style 429 response.

API keys are bucketed by request.state.authed_user.api_key_id (set by
require_api_key). Dashboard-session users have api_key_id=0, so they are
bucketed by user_id instead of all sharing one "key:0" quota. Public routes
fall back to client IP.

Storage: Redis when REDIS_URL is set, else in-memory for local/test builds.
Released processes disable slowapi's per-process fallback because it is not a
distributed limit; Redis failure is handled as a failed dependency instead of
silently weakening abuse controls.
"""
from __future__ import annotations

import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from src.auth.client_ip import client_ip

_TRUTHY = {"1", "true", "yes", "on"}
_DEV_RELEASES = {"", "dev", "development", "local", "test", "ci"}


def _released() -> bool:
    return os.getenv("RELEASE", "dev").strip().lower() not in _DEV_RELEASES


def _api_key_id(request: Request) -> str:
    u = getattr(request.state, "authed_user", None)
    if u is not None:
        api_key_id = int(getattr(u, "api_key_id", 0) or 0)
        if api_key_id > 0:
            return f"key:{api_key_id}"
        return f"user:{u.user_id}"
    return f"ip:{client_ip(request)}"


def _resolve_storage_uri() -> str:
    """Resolve the slowapi storage backend, failing loud in production (F-ARCH-3).

    In-memory storage is per-process and NOT shared across workers, so it is not
    a real rate limit under horizontal scaling. Silently falling back to it in
    production is a lie. When RELEASE is set (production) we require a real
    REDIS_URL. ``RATE_LIMIT_ALLOW_MEMORY=1`` remains a local compatibility
    escape hatch, but the shared production startup validator rejects it in any
    released process. Dev/test keep the memory:// convenience default.
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


def _limiter_enabled() -> bool:
    """Allow deterministic test/E2E harnesses to disable route throttles.

    Production ignores this switch: rate limiting remains enabled whenever
    RELEASE is set.
    """
    disabled = os.getenv("RATE_LIMIT_DISABLED", "0").strip().lower() in _TRUTHY
    return not (disabled and not os.getenv("RELEASE"))


limiter = Limiter(
    key_func=_api_key_id,
    storage_uri=_resolve_storage_uri(),
    strategy="fixed-window",
    headers_enabled=True,
    # Per-process fallback is useful locally but is not a real distributed
    # limit. A released process fails closed on Redis errors and health gates
    # remove it from service instead of silently weakening abuse controls.
    in_memory_fallback_enabled=not _released(),
    enabled=_limiter_enabled(),
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
