"""Admission control for compute-heavy analysis endpoints (F-CAP-1).

At ~70 concurrent authed ``POST /validate`` requests across 10 orgs, 55%
came back as HTTP 500 (``QueuePool limit of size 5 overflow 10 reached``)
because ``/validate`` holds a DB session for the WHOLE 30-80s analysis and
the pool (``src.db.engine``) is sized for a handful of short-lived sessions,
not dozens of long-held ones. Bumping the pool (see ``src.db.engine``) buys
headroom but does not, by itself, stop a burst from overrunning it -- this
module is the other half: a per-process gate that bounds how many analyses
run concurrently, so ``/validate`` (and its siblings) never queue more
in-flight work than the DB pool can actually back.

Two ceilings, both env-tunable, read live (no caching) so ops can retune
without a deploy -- mirrors ``src.auth.org_limits``'s ``_int_env`` idiom:

  - ``MAX_CONCURRENT_ANALYSES`` (default 8): global per-process cap. Must
    stay comfortably under the DB pool's real capacity (pool_size +
    max_overflow) so admission-control trips BEFORE the pool would.
  - ``MAX_CONCURRENT_ANALYSES_PER_ORG`` (default 3): fairness ceiling so one
    noisy/heavy org can't grab every global slot and starve the other nine
    -- the exact failure mode the load test surfaced (10 orgs, one bursting).

Design -- LOOP-LOCAL state (critical):
  pytest spins up a fresh event loop per test (function-scoped by default
  under pytest-asyncio), and a real ASGI server can, in principle, run
  multiple loops in a process's lifetime. A module-level global counter
  would leak state across those loop boundaries (exactly the bug
  ``parse_pool._ladder_semaphore`` already had to design around for its
  concurrency semaphore). So the in-flight counters live as an attribute
  stashed directly on the RUNNING event loop object (``loop._cadverify_
  admission_state``), created lazily on first use and garbage-collected for
  free when the loop itself is (there is no separate teardown to forget).

  Acquire/release is a single async-generator FastAPI dependency (same shape
  as ``src.db.engine.get_db_session``): the ACQUIRE (check-then-increment)
  happens before ``yield`` with NO ``await`` between the capacity check and
  the counter mutation, so nothing else can interleave -- asyncio is
  single-threaded/cooperative, and control only ever switches to another
  coroutine at an ``await`` point, so a synchronous check-then-mutate is
  atomic by construction (no lock needed). The RELEASE happens in a
  ``finally`` after ``yield`` so it runs even if the handler raises --
  FastAPI resumes (or throws into) the generator once the request is done,
  exactly like ``get_db_session``'s commit/rollback/close dance -- so a
  failed analysis still frees its slot instead of leaking it forever.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator

from fastapi import HTTPException, Request

from src.auth.models import lookup_org_membership

logger = logging.getLogger("cadverify.admission")

_TRUTHY = {"1", "true", "yes", "on"}

_STATE_ATTR = "_cadverify_admission_state"


# ---------------------------------------------------------------------------
# Tunables -- read live from env, mirrors org_limits._int_env.
# ---------------------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _max_concurrent() -> int:
    return _int_env("MAX_CONCURRENT_ANALYSES", 8)


def _max_concurrent_per_org() -> int:
    return _int_env("MAX_CONCURRENT_ANALYSES_PER_ORG", 3)


def _admission_disabled() -> bool:
    """Kill-switch, mirroring ``org_limits._org_limits_disabled``'s exact
    convention: ``ADMISSION_DISABLED`` only takes effect OUTSIDE of
    ``RELEASE`` (a dev/test convenience bypass for deterministic runs).
    Whenever ``RELEASE`` is set (production), the switch is ignored and
    admission control stays ON."""
    disabled = os.getenv("ADMISSION_DISABLED", "0").strip().lower() in _TRUTHY
    return disabled and not os.getenv("RELEASE")


def _admission_err(code: str, message: str, retry_after: int) -> HTTPException:
    """Honest 429, mirroring ``org_limits._org_err``'s body shape
    (code/message/doc_url + Retry-After) so ``structured_http_error_handler``
    passes it through untouched, headers included (gauntlet F2)."""
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
# Loop-local state
# ---------------------------------------------------------------------------


class _AdmissionState:
    """Mutable in-flight counters for ONE event loop's lifetime."""

    __slots__ = ("global_count", "per_org")

    def __init__(self) -> None:
        self.global_count = 0
        self.per_org: dict[str, int] = {}


