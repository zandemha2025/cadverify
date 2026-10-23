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

Both ceilings count part checks, not calls. The app checks a part with
several calls on the same file at once (the assembly probe, the preview mesh,
``/validate``, then ``/validate/cost``); a kept part's page does the same with
its preview, orientations and bodies. Calls of one check (the organization,
the person and the file: its SHA-256, or the kept part's ``mesh_hash``) count
once, and the check stays counted for ``ADMISSION_CHECK_GRACE_SECONDS`` (5)
after its last call ends, so its next call isn't refused for room it just
gave back. A second call of the same kind on the same file at once (two
``/validate`` of the same bytes) counts as another check. The same key names
the check to the compute budget (``compute_budget.check_scope``), where the
check's calls share one reservation.

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

from src.config.public_urls import error_doc_url

import asyncio
import hashlib
import logging
import os
import time
from collections import deque
from typing import AsyncGenerator, Optional

from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile as _UploadFile

from src.auth.models import lookup_org_membership
from src.services import compute_budget

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


def _check_grace_seconds() -> float:
    """How long a check stays counted after its last call (``ADMISSION_CHECK_GRACE_SECONDS``, 5)."""
    try:
        return max(0.0, float(os.getenv("ADMISSION_CHECK_GRACE_SECONDS", "5")))
    except ValueError:
        return 5.0


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
            "doc_url": error_doc_url(code),
        },
    )


# ---------------------------------------------------------------------------
# Loop-local state
# ---------------------------------------------------------------------------


class _Check:
    """The calls of one part check in flight: how many of each kind, and how much it counts."""

    __slots__ = ("org_id", "kinds", "units", "linger")

    def __init__(self, org_id: str) -> None:
        self.org_id = org_id
        self.kinds: dict[str, int] = {}
        self.units = 0  # what it counts toward both ceilings
        self.linger: Optional[asyncio.TimerHandle] = None


class _AdmissionState:
    """Mutable in-flight counters for ONE event loop's lifetime."""

    __slots__ = ("global_count", "per_org", "durations", "checks")

    def __init__(self) -> None:
        # Checks in flight (a check of several calls counts once), not calls.
        self.global_count = 0
        self.per_org: dict[str, int] = {}
        # How long recent analyses took on this process, by kind (validate,
        # cost): (org_id, seconds). Read by the check card's expected time (me-21).
        self.durations: dict[str, deque] = {}
        self.checks: dict[str, _Check] = {}


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


def _refuse_over(state: _AdmissionState, org_id: str, more: int) -> None:
    """Raise the honest 429 when ``more`` checks wouldn't fit under either ceiling."""
    if more <= 0:
        return
    limit = _max_concurrent()
    if state.global_count + more > limit:
        raise _admission_err(
            "server_busy",
            "server is at capacity, retry shortly",
            5,
        )

    org_limit = _max_concurrent_per_org()
    if state.per_org.get(org_id, 0) + more > org_limit:
        raise _admission_err(
            "org_at_capacity",
            f"this organization has reached its concurrent-analysis limit of {org_limit}",
            5,
        )


def _count(state: _AdmissionState, org_id: str, delta: int) -> None:
    state.global_count = max(0, state.global_count + delta)
    remaining = state.per_org.get(org_id, 0) + delta
    if remaining <= 0:
        state.per_org.pop(org_id, None)
    else:
        state.per_org[org_id] = remaining


def _acquire(state: _AdmissionState, org_id: str, key: Optional[str] = None, kind: str = "call") -> None:
    """Check-then-increment with NO ``await`` in between -> atomic under
    asyncio's cooperative scheduling. Raises the honest 429 on either
    ceiling; otherwise commits both counters together.

    ``key`` names the part check the call belongs to (None: a check of its
    own). A call joining its check counts nothing more, unless the check
    already has a call of the same ``kind`` in flight: then it counts as one
    more check.
    """
    if key is None:
        _refuse_over(state, org_id, 1)
        _count(state, org_id, 1)
        return
    check = state.checks.get(key)
    if check is None:
        check = _Check(org_id)
    same_kind = check.kinds.get(kind, 0) + 1
    more = max(check.units, same_kind) - check.units
    _refuse_over(state, org_id, more)
    if check.linger is not None:
        check.linger.cancel()
        check.linger = None
    check.kinds[kind] = same_kind
    check.units += more
    state.checks[key] = check
    _count(state, org_id, more)


def _release(state: _AdmissionState, org_id: str, key: Optional[str] = None, kind: str = "call") -> None:
    """Undo ``_acquire`` -- always runs (caller puts this in a ``finally``),
    so a failed/raised analysis still frees its slot.

    A check whose last call ended stays counted for the grace period, so its
    next call (the price after the check) finds its room.
    """
    if key is None:
        _count(state, org_id, -1)
        return
    check = state.checks.get(key)
    if check is None:
        return
    left = check.kinds.get(kind, 0) - 1
    if left > 0:
        check.kinds[kind] = left
    else:
        check.kinds.pop(kind, None)
    units = max(check.kinds.values(), default=0)
    grace = _check_grace_seconds()
    if units == 0 and grace > 0:
        units = 1  # counted a little longer: its next call is usually a second away
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and check.linger is None:
            check.linger = loop.call_later(grace, _expire, state, key, check)
        elif loop is None:
            units = 0
    if units < check.units:
        _count(state, org_id, units - check.units)
        check.units = units
    if check.units == 0:
        state.checks.pop(key, None)


