"""Per-org resource-isolation circuit breakers (W-ORG-ISO).

ADDITIVE to the existing per-IDENTITY limiter (``src.auth.rate_limit``): that
limiter buckets by API key / dashboard user / IP (``_api_key_id``) and has no
org dimension at all, so ten API keys inside one noisy org can each sit just
under their own 60/hour;500/day ceiling while collectively hammering shared
infra hard enough to degrade the other nine orgs on the platform. This module
adds a second, COARSER ceiling keyed by org, so a runaway/abusive org gets
throttled as a whole even when every individual identity inside it looks fine.

Two independent guards, both fail-open (a broken guard must never degrade
legit traffic worse than the flood it's meant to stop):

  (a) A Redis fixed-window circuit-breaker (``org:rl:h:*`` / ``org:rl:d:*``),
      same INCR+EXPIRE idiom as ``signup_limits.per_ip_signup_limit``. Cheap,
      fast, resets automatically, but not durable across a Redis flush/outage.
  (b) A durable daily-analyses quota backed by a live count over the
      ``analyses`` table (same query shape as
      ``admin_routes.get_usage_summary``), so the cap survives a Redis blip
      and reflects reality even if the Redis counters were reset.

Ceilings rationale (tunable via env, no deploy needed):
  A legitimate heavy org -- a handful of users/keys plus batch traffic -- does
  at most low-thousands of requests per day; the per-IDENTITY ceiling is
  already 500/day (60/hour). Setting the org aggregate at ORG_RATE_LIMIT_PER_DAY
  (20000/day) and ORG_RATE_LIMIT_PER_HOUR (2000/hour) is roughly 10-40x a
  single identity's allowance -- headroom no legitimate org of a few keys
  should ever approach, but a looping/misconfigured/abusive client trips
  quickly. ORG_ANALYSES_PER_DAY (5000/day) is the durable backstop on the same
  reasoning, sized against real persisted volume rather than raw HTTP hits.
  Retune later from ``get_usage_summary``'s real per-org counters.

Both guards are OFF for unauthenticated callers (no org to scope to) and OFF
whenever the caller's org can't be resolved -- this is a circuit-breaker for
abuse, not a new authorization gate, so an unresolvable org fails OPEN rather
than blocking a request the per-identity limiter and RBAC already gated.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from fastapi import HTTPException, Request
from sqlalchemy import func, select

from src.auth.models import lookup_org_membership
from src.auth.redis_util import require_redis_url
from src.db.engine import get_session_factory
from src.db.models import Analysis

logger = logging.getLogger("cadverify.org_limits")

_TRUTHY = {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Tunables -- read live from env (no caching) so ops can retune without a
# deploy. Mirrors the lazy os.getenv() reads in bom.py/manifest.py's
# _import_cap_bytes() style.
# ---------------------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _hour_ceiling() -> int:
    return _int_env("ORG_RATE_LIMIT_PER_HOUR", 2000)


def _day_ceiling() -> int:
    return _int_env("ORG_RATE_LIMIT_PER_DAY", 20000)


def _analyses_per_day_ceiling() -> int:
    return _int_env("ORG_ANALYSES_PER_DAY", 5000)


def _org_limits_disabled() -> bool:
    """Kill-switch, mirroring ``rate_limit._limiter_enabled``'s exact convention.

    ``ORG_RATE_LIMIT_DISABLED`` only takes effect OUTSIDE of ``RELEASE``
    (dev/test convenience bypass for deterministic runs). Whenever ``RELEASE``
    is set (production), the switch is ignored and the org ceilings stay ON --
    identical semantics to ``RATE_LIMIT_DISABLED`` / ``SIGNUP_RATE_LIMIT_DISABLED``.
    """
    disabled = os.getenv("ORG_RATE_LIMIT_DISABLED", "0").strip().lower() in _TRUTHY
    return disabled and not os.getenv("RELEASE")


def _r() -> aioredis.Redis:
    return aioredis.from_url(require_redis_url(), decode_responses=True)


def _org_err(code: str, message: str, retry_after: int) -> HTTPException:
    """Honest 429, mirroring ``rate_limit.rate_limit_handler`` /
    ``signup_limits._err``'s body shape (code/message/doc_url + Retry-After)."""
    retry_after = max(int(retry_after), 1)
    return HTTPException(
        status_code=429,
        headers={"Retry-After": str(retry_after)},
        detail={
            "code": code,
            "message": message,
            "doc_url": f"https://docs.cadverify.com/errors#{code}",
        },
    )


