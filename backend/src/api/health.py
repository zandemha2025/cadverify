"""Health check endpoint with Postgres + Redis probes."""

from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()


@router.get("/health")
async def health_check():
    """Returns 200 if all dependencies are reachable, 503 if degraded."""
    checks: dict[str, bool] = {"postgres": False, "redis": False}
    version = os.getenv("RELEASE", "dev")

    # Postgres probe
    try:
        from src.db.engine import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception:
        pass

    # Redis probe — connect directly from REDIS_URL (no get_redis helper exists;
    # slowapi manages its own connection internally).
    try:
        redis_url = os.getenv("REDIS_URL")
        if redis_url and redis_url != "memory://":
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
            checks["redis"] = True
        else:
            # No Redis configured — report as healthy (in-memory fallback mode)
            checks["redis"] = True
    except Exception:
        pass

    all_ok = all(checks.values())
    return JSONResponse(
        content={
            "status": "ok" if all_ok else "degraded",
            "version": version,
            **checks,
        },
        status_code=200 if all_ok else 503,
    )
