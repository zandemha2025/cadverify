"""One compute budget per process: the CAD work in flight fits in its memory.

Every CPU-heavy CAD step (a parse, the DFM analysis, a price, a repair, a
preview) reserves room here before it starts, in two dimensions:

  - memory: the piece of work's estimate, from the measured per-check model
    (``stored_check_service.estimate_memory_bytes_for_data``);
  - a compute slot: one per piece of work, ``COMPUTE_SLOTS`` in all
    (default ``max(2, os.cpu_count())``).

The memory capacity is ``COMPUTE_MEMORY_BUDGET_MB`` when set, otherwise
``COMPUTE_MEMORY_FRACTION`` (0.7) of the machine's (or container's) memory.

A reservation is held until the work has really ended. ``asyncio.wait_for``
can stop waiting for an executor thread, but it can't stop the thread: a part
that ran past its time limit keeps computing and keeps its arrays. So the
release happens in the executor thread's own ``finally``, when the computation
returns or raises, never when an await is cancelled. A retry of a timed-out
part therefore waits for room while its abandoned first attempt still runs.

Work bigger than the whole budget runs only when nothing else is running.
Waiters are admitted first come, first served, so a big part is never starved
by a stream of small ones. The state is process-wide and thread-safe (a
release happens on an executor thread); it is never tied to one event loop.

Use:

    async with hold(need_bytes, wait=..., label="catalog part"):
        ...  # several steps; each run_within_budget() call inside joins this hold

    await run_within_budget(fn, *args, need_bytes=..., timeout=..., label=...)

A hold inside a hold joins the outer one (one reservation for the whole job:
a catalog part's analysis and price, a request's parse and analysis). Each
``run_within_budget`` thread joins the current hold, or reserves on its own when
there is none. The outer hold's room comes back when the last of its threads ends.

Waiting: in a web process a hold waits at most ``COMPUTE_WAIT_SECONDS`` (15) and
then raises :class:`ComputeBusy`, the API's existing 429 ``server_busy`` with
Retry-After. The worker (``worker_process()`` at startup) waits without limit by
default; its job-level holds pass their own bound and put the job back in the
queue when it passes (``src.jobs.batch_tasks``, ``src.jobs.stored_check_tasks``).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional

import structlog
from fastapi import HTTPException

logger = logging.getLogger("cadverify.compute_budget")
slog = structlog.get_logger("cadverify.compute_budget")

MB = 1024 * 1024
DEFAULT_MEMORY_FRACTION = 0.7
DEFAULT_WAIT_SECONDS = 15.0
BUSY_RETRY_AFTER_SECONDS = 5


# ---------------------------------------------------------------------------
# Settings (read on every reservation, so ops can retune without a deploy)
# ---------------------------------------------------------------------------


def _machine_memory_bytes() -> Optional[int]:
    from src.services.stored_check_service import _container_memory_bytes

    return _container_memory_bytes()


def memory_capacity_bytes() -> int:
    """``COMPUTE_MEMORY_BUDGET_MB``, else ``COMPUTE_MEMORY_FRACTION`` (0.7) of this machine's memory."""
    raw = os.getenv("COMPUTE_MEMORY_BUDGET_MB", "").strip()
    if raw:
        try:
            return max(64, int(float(raw))) * MB
        except ValueError:
            pass
    try:
        fraction = float(os.getenv("COMPUTE_MEMORY_FRACTION", str(DEFAULT_MEMORY_FRACTION)))
    except ValueError:
        fraction = DEFAULT_MEMORY_FRACTION
    fraction = min(max(fraction, 0.1), 0.95)
    total = _machine_memory_bytes() or 2 * 1024**3
    return int(total * fraction)


