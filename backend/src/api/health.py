"""Health check endpoint with Postgres + Redis/async-tier probes.

Honesty invariant (F-ARCH-2): /health must never claim a dependency is healthy
when it is absent. The async tier (Redis + the arq worker) powers batch jobs,
reconstruction, magic-link signup, and signup rate limits. When it is *expected*
(a real REDIS_URL is configured, or we are running a released/production build)
but *absent*, the endpoint reports the truth and returns ``degraded`` (503).

Off-switch: ASYNC_STRICT_HEALTH=0 makes the async tier's absence non-fatal to
the overall status (it is still reported truthfully in the ``async`` block).
Worker gate: WORKER_STRICT_HEALTH=1 also treats a missing arq heartbeat as
degraded when Redis is reachable and the async tier is expected.
"""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


@router.get("/health")
async def health_check():
    """Return 200 when healthy, 503 when degraded.

    Response shape::

        {
          "status": "ok" | "degraded",
          "version": "...",
          "postgres": bool,           # real probe
          "redis": bool,              # real probe (backward-compat top-level)
          "async": {
            "redis": bool,            # real probe
            "worker": "ok"|"unknown"|"unavailable",
            "expected": bool          # is the async tier expected in this env?
          },
          "reconstruction": {...}
        }
    """
    version = os.getenv("RELEASE", "dev")
    strict = _flag("ASYNC_STRICT_HEALTH", "1")
    worker_strict = _flag("WORKER_STRICT_HEALTH", "0")

    # Postgres probe
    postgres_ok = False
    try:
        from src.db.engine import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        postgres_ok = True
    except Exception:
        pass

    # Async tier: is it expected here, and is it actually reachable?
    redis_url = os.getenv("REDIS_URL")
    redis_configured = bool(redis_url) and redis_url != "memory://"
    # The async tier is "expected" when the operator configured a real Redis, or
    # when this is a released/production build (RELEASE set) where batch jobs,
    # reconstruction, and magic-link signup all require it.
    async_expected = redis_configured or bool(os.getenv("RELEASE"))

    redis_ok = False
    worker_state = "unavailable"
    if redis_configured:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, socket_connect_timeout=2)
            try:
                await r.ping()
                redis_ok = True
                # Honest worker probe: arq workers heartbeat into a health-check
                # key with a short TTL. If it is present a worker is alive; if
                # not, we genuinely cannot confirm one (the API is not the
                # worker) -> "unknown", never a fabricated "ok".
                health_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")
                try:
                    worker_state = "ok" if await r.exists(health_key) else "unknown"
                except Exception:
                    worker_state = "unknown"
            finally:
                await r.aclose()
        except Exception:
            redis_ok = False
            worker_state = "unavailable"
    else:
        # No real Redis configured. Do NOT claim it is healthy.
        redis_ok = False
        worker_state = "unavailable"

    async_block = {
        "redis": redis_ok,
        "worker": worker_state,
        "expected": async_expected,
        "worker_strict": worker_strict,
    }

    # Honest reconstruction capability report (not a health gate: reconstruction
    # being unavailable in a zero-egress deployment is a valid, intended state).
    try:
        from src.services.reconstruction_service import (
            check_reconstruction_availability,
        )

        recon = check_reconstruction_availability()
        reconstruction = {
            "available": recon["available"],
            "backend": recon["effective_backend"],
            "egress": recon["egress"],
        }
    except Exception:
        reconstruction = {"available": False, "backend": "unknown", "egress": False}

    # Degraded when Postgres is down, or when the async tier is expected+strict
    # but unreachable. Worker "unknown" is honest uncertainty, not a failure, so
    # it does not gate status.
    async_degraded = strict and async_expected and not redis_ok
    worker_degraded = worker_strict and async_expected and redis_ok and worker_state != "ok"
    healthy = postgres_ok and not async_degraded
    healthy = healthy and not worker_degraded

    return JSONResponse(
        content={
            "status": "ok" if healthy else "degraded",
            "version": version,
            "postgres": postgres_ok,
            "redis": redis_ok,
            "async": async_block,
            "reconstruction": reconstruction,
        },
        status_code=200 if healthy else 503,
    )