def _expire(state: _AdmissionState, key: str, check: _Check) -> None:
    """The grace after a check's last call ended: it no longer counts."""
    check.linger = None
    if state.checks.get(key) is not check or check.kinds:
        return
    _count(state, check.org_id, -check.units)
    check.units = 0
    state.checks.pop(key, None)


def _call_kind(request) -> str:
    """Which call of a check this is: its path, and the query that makes it a different call."""
    url = getattr(request, "url", None)
    path = (getattr(url, "path", "") or "").rstrip("/")
    query = getattr(request, "query_params", None) or {}
    for name in ("format", "purpose"):
        value = query.get(name) if hasattr(query, "get") else None
        if value:
            path += f"?{name}={str(value).lower()}"
    return path or "call"


async def _sha256_of(file: _UploadFile) -> str:
    digest = hashlib.sha256()
    try:
        await file.seek(0)
        while chunk := await file.read(1024 * 1024):
            digest.update(chunk)
    finally:
        await file.seek(0)
    return digest.hexdigest()


async def _check_key(request, org_id: str, user_id) -> Optional[str]:
    """The part check this call belongs to: the organization, the person and the file.

    The file is its SHA-256 (every uploaded file of the call, in order), or
    the kept part's ``mesh_hash`` (the SHA-256 of its stored bytes). None
    when the call names no file: it is a check of its own.
    """
    files: list[str] = []
    params = getattr(request, "path_params", None) or {}
    mesh_hash = params.get("mesh_hash") if hasattr(params, "get") else None
    if mesh_hash:
        files.append(str(mesh_hash).lower())
    headers = getattr(request, "headers", None)
    ctype = headers.get("content-type", "") if headers is not None and hasattr(headers, "get") else ""
    if "multipart/form-data" in ctype and hasattr(request, "form"):
        try:
            form = await request.form()  # already parsed for the route: the same object
            for _name, value in form.multi_items():
                if isinstance(value, _UploadFile):
                    files.append(await _sha256_of(value))
        except Exception:
            logger.debug("admission: could not name the check's file", exc_info=True)
    if not files:
        return None
    return f"{org_id}:{user_id}:{'+'.join(files)}"


TIMING_KEEP = 50


def _kind(path: str) -> str | None:
    """The two calls a part check makes: ``validate`` (process checks) and ``cost`` (prices)."""
    p = path.rstrip("/")
    if p.endswith("/validate/cost"):
        return "cost"
    if p.endswith("/validate"):
        return "validate"
    return None


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    o = sorted(xs)
    m = len(o) // 2
    return o[m] if len(o) % 2 else (o[m - 1] + o[m]) / 2


def recent_timing(org_id: str | None, samples: int = 10) -> dict:
    """Median seconds of the last ``samples`` validations and pricings on this
    server process: the org's own when it has some, else everyone's (said in
    ``basis``). None when nothing ran since the process started."""
    state = _state()
    out: dict = {"basis": None}
    for kind in ("validate", "cost"):
        rows = list(state.durations.get(kind, ()))
        mine = [sec for org, sec in rows if org == org_id][-samples:]
        use = mine or [sec for _org, sec in rows][-samples:]
        if mine:
            out["basis"] = "org"
        elif use and out["basis"] is None:
            out["basis"] = "server"
        out[f"{kind}_s"] = round(_median(use), 1) if use else None
        out[f"{kind}_samples"] = len(use)
    return out


def in_flight(org_id: str | None) -> tuple[int, int]:
    """Analyses running now on this server process: all of them, and the org's.
    A read of the same counters admission uses (me-21: "3 checks ahead of
    yours"); one process's view, never a fleet-wide queue."""
    state = _state()
    return state.global_count, state.per_org.get(org_id or "", 0)


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
    key = await _check_key(request, org_id, user.user_id)
    call = _call_kind(request)
    state = _state()

    _acquire(state, org_id, key, call)
    url = getattr(request, "url", None)
    kind = _kind(getattr(url, "path", "") or "")
    t0 = time.monotonic()

    def note() -> None:
        if kind:
            state.durations.setdefault(kind, deque(maxlen=TIMING_KEEP)).append((org_id, time.monotonic() - t0))

    try:
        # The compute budget gives the calls of this check one reservation.
        with compute_budget.check_scope(key):
            yield
        note()
    except HTTPException as exc:
        # A check that ran out of time took that long too: it counts toward how long checks take here.
        if exc.status_code == 504:
            note()
        raise
    finally:
        _release(state, org_id, key, call)
