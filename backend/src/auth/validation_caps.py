"""Hard product caps: at most N validations per organization AND per user.

ADDITIVE to the two existing guards:

  - ``src.auth.rate_limit``      -- per-IDENTITY request throttle (60/hour;500/day),
                                    a burst control, not a product quota.
  - ``src.auth.org_limits``      -- per-org circuit-breaker against runaway
                                    aggregate volume (2000/hour;20000/day requests,
                                    5000 analyses/day durable). Sized as an abuse
                                    backstop, far above any pilot allowance.

This module enforces the actual PRODUCT LIMIT the launch carries: a caller may
run at most ``VALIDATION_CAP_PER_ORG`` validations (persisted ``analyses`` rows)
per organization, AND at most ``VALIDATION_CAP_PER_USER`` per user -- whichever
binds first. A validation is counted when it is persisted (an ``analyses`` row
exists), so cached/deduped re-reads of an existing result do not burn the cap.

Window semantics (env-tunable, no deploy needed):
  ``VALIDATION_CAP_WINDOW_DAYS`` unset or 0  -> LIFETIME cap (the launch rule:
                                                100 total validations per org
                                                and per user).
  ``VALIDATION_CAP_WINDOW_DAYS`` = k > 0     -> rolling trailing-k-days cap.

Both counts are durable (live ``SELECT count(*)`` over ``analyses``, same query
shape as ``org_limits._daily_analyses_count`` / ``admin_routes.get_usage_summary``),
so the caps survive a Redis flush/outage -- Redis is not involved at all.

Honesty in the error: a lifetime cap carries NO ``Retry-After`` header (there is
nothing to wait for); a windowed cap carries ``Retry-After`` set to the window.

Fail-open philosophy, mirroring ``org_limits``: a broken guard must never block
legit traffic harder than the abuse it prevents -- a DB error during the count
logs a WARNING and lets the request through. When the DB is down, no analysis
row can be created anyway, so fail-open cannot be exploited to persist work.

Concurrency note: the check is count-then-write, so N concurrent requests at
cap-1 can overshoot by up to N-1. This matches the durable quota semantics
already shipped in ``org_limits``; closing it fully needs a serializable
transaction or a counter table, deferred deliberately (pilot scale).

No-ops (fail OPEN) when:
  - kill-switch ``VALIDATION_CAPS_DISABLED`` is set OUTSIDE of RELEASE;
  - the caller is unauthenticated (public/demo routes, which persist nothing);
  - the caller's org membership cannot be resolved (same defensive rule as
    ``org_limits`` -- RBAC and the per-identity limiter already gated);
  - the count query errors (DB blip).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import func, select

from src.auth.models import lookup_org_membership
from src.config.public_urls import error_doc_url
from src.db.engine import get_session_factory
from src.db.models import Analysis, User

logger = logging.getLogger("cadverify.validation_caps")

_TRUTHY = {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _org_cap() -> int:
    return _int_env("VALIDATION_CAP_PER_ORG", 100)


def _user_cap() -> int:
    return _int_env("VALIDATION_CAP_PER_USER", 100)


def _window_days() -> int:
    """0 => lifetime (the launch rule). >0 => rolling window in days."""
    return max(_int_env("VALIDATION_CAP_WINDOW_DAYS", 0), 0)


def _caps_disabled() -> bool:
    """Kill-switch, same convention as ``org_limits._org_limits_disabled`` /
    ``rate_limit._limiter_enabled``: honored only OUTSIDE of ``RELEASE``."""
    disabled = os.getenv("VALIDATION_CAPS_DISABLED", "0").strip().lower() in _TRUTHY
    return disabled and not os.getenv("RELEASE")


def _cap_err(code: str, message: str, windowed: bool) -> HTTPException:
    headers = {}
    if windowed:
        headers["Retry-After"] = str(_window_days() * 86400)
    return HTTPException(
        status_code=429,
        headers=headers or None,
        detail={
            "code": code,
            "message": message,
            "doc_url": error_doc_url(code),
        },
    )


async def _count(column, key, since) -> int:
    """Live count of ``analyses`` rows for one dimension, own short-lived
    session (same composition rule as ``org_limits._daily_analyses_count``)."""
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(func.count()).select_from(Analysis).where(column == key)
        if since is not None:
            stmt = stmt.where(Analysis.created_at >= since)
        return int((await session.execute(stmt)).scalar_one())


async def _user_plan(user_id: int) -> str:
    """The caller's product plan; a missing row means 'trial' (the safe
    default). A DB error here fails open in the caller exactly like the count
    query: if the DB is down, no analysis row can persist anyway."""
    factory = get_session_factory()
    async with factory() as session:
        plan = (
            await session.execute(select(User.plan).where(User.id == user_id))
        ).scalar_one_or_none()
    return str(plan) if plan else "trial"


async def user_trial_usage(user_id: int) -> dict:
    """Usage read for the caller's own quota card ("X of Y trial checks used").

    Same durable count and window semantics as enforcement, so the card can
    never disagree with the gate. Pilot plan reports unlimited instead of a
    number it does not enforce."""
    plan = await _user_plan(user_id)
    if plan == "pilot":
        return {"plan": plan, "unlimited": True, "used": None, "cap": None, "remaining": None}
    since = (
        datetime.now(timezone.utc) - timedelta(days=_window_days())
        if _window_days() > 0
        else None
    )
    used = await _count(Analysis.user_id, user_id, since)
    cap = _user_cap()
    return {
        "plan": plan,
        "unlimited": False,
        "used": used,
        "cap": cap,
        "remaining": max(cap - used, 0),
        "window_days": _window_days(),
    }


async def enforce_validation_caps(request: Request) -> None:
    """FastAPI dependency: hard product caps on validations. Wire AFTER
    ``require_api_key`` / ``require_role`` (needs ``request.state.authed_user``),
    alongside ``enforce_org_limits`` on every analysis-creating route.
    """
    if _caps_disabled():
        return

    user = getattr(request.state, "authed_user", None)
    if user is None:
        return

    try:
        membership = await lookup_org_membership(user.user_id)
    except Exception:
        logger.debug(
            "validation_caps: org membership lookup failed for user_id=%s; failing open",
            user.user_id,
            exc_info=True,
        )
        return

    if not membership:
        return

    org_id = membership[0]

    try:
        plan = await _user_plan(user.user_id)
    except Exception:
        logger.debug(
            "validation_caps: plan lookup failed for user_id=%s; enforcing as trial",
            user.user_id,
            exc_info=True,
        )
        plan = "trial"
    if plan == "pilot":
        # Pilot accounts (owner/demo) are never trial-gated.
        return

    windowed = _window_days() > 0
    since = (
        datetime.now(timezone.utc) - timedelta(days=_window_days())
        if windowed
        else None
    )

    try:
        org_count = await _count(Analysis.org_id, org_id, since)
        user_count = await _count(Analysis.user_id, user.user_id, since)
    except Exception:
        logger.warning(
            "validation_caps: count query failed for org=%s user=%s; failing open",
            org_id,
            user.user_id,
            exc_info=True,
        )
        return

    period = f"in the trailing {_window_days()} days" if windowed else "in total"
    if org_count >= _org_cap():
        raise _cap_err(
            "org_validation_cap_exceeded",
            f"this organization has reached its cap of {_org_cap()} validations "
            f"{period}",
            windowed,
        )
    if user_count >= _user_cap():
        # Trial exhaustion is a plan gate, not a throttle: 403 with a
        # remaining-count payload the UI can render honestly. The org cap
        # above stays a 429 circuit-breaker.
        raise HTTPException(
            status_code=403,
            detail={
                "code": "user_validation_cap_exceeded",
                "message": (
                    f"this account has used its {_user_cap()} trial checks; "
                    "talk to the ProofShape team to keep going"
                ),
                "used": user_count,
                "cap": _user_cap(),
                "remaining": 0,
                "plan": plan,
                "doc_url": error_doc_url("user_validation_cap_exceeded"),
            },
        )
