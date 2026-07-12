"""Lightweight arq worker heartbeat.

The API process is not the worker, so ``/health`` cannot observe worker
liveness directly -- it can only read something the worker leaves in Redis.
arq writes its own ``<queue>:health-check`` key, but that value's format is not
contractually stable and carries no easily parsed timestamp. This module adds a
tiny, explicit heartbeat the worker refreshes on startup and once per minute:

    Redis key ``WORKER_HEARTBEAT_KEY`` (default ``cadverify:worker:heartbeat``)
    value = ISO-8601 UTC timestamp, with a TTL so a dead worker's key expires.

``/health/deep`` reads it and reports the *age* of the last heartbeat, degrading
honestly to ``stale``/``unknown`` when the worker is late or absent -- never a
fabricated ``ok``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("cadverify.worker.heartbeat")

HEARTBEAT_KEY = os.getenv("WORKER_HEARTBEAT_KEY", "cadverify:worker:heartbeat")
# TTL so the key self-expires shortly after a worker dies.
HEARTBEAT_TTL_SECONDS = int(os.getenv("WORKER_HEARTBEAT_TTL_SECONDS", "150"))
# Age beyond which a present heartbeat is considered stale (worker wedged).
HEARTBEAT_STALE_SECONDS = int(os.getenv("WORKER_HEARTBEAT_STALE_SECONDS", "90"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key() -> str:
    # Re-read env at call time so tests can override the key name.
    return os.getenv("WORKER_HEARTBEAT_KEY", HEARTBEAT_KEY)


def _ttl() -> int:
    return int(os.getenv("WORKER_HEARTBEAT_TTL_SECONDS", str(HEARTBEAT_TTL_SECONDS)))


async def write_heartbeat(redis: Any, *, now: Optional[datetime] = None) -> str:
    """Write/refresh the heartbeat key with a TTL. Returns the ISO value."""
    stamp = (now or _now()).isoformat()
    await redis.set(_key(), stamp, ex=_ttl())
    return stamp


async def read_heartbeat_age(
    redis: Any, *, now: Optional[datetime] = None
) -> Optional[int]:
    """Return the age in seconds of the last heartbeat, or ``None`` if absent
    or unparseable (an honest 'unknown', never a fabricated fresh value)."""
    raw = await redis.get(_key())
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or _now()
    return max(0, int((now - ts).total_seconds()))


def classify_worker(
    *,
    redis_ok: bool,
    heartbeat_age: Optional[int],
    arq_key_present: bool,
    stale_seconds: Optional[int] = None,
) -> str:
    """Map probe inputs to an honest worker state.

    Returns one of ``ok`` | ``stale`` | ``unknown`` | ``unavailable``.
    """
    if not redis_ok:
        return "unavailable"
    threshold = stale_seconds if stale_seconds is not None else HEARTBEAT_STALE_SECONDS
    if heartbeat_age is not None:
        return "ok" if heartbeat_age <= threshold else "stale"
    # No explicit heartbeat -- fall back to arq's own key as a coarse signal.
    if arq_key_present:
        return "ok"
    return "unknown"


async def worker_heartbeat(ctx: dict) -> None:
    """arq cron entrypoint: refresh the heartbeat each tick."""
    redis = ctx.get("redis")
    if redis is None:  # pragma: no cover - defensive
        logger.warning("worker_heartbeat: no redis in ctx")
        return
    try:
        await write_heartbeat(redis)
    except Exception:  # pragma: no cover - never fail the worker on heartbeat
        logger.exception("worker_heartbeat: failed to write heartbeat")