def compute_slots() -> int:
    """``COMPUTE_SLOTS``, else ``max(2, os.cpu_count())``."""
    default = max(2, os.cpu_count() or 2)
    raw = os.getenv("COMPUTE_SLOTS", "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def compute_wait_seconds() -> float:
    """How long a web request waits for room before it answers 429 (``COMPUTE_WAIT_SECONDS``, 15)."""
    try:
        return max(0.0, float(os.getenv("COMPUTE_WAIT_SECONDS", str(DEFAULT_WAIT_SECONDS))))
    except ValueError:
        return DEFAULT_WAIT_SECONDS


_WAIT_WITHOUT_LIMIT = False


def worker_process() -> None:
    """Called once by the arq worker at startup: work waits for room, it never fails for it."""
    global _WAIT_WITHOUT_LIMIT
    _WAIT_WITHOUT_LIMIT = True


def default_wait() -> Optional[float]:
    """The wait bound when the caller gives none: none in the worker, ``COMPUTE_WAIT_SECONDS`` on the web."""
    return None if _WAIT_WITHOUT_LIMIT else compute_wait_seconds()


def job_wait_seconds(job_started: float, work_seconds: float, job_timeout: float, *,
                     margin: float = 30.0, floor: float = 30.0) -> float:
    """How long a worker job may wait for room before it goes back to the queue.

    What its arq ``job_timeout`` leaves after its own work (``work_seconds``) and
    a margin, at least ``floor``, and never so long that the wait itself reaches
    the timeout: arq would cancel the job mid-wait. ``job_started`` is a
    ``time.monotonic()`` reading taken when the job began.
    """
    left = job_timeout - (time.monotonic() - job_started)
    return max(0.0, min(left - 2 * margin, max(floor, left - work_seconds - margin)))


class _Default:
    pass


DEFAULT = _Default()


def _resolve_wait(wait) -> Optional[float]:
    return default_wait() if isinstance(wait, _Default) else wait


class ComputeBusy(HTTPException):
    """No room in the compute budget within the wait bound.

    It is the API's existing 429 ``server_busy`` (``src.api.admission``'s
    shape, with Retry-After), so a web request answers it as is. The worker's
    job-level holds catch it and put the job back in the queue.
    """

    def __init__(self, waited_s: float = 0.0, retry_after: int = BUSY_RETRY_AFTER_SECONDS):
        from src.config.public_urls import error_doc_url

        self.waited_s = waited_s
        super().__init__(
            status_code=429,
            headers={"Retry-After": str(max(1, int(retry_after)))},
            detail={
                "code": "server_busy",
                "message": "server is at capacity, retry shortly",
                "doc_url": error_doc_url("server_busy"),
            },
        )


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


class Reservation:
    """Room held in the budget: one slot and ``need_bytes``.

    Held by its owner (the hold, or the thread of a lone ``run_within_budget``)
    and by every executor thread that joined it; given back when the last one
    lets go, whichever thread that is.
    """

    __slots__ = ("budget", "need_bytes", "label", "_refs", "released")

    def __init__(self, budget: "ComputeBudget", need_bytes: int, label: str):
        self.budget = budget
        self.need_bytes = need_bytes
        self.label = label
        self._refs = 1
        self.released = False

    def join(self) -> bool:
        """One more thread holds this room. False when it was already given back."""
        with self.budget._lock:
            if self.released:
                return False
            self._refs += 1
            return True

    def leave(self) -> None:
        """One holder lets go; the last one gives the room back (any thread)."""
        with self.budget._lock:
            if self.released:
                return
            self._refs -= 1
            if self._refs > 0:
                return
            self.released = True
            granted = self.budget._give_back(self)
        self.budget._wake(granted)


class _Waiter:
    __slots__ = ("need_bytes", "label", "loop", "future", "reservation")

    def __init__(self, need_bytes: int, label: str, loop: asyncio.AbstractEventLoop):
        self.need_bytes = need_bytes
        self.label = label
        self.loop = loop
        self.future: asyncio.Future = loop.create_future()
        self.reservation: Optional[Reservation] = None


def _set_done(fut: asyncio.Future) -> None:
    if not fut.done():
        fut.set_result(None)


class ComputeBudget:
    """Memory and compute slots for the CAD work of this process (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.used_bytes = 0
        self.used_slots = 0  # one per reservation: the pieces of work running
        self.capacity_bytes = memory_capacity_bytes()
        self.slots = compute_slots()
        self._queue: deque[_Waiter] = deque()

    # -- all of these run under self._lock ---------------------------------
    def _refresh(self) -> None:
        self.capacity_bytes = memory_capacity_bytes()
        self.slots = compute_slots()

    def _fits(self, need: int) -> bool:
        if self.used_slots >= self.slots:
            return False
        if self.used_slots == 0:
            return True  # alone, anything runs: work bigger than the budget only runs alone
        return self.used_bytes + need <= self.capacity_bytes

    def _grant(self, need: int, label: str) -> Reservation:
        self.used_bytes += need
        self.used_slots += 1
        return Reservation(self, need, label)

    def _admit_waiting(self) -> list[_Waiter]:
        granted = []
        while self._queue and self._fits(self._queue[0].need_bytes):
            w = self._queue.popleft()
            w.reservation = self._grant(w.need_bytes, w.label)
            granted.append(w)
        return granted

    def _give_back(self, res: Reservation) -> list[_Waiter]:
        self.used_bytes -= res.need_bytes
        self.used_slots -= 1
        return self._admit_waiting()

    # -- outside the lock ----------------------------------------------------
    def _wake(self, granted: list[_Waiter]) -> None:
        for w in granted:
            try:
                w.loop.call_soon_threadsafe(_set_done, w.future)
            except RuntimeError:  # its loop is gone: nobody will use this room
                w.reservation.leave()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "used_bytes": self.used_bytes, "capacity_bytes": self.capacity_bytes,
                "used_slots": self.used_slots, "slots": self.slots,
                "running": self.used_slots, "waiting": len(self._queue),
            }

    async def reserve(self, need_bytes: int, *, wait: Optional[float], label: str = "cad") -> Reservation:
        """Room for ``need_bytes`` and a slot; waits up to ``wait`` seconds (None: no limit).

        Raises :class:`ComputeBusy` when the wait passes with no room.
        """
        need = max(0, int(need_bytes))
        loop = asyncio.get_running_loop()
        with self._lock:
            self._refresh()
            if not self._queue and self._fits(need):
                return self._grant(need, label)
            waiter = _Waiter(need, label, loop)
            self._queue.append(waiter)
            granted = self._admit_waiting()  # the limits may have just grown
        self._wake(granted)
        t0 = time.monotonic()
        try:
            if wait is None:
                await asyncio.shield(waiter.future)
            else:
                await asyncio.wait_for(asyncio.shield(waiter.future), max(0.0, wait))
        except asyncio.TimeoutError:
            with self._lock:
                res = waiter.reservation
                if res is None:
                    self._queue.remove(waiter)
                    granted = self._admit_waiting()  # a big head leaving can let others in
                else:
                    granted = []
            self._wake(granted)
            if res is None:
                waited = time.monotonic() - t0
                slog.info("compute_busy", label=label, need_mb=round(need / MB), waited_s=round(waited, 1),
                          **self._state_fields())
                raise ComputeBusy(waited)
        except BaseException:
            with self._lock:
                res = waiter.reservation
                if res is None:
                    self._queue.remove(waiter)
                    granted = self._admit_waiting()
                else:
                    granted = []
            self._wake(granted)
            if res is not None:
                res.leave()
            raise
        waited = time.monotonic() - t0
        if waited >= 1.0:
            slog.info("compute_waited", label=label, need_mb=round(need / MB), waited_s=round(waited, 1),
                      **self._state_fields())
        return waiter.reservation

    def _state_fields(self) -> dict[str, Any]:
        s = self.snapshot()
        return {"used_mb": round(s["used_bytes"] / MB), "capacity_mb": round(s["capacity_bytes"] / MB),
                "running": s["running"], "slots": s["slots"], "waiting": s["waiting"]}


_BUDGET: Optional[ComputeBudget] = None
_BUDGET_LOCK = threading.Lock()


def budget() -> ComputeBudget:
    """This process's budget (created on first use)."""
    global _BUDGET
    if _BUDGET is None:
        with _BUDGET_LOCK:
            if _BUDGET is None:
                _BUDGET = ComputeBudget()
    return _BUDGET


def reset_for_tests() -> None:
    """A fresh, empty budget, with the web process's waits (tests only)."""
    global _BUDGET, _WAIT_WITHOUT_LIMIT
    with _BUDGET_LOCK:
        _BUDGET = ComputeBudget()
    _WAIT_WITHOUT_LIMIT = False


# ---------------------------------------------------------------------------
# Holds and executor calls
# ---------------------------------------------------------------------------

_CURRENT: contextvars.ContextVar[Optional[Reservation]] = contextvars.ContextVar(
    "cadverify_compute_reservation", default=None
)


def current() -> Optional[Reservation]:
    res = _CURRENT.get()
    return res if res is not None and not res.released else None


def need_for_data(data: bytes, filename: str) -> int:
    """The memory one check of this file needs (the measured model, with its headroom)."""
    from src.services.stored_check_service import estimate_memory_bytes_for_data

    need, _basis = estimate_memory_bytes_for_data(data or b"", filename or "")
    return need


def need_for_path(path: str, filename: str) -> int:
    from src.services.stored_check_service import estimate_memory_bytes

    try:
        need, _basis = estimate_memory_bytes(path, filename)
    except OSError:
        need = default_need()
    return need


def default_need() -> int:
    """The model's smallest check (a tiny STEP), for work with no file to size."""
    from src.services.stored_check_service import MEMORY_HEADROOM, STEP_MEMORY_POINTS

    return int(STEP_MEMORY_POINTS[0][1] * MEMORY_HEADROOM * MB)


@asynccontextmanager
async def hold(need_bytes: int, *, wait=DEFAULT, label: str = "cad") -> AsyncIterator[Reservation]:
    """Hold room for a piece of work made of several steps.

    Inside another hold this joins it (no second reservation). The room comes
    back when the block ends and every executor thread started in it has ended.
    """
    outer = current()
    if outer is not None and outer.join():
        try:
            yield outer
        finally:
            outer.leave()
        return
    res = await budget().reserve(need_bytes, wait=_resolve_wait(wait), label=label)
    token = _CURRENT.set(res)
    try:
        yield res
    finally:
        try:
            _CURRENT.reset(token)
        except ValueError:  # finalized in another context
            _CURRENT.set(None)
        res.leave()


def hold_for_data(data: bytes, filename: str, *, wait=DEFAULT, label: str = "cad"):
    """``hold`` sized by the memory model for this file. Inside a hold it joins it and sizes nothing."""
    need = 0 if current() is not None else need_for_data(data, filename)
    return hold(need, wait=wait, label=label)


class DeferredHold:
    """A hold taken part way through a call (``take``), at the point real work starts.

    For a function that may finish without computing (a cached analysis): the
    room is reserved only when it reaches the work, and given back when the
    ``deferred_hold`` block around the call ends.
    """

    def __init__(self, label: str, wait) -> None:
        self.label = label
        self.wait = wait
        self.reservation: Optional[Reservation] = None
        self._token: Optional[contextvars.Token] = None

    async def take(self, need_bytes: int) -> Reservation:
        if self.reservation is not None:
            return self.reservation
        outer = current()
        if outer is not None and outer.join():
            self.reservation = outer
            return outer
        res = await budget().reserve(need_bytes, wait=_resolve_wait(self.wait), label=self.label)
        self.reservation = res
        # Set in the caller's task, so every step after this point joins it.
        self._token = _CURRENT.set(res)
        return res

    async def take_for_data(self, data: bytes, filename: str) -> Reservation:
        return await self.take(0 if current() is not None else need_for_data(data, filename))


@asynccontextmanager
async def deferred_hold(*, wait=DEFAULT, label: str = "cad") -> AsyncIterator[DeferredHold]:
    room = DeferredHold(label, wait)
    try:
        yield room
    finally:
        if room._token is not None:
            try:
                _CURRENT.reset(room._token)
            except ValueError:
                _CURRENT.set(None)
        if room.reservation is not None:
            room.reservation.leave()


class _Thread:
    """One executor call under a reservation: it leaves the reservation when the call ends."""

    __slots__ = ("res", "label", "_lock", "_claimed", "abandoned_at", "started_at")

    def __init__(self, res: Reservation, label: str):
        self.res = res
        self.label = label
        self._lock = threading.Lock()
        self._claimed = False
        self.abandoned_at: Optional[float] = None
        self.started_at: Optional[float] = None

    def _claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True

    def run(self, ctx: contextvars.Context, fn: Callable, args: tuple, kwargs: dict):
        if not self._claim():  # cancelled before it started; the room is already back
            return None
        self.started_at = time.monotonic()
        outcome = "error"
        try:
            result = ctx.run(fn, *args, **kwargs)
            outcome = "ok"
            return result
        finally:
            self.res.leave()
            abandoned = self.abandoned_at
            if abandoned is not None:
                now = time.monotonic()
                slog.info(
                    "abandoned_compute_finished",
                    label=self.label,
                    outcome=outcome,
                    duration_ms=round((now - self.started_at) * 1000, 1),
                    after_abandoned_ms=round((now - abandoned) * 1000, 1),
                    held_mb=round(self.res.need_bytes / MB),
                )

    def settle(self, fut: asyncio.Future) -> None:
        """Done callback: a call cancelled before its thread started gives its room back."""
        if fut.cancelled():
            if self._claim():
                self.res.leave()
            return
        fut.exception()  # retrieved: an abandoned call's error is logged by its thread, not as "never retrieved"


async def run_within_budget(
    fn: Callable,
    *args,
    need_bytes: Optional[int] = None,
    timeout: Optional[float] = None,
    wait=DEFAULT,
    label: Optional[str] = None,
    **kwargs,
):
    """reserve -> ``run_in_executor`` -> ``wait_for(shield(fut), timeout)``.

    Joins the current hold, or reserves ``need_bytes`` (default: the model's
    smallest check) when there is none; waiting for room doesn't count toward
    ``timeout``. On a timeout (``asyncio.TimeoutError``, as ``wait_for`` raises)
    or a cancellation the thread runs on and keeps the room until it returns;
    ``abandoned_compute_finished`` is logged then. The thread runs in a copy of
    the caller's context, as ``asyncio.to_thread`` does.
    """
    label = label or getattr(fn, "__name__", "cad")
    loop = asyncio.get_running_loop()
    res = current()
    if res is None or not res.join():
        res = await budget().reserve(default_need() if need_bytes is None else need_bytes,
                                     wait=_resolve_wait(wait), label=label)
    call = _Thread(res, label)
    ctx = contextvars.copy_context()
    try:
        fut = loop.run_in_executor(None, call.run, ctx, fn, args, kwargs)
    except BaseException:
        if call._claim():
            res.leave()
        raise
    fut.add_done_callback(call.settle)
    try:
        if timeout is None:
            return await asyncio.shield(fut)
        return await asyncio.wait_for(asyncio.shield(fut), timeout)
    except BaseException as exc:
        if not fut.done():
            call.abandoned_at = time.monotonic()
            slog.info("compute_abandoned", label=label, reason=type(exc).__name__,
                      timeout_s=None if timeout is None else round(timeout, 1),
                      held_mb=round(res.need_bytes / MB))
        raise