# ---------------------------------------------------------------------------
# (a) Redis fixed-window circuit-breaker
# ---------------------------------------------------------------------------


async def _check_redis_ceiling(org_id: str) -> None:
    """INCR+EXPIRE hour + day counters for ``org_id``; 429 over ceiling.

    Fail-open: ANY Redis error (unreachable, unconfigured REDIS_URL, timeout)
    is swallowed and logged -- a Redis blip must never 429 legitimate traffic.
    The per-identity slowapi limiter still applies regardless.
    """
    now = int(time.time())
    hour_bucket = now // 3600
    day_bucket = now // 86400
    hour_key = f"org:rl:h:{org_id}:{hour_bucket}"
    day_key = f"org:rl:d:{org_id}:{day_bucket}"

    try:
        r = _r()
        hour_count = await r.incr(hour_key)
        if hour_count == 1:
            await r.expire(hour_key, 3600)
        day_count = await r.incr(day_key)
        if day_count == 1:
            await r.expire(day_key, 86400)
    except Exception:
        logger.debug(
            "org_limits: Redis ceiling check failed for org=%s; failing open",
            org_id,
            exc_info=True,
        )
        return

    if hour_count > _hour_ceiling():
        retry_after = 3600 - (now % 3600)
        raise _org_err(
            "org_rate_limited",
            "this organization has exceeded its request ceiling; "
            f"retry after {retry_after}s",
            retry_after,
        )
    if day_count > _day_ceiling():
        retry_after = 86400 - (now % 86400)
        raise _org_err(
            "org_rate_limited",
            "this organization has exceeded its request ceiling; "
            f"retry after {retry_after}s",
            retry_after,
        )


# ---------------------------------------------------------------------------
# (b) Durable daily-analyses quota
# ---------------------------------------------------------------------------


async def _daily_analyses_count(org_id: str) -> int:
    """Live count of ``analyses`` rows for ``org_id`` in the trailing 24h.

    Same query shape as ``admin_routes.get_usage_summary``'s ``_count``
    helper, but opens its own short-lived session (like
    ``auth.models.lookup_org_membership``) so this dependency composes
    without relying on the calling route's own ``get_db_session`` dependency.
    """
    since = datetime.now(timezone.utc) - timedelta(days=1)
    factory = get_session_factory()
    async with factory() as session:
        stmt = (
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.org_id == org_id, Analysis.created_at >= since)
        )
        return int((await session.execute(stmt)).scalar_one())


async def _check_daily_analyses_quota(org_id: str) -> None:
    """429 (``org_quota_exceeded``) once the org's trailing-24h analyses count
    reaches ``ORG_ANALYSES_PER_DAY``. Fail-open on any DB error."""
    limit = _analyses_per_day_ceiling()
    try:
        count = await _daily_analyses_count(org_id)
    except Exception:
        logger.debug(
            "org_limits: daily-analyses quota check failed for org=%s; failing open",
            org_id,
            exc_info=True,
        )
        return

    if count >= limit:
        raise _org_err(
            "org_quota_exceeded",
            f"this organization has reached its daily analyses cap of {limit}; "
            "it resets on a rolling ~24h window",
            86400,
        )


# ---------------------------------------------------------------------------
# Public dependency
# ---------------------------------------------------------------------------


async def enforce_org_limits(request: Request) -> None:
    """FastAPI dependency: per-org circuit-breakers. Use via
    ``dependencies=[Depends(enforce_org_limits)]`` or as a handler param, on
    compute-heavy routes only -- MUST be wired to run AFTER ``require_api_key``
    / ``require_role`` (i.e. after ``request.state.authed_user`` is set), since
    it reads that state and no-ops when it is absent.

    No-ops (fail OPEN, request proceeds unchanged) when:
      - the kill-switch ``ORG_RATE_LIMIT_DISABLED`` is active (dev/test only);
      - the caller is unauthenticated (no ``authed_user`` -- public/demo
        routes are untouched);
      - the caller's org membership can't be resolved (defensive: a
        superadmin or a mocked test principal with no membership row);
      - the org-membership lookup itself errors (DB blip).
    """
    if _org_limits_disabled():
        return

    user = getattr(request.state, "authed_user", None)
    if user is None:
        return

    try:
        membership = await lookup_org_membership(user.user_id)
    except Exception:
        logger.debug(
            "org_limits: org membership lookup failed for user_id=%s; failing open",
            user.user_id,
            exc_info=True,
        )
        return

    if not membership:
        return

    org_id = membership[0]

    await _check_redis_ceiling(org_id)
    await _check_daily_analyses_quota(org_id)