def _state() -> _AdmissionState:
    """Return (and lazily create) THIS running loop's admission state.

    Attached to the loop object itself -- not a module global -- so it never
    crosses loops. Mirrors ``parse_pool._ladder_semaphore``'s exact pattern
    (a module-level ``asyncio.Semaphore``/counter would leak across pytest's
    per-test event loops and silently corrupt one test's counts with
    another's).
    """
    loop = asyncio.get_event_loop()
    state = getattr(loop, _STATE_ATTR, None)
    if state is None:
        state = _AdmissionState()
        setattr(loop, _STATE_ATTR, state)
    return state


def _acquire(state: _AdmissionState, org_id: str) -> None:
    """Check-then-increment with NO ``await`` in between -> atomic under
    asyncio's cooperative scheduling. Raises the honest 429 on either
    ceiling; otherwise commits both counters together."""
    limit = _max_concurrent()
    if state.global_count >= limit:
        raise _admission_err(
            "server_busy",
            "server is at capacity, retry shortly",
            5,
        )

    org_limit = _max_concurrent_per_org()
    if state.per_org.get(org_id, 0) >= org_limit:
        raise _admission_err(
            "org_at_capacity",
            f"this organization has reached its concurrent-analysis limit of {org_limit}",
            5,
        )

    state.global_count += 1
    state.per_org[org_id] = state.per_org.get(org_id, 0) + 1


def _release(state: _AdmissionState, org_id: str) -> None:
    """Undo ``_acquire`` -- always runs (caller puts this in a ``finally``),
    so a failed/raised analysis still frees its slot."""
    state.global_count = max(0, state.global_count - 1)
    remaining = state.per_org.get(org_id, 0) - 1
    if remaining <= 0:
        state.per_org.pop(org_id, None)
    else:
        state.per_org[org_id] = remaining


# ---------------------------------------------------------------------------
# Public dependency
# ---------------------------------------------------------------------------


async def admit_analysis(request: Request) -> AsyncGenerator[None, None]:
    """FastAPI async-generator dependency: bounds concurrent in-flight
    analyses (global + per-org), same shape as ``src.db.engine.get_db_
    session`` (acquire before ``yield``, release in a ``finally`` after).

    Wire via ``Depends(admit_analysis)`` on compute-heavy handlers only,
    AFTER auth has set ``request.state.authed_user`` (it reads that state
    and no-ops when it is absent). No-ops (yields straight through, no
    counters touched) when:
      - the kill-switch ``ADMISSION_DISABLED`` is active (dev/test only);
      - the caller is unauthenticated (no ``authed_user`` -- public/demo
        routes are unaffected);
      - the caller's org membership can't be resolved (defensive, same as
        ``org_limits.enforce_org_limits``);
      - the org-membership lookup itself errors (DB blip) -- fails open.

    Raises an honest 429 (``server_busy`` / ``org_at_capacity``, both with
    ``Retry-After``) instead of ever letting the request queue for a DB
    connection the pool doesn't have -- turning the 55%-of-requests-500
    failure mode into a clean, retryable 429.
    """
    if _admission_disabled():
        yield
        return

    user = getattr(request.state, "authed_user", None)
    if user is None:
        yield
        return

    try:
        membership = await lookup_org_membership(user.user_id)
    except Exception:
        logger.debug(
            "admission: org membership lookup failed for user_id=%s; failing open",
            user.user_id,
            exc_info=True,
        )
        yield
        return

    if not membership:
        yield
        return

    org_id = membership[0]
    state = _state()

    _acquire(state, org_id)
    try:
        yield
    finally:
        _release(state, org_id)
