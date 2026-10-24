"""One compute budget per process: the CAD work in flight fits in its memory.

Every CPU-heavy CAD step (a parse, the DFM analysis, a price, a repair, a
preview) reserves room here before it starts, in two dimensions:

  - memory: the piece of work's estimate, from the measured per-check model
    (``stored_check_service.estimate_memory_bytes_for_data``), re-sized from
    the mesh once a STEP or IGES file is tessellated (``size_to_mesh``);
  - a compute slot: one per piece of work, ``COMPUTE_SLOTS`` in all
    (default ``max(2, available_cpus())``: the container's CPU quota when it
    has one, else the CPUs this process may run on).

The memory capacity is ``COMPUTE_MEMORY_BUDGET_MB`` when set, otherwise
``COMPUTE_MEMORY_FRACTION`` (0.7) of the machine's (or container's) memory.

One check, one reservation. The app checks a part with several calls on the
same file at once (the assembly probe, the preview mesh, ``/validate``, then
``/validate/cost``). Admission (``src.api.admission``) names the check (the
organization, the person and the file's SHA-256) for every call it admits
(``check_scope``), and the calls of one check share one reservation: one slot,
sized by the largest single need among them. A second copy of the same heavy
work on the same file (two analyses at once) adds its own need, so parallel
calls can never hide work. The room comes back when the last of them ends.

A reservation is held until the work has really ended. ``asyncio.wait_for``
can stop waiting for an executor thread, but it can't stop the thread: a part
that ran past its time limit keeps computing and keeps its arrays. So the
release happens in the executor thread's own ``finally``, when the computation
returns or raises, never when an await is cancelled. A retry of a timed-out
part therefore waits for room while its abandoned first attempt still runs.

Work bigger than the whole budget runs only when nothing else is running.
Waiters are served in order, so a big part is never starved by a stream of
small ones: first work that is growing (a check whose mesh turned out bigger
than its provisional room), then interactive work (every web request, and the
worker's design generation, big-file checks and kept-part jobs), then batch and
catalog items, each first come, first served. Batch work never takes the last
free slot, so interactive work always finds one. A check that timed out
waiting, or whose last call just ended, keeps its place in line for
``TICKET_SECONDS`` (60): the same person retrying the same file goes ahead of
newcomers instead of behind them. The state is process-wide and thread-safe (a
release happens on an executor thread); it is never tied to one event loop.

Use:

    async with hold(need_bytes, wait=..., label="catalog part"):
        ...  # several steps; each run_within_budget() call inside joins this hold

    await run_within_budget(fn, *args, need_bytes=..., timeout=..., label=...)

A hold inside a hold joins the outer one (one reservation for the whole job:
a catalog part's analysis and price, a request's parse and analysis). Each
``run_within_budget`` thread joins the current hold, or reserves on its own when
there is none. The outer hold's room comes back when the last of its threads ends.

Waiting: in a web process a hold waits at most ``COMPUTE_WAIT_SECONDS`` (30) and
then raises :class:`ComputeBusy`, the API's existing 429 ``server_busy`` with
Retry-After. The worker (``worker_process()`` at startup) waits without limit by
default; its job-level holds pass their own bound and put the job back in the
queue when it passes (``src.jobs.batch_tasks``, ``src.jobs.stored_check_tasks``).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import math
import os
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Callable, Iterator, Optional, TypeVar, cast

import structlog
from fastapi import HTTPException

logger = logging.getLogger("cadverify.compute_budget")
slog = structlog.get_logger("cadverify.compute_budget")

_T = TypeVar("_T")

MB = 1024 * 1024
DEFAULT_MEMORY_FRACTION = 0.7
# The app doesn't retry a busy answer by itself everywhere yet: a request waits
# this long for room before it answers 429 (the capacity test, round 14).
DEFAULT_WAIT_SECONDS = 30.0
BUSY_RETRY_AFTER_SECONDS = 5
# How long a check keeps its place in line after it timed out waiting, or after
# its last call ended (the same person and file, back within this time).
TICKET_SECONDS = 60.0

# Who goes first when several wait: growing work, then interactive, then batch.
GROW, INTERACTIVE, BATCH = 0, 1, 2


def _clock() -> float:
    """The clock places in line are kept by (its own name, so a test can move it)."""
    return time.monotonic()

# Work that only reads a mesh it shares with its check (a preview, the assembly
# probe's model): beside the check's analysis it adds nothing to the largest need.
LIGHT_WORK = frozenset({"preview mesh", "stored preview", "assembly json", "assembly glb"})


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


# The process may use at most this share of the machine's memory in all: its own
# baseline (the interpreter, the parse pool's warm workers, memory its heap kept
# from earlier work) plus the work in flight. The budget gives no more than what
# that leaves above the baseline: the resident memory not held by reservations,
# read at every reservation (at least what was resident when last idle).
MACHINE_SHARE = 0.9
# Freed heap goes back to the OS (glibc malloc_trim) after heavy work, at most this often.
TRIM_EVERY_SECONDS = 2.0


def _tree_rss_bytes() -> Optional[int]:
    """Resident memory of this process and its children (the parse pool's workers)."""
    def rss(pid) -> int:
        try:
            with open(f"/proc/{pid}/status") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) * 1024
        except OSError:
            pass
        return 0

    me = os.getpid()
    total = rss(me)
    if not total:
        return None
    try:
        for task in os.listdir(f"/proc/{me}/task"):
            try:
                with open(f"/proc/{me}/task/{task}/children") as fh:
                    total += sum(rss(int(pid)) for pid in fh.read().split())
            except OSError:
                continue
    except OSError:
        pass
    return total


_LIBC_TRIM = None


def give_memory_back() -> None:
    """Hand freed heap back to the OS (glibc ``malloc_trim(0)``; a no-op elsewhere)."""
    global _LIBC_TRIM
    if _LIBC_TRIM is None:
        try:
            import ctypes

            _LIBC_TRIM = ctypes.CDLL("libc.so.6").malloc_trim
        except (OSError, AttributeError):
            _LIBC_TRIM = False
    if _LIBC_TRIM:
        try:
            _LIBC_TRIM(0)
        except Exception:
            pass


CGROUP_CPU_FILES = ("/sys/fs/cgroup/cpu.max",)
CGROUP_V1_CPU_FILES = ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _cgroup_cpu_quota() -> Optional[float]:
    """The container's CPU quota in CPUs (cgroup v2 ``cpu.max``, else v1), None when unlimited."""
    for path in CGROUP_CPU_FILES:
        try:
            parts = open(path).read().split()
        except OSError:
            continue
        if len(parts) >= 1 and parts[0] != "max":
            try:
                quota = float(parts[0])
                period = float(parts[1]) if len(parts) > 1 else 100000.0
            except ValueError:
                return None
            return quota / period if quota > 0 and period > 0 else None
        return None
    try:
        quota = float(open(CGROUP_V1_CPU_FILES[0]).read().strip())
        period = float(open(CGROUP_V1_CPU_FILES[1]).read().strip())
    except (OSError, ValueError):
        return None
    return quota / period if quota > 0 and period > 0 else None


def available_cpus() -> int:
    """The CPUs this process can really use: the container's CPU quota when it has one.

    ``os.cpu_count()`` inside a container reports the host's CPUs. This is the
    smallest of the host's count, the CPUs the process may run on (its
    affinity, as ``taskset`` or a cpuset sets it), and the cgroup's CPU quota
    rounded up (``/sys/fs/cgroup/cpu.max``: "200000 100000" is 2 CPUs).
    """
    n = os.cpu_count() or 2
    try:
        n = min(n, len(os.sched_getaffinity(0)) or n)
    except (AttributeError, OSError):
        pass
    quota = _cgroup_cpu_quota()
    if quota:
        n = min(n, max(1, math.ceil(quota - 1e-6)))
    return max(1, n)


def compute_slots() -> int:
    """``COMPUTE_SLOTS``, else ``max(2, available_cpus())``."""
    default = max(2, available_cpus())
    raw = os.getenv("COMPUTE_SLOTS", "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def compute_wait_seconds() -> float:
    """How long a web request waits for room before it answers 429 (``COMPUTE_WAIT_SECONDS``, 30)."""
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


class MeshBusy(ComputeBusy):
    """A part's meshing ran out of wall time while the CPUs were saturated.

    ``parse_pool.ParseBusy``: the part may well mesh once there is room, so a web
    request answers busy (the same 429 ``server_busy``), not "can't be meshed";
    a catalog part is checked again after the rest of its run.
    """


# ---------------------------------------------------------------------------
# Which check, and whose work (context set by admission and by batch items)
# ---------------------------------------------------------------------------

_CHECK_KEY: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("cadverify_compute_check", default=None)
_PRIORITY: contextvars.ContextVar[int] = contextvars.ContextVar("cadverify_compute_priority", default=INTERACTIVE)


def check_key() -> Optional[str]:
    """The check the current request belongs to (set by admission), or None."""
    return _CHECK_KEY.get()


@contextmanager
def check_scope(key: Optional[str]) -> Iterator[None]:
    """Holds taken inside belong to this check: they share one reservation."""
    token = _CHECK_KEY.set(key)
    try:
        yield
    finally:
        try:
            _CHECK_KEY.reset(token)
        except ValueError:  # finalized in another context
            _CHECK_KEY.set(None)


@contextmanager
def batch_work() -> Iterator[None]:
    """Holds taken inside are batch or catalog work: served after interactive work."""
    token = _PRIORITY.set(BATCH)
    try:
        yield
    finally:
        try:
            _PRIORITY.reset(token)
        except ValueError:
            _PRIORITY.set(INTERACTIVE)


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


class Reservation:
    """Room held in the budget: one slot and ``need_bytes``, for one check.

    Shared by the :class:`Hold` of every call of the check (one, for work that
    isn't part of a check). Its size is what they need together: the largest
    single need, or the needs of its heavy holds added, whichever is more.
    Given back when the last hold lets go, whichever thread that is.
    """

    __slots__ = ("budget", "need_bytes", "key", "priority", "seq", "holds", "released")

    def __init__(self, budget: "ComputeBudget", need_bytes: int, key: Optional[str], priority: int, seq: int):
        self.budget = budget
        self.need_bytes = need_bytes
        self.key = key
        self.priority = priority
        self.seq = seq
        self.holds: list[Hold] = []
        self.released = False

    def target(self, hold: "Optional[Hold]" = None, need: int = 0) -> int:
        """What the holds need together (``hold`` counted at ``need`` instead of its own)."""
        biggest = heavy = 0
        for h in self.holds:
            n = need if h is hold else h.need_bytes
            biggest = max(biggest, n)
            if h.heavy:
                heavy += n
        return max(biggest, heavy)


class Hold:
    """One holder's share of a :class:`Reservation` (what ``current()`` returns).

    Held by its owner (a hold block, or the thread of a lone
    ``run_within_budget``) and by every executor thread that joined it. When the
    last one lets go, its need leaves the reservation (which shrinks, or is
    given back when no other hold shares it).
    """

    __slots__ = ("reservation", "need_bytes", "label", "heavy", "provisional", "_refs", "released")

    def __init__(self, reservation: Reservation, need_bytes: int, label: str):
        self.reservation = reservation
        self.need_bytes = need_bytes
        self.label = label
        self.heavy = label not in LIGHT_WORK
        # Sized before its mesh was known: ``size_to_mesh`` re-sizes it (only it).
        self.provisional = False
        self._refs = 1
        self.released = False

    @property
    def budget(self) -> "ComputeBudget":
        return self.reservation.budget

    def join(self) -> bool:
        """One more thread holds this room. False when it was already given back."""
        with self.budget._lock:
            if self.released:
                return False
            self._refs += 1
            return True

    def leave(self) -> None:
        """One holder lets go; the last one gives this hold's need back (any thread)."""
        budget = self.budget
        with budget._lock:
            if self.released:
                return
            self._refs -= 1
            if self._refs > 0:
                return
            self.released = True
            granted, idle = budget._drop_hold(self)
        budget._wake(granted)
        budget._after_release(idle)


class _Party:
    """One caller waiting on a waiter (several calls of one check wait on one place in line)."""

    __slots__ = ("loop", "future", "need_bytes", "label", "hold")

    def __init__(self, loop: asyncio.AbstractEventLoop, need_bytes: int, label: str):
        self.loop = loop
        self.future: asyncio.Future = loop.create_future()
        self.need_bytes = need_bytes
        self.label = label
        self.hold: Optional[Hold] = None


class _Waiter:
    """A place in line: new room for one check (its parties), or more room for a hold (``grow``)."""

    __slots__ = ("cls", "seq", "key", "parties", "grow_hold", "grow_to", "done")

    def __init__(self, cls: int, seq: int, key: Optional[str], parties: list[_Party], *,
                 grow_hold: Optional[Hold] = None, grow_to: int = 0):
        self.cls = cls
        self.seq = seq
        self.key = key
        self.parties = parties
        self.grow_hold = grow_hold
        self.grow_to = grow_to
        self.done = False

    @property
    def label(self) -> str:
        return self.parties[0].label if self.parties else "cad"

    def need(self) -> int:
        biggest = heavy = 0
        for p in self.parties:
            biggest = max(biggest, p.need_bytes)
            if p.label not in LIGHT_WORK:
                heavy += p.need_bytes
        return max(biggest, heavy)


def _set_done(fut: asyncio.Future) -> None:
    if not fut.done():
        fut.set_result(None)


class ComputeBudget:
    """Memory and compute slots for the CAD work of this process (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.used_bytes = 0
        self.used_slots = 0  # one per reservation: the pieces of work running
        self.slots = compute_slots()
        self._queue: list[_Waiter] = []  # kept in order: (class, seq)
        self._seq = 0
        self._shared: dict[str, Reservation] = {}  # check key -> its room, while held
        self._pending: dict[str, _Waiter] = {}  # check key -> its place in line, while waiting
        self._tickets: dict[str, tuple[int, float]] = {}  # check key -> (seq, until)
        # The process tree's resident memory when it was last idle (no work in flight).
        self.idle_baseline_bytes: Optional[int] = _tree_rss_bytes()
        self._last_trim = 0.0
        self.capacity_bytes = self._capacity()

    def _capacity(self, tree_rss: Optional[int] = None) -> int:
        """The configured capacity, but no more than the machine's share left above the baseline.

        The baseline is what the process holds that no reservation explains:
        its resident memory now less the room reserved (a lower bound, as work
        in flight hasn't reached its peak yet), and at least what was resident
        when it was last idle.
        """
        configured = memory_capacity_bytes()
        machine = _machine_memory_bytes()
        baseline = self.idle_baseline_bytes or 0
        if tree_rss:
            baseline = max(baseline, tree_rss - self.used_bytes)
        if machine and baseline:
            return max(0, min(configured, int(machine * MACHINE_SHARE) - baseline))
        return configured

    # -- all of these run under self._lock ---------------------------------
    def _refresh(self, tree_rss: Optional[int] = None) -> None:
        self.capacity_bytes = self._capacity(tree_rss)
        self.slots = compute_slots()

    def _next_seq(self, key: Optional[str]) -> int:
        """The place in line: a returning check's own (its ticket), else the next one."""
        if key is not None:
            ticket = self._tickets.get(key)
            if ticket is not None:
                seq, until = ticket
                if until >= _clock():
                    return seq
                del self._tickets[key]
        self._seq += 1
        return self._seq

    def _write_ticket(self, key: str, seq: int) -> None:
        now = _clock()
        if len(self._tickets) > 4096:
            self._tickets = {k: t for k, t in self._tickets.items() if t[1] >= now}
        self._tickets[key] = (seq, now + TICKET_SECONDS)

    def _enqueue(self, w: _Waiter) -> None:
        self._queue.append(w)
        self._queue.sort(key=lambda x: (x.cls, x.seq))

    def _fits(self, w: _Waiter) -> bool:
        if w.grow_hold is not None:
            hold = w.grow_hold
            res = hold.reservation
            if res.released or hold.released:
                return True  # nothing left to grow: let it go
            delta = res.target(hold, w.grow_to) - res.need_bytes
            if delta <= 0 or self.used_slots <= 1:
                return True  # alone, anything runs: work bigger than the budget only runs alone
            return self.used_bytes + delta <= self.capacity_bytes
        if self.used_slots >= self.slots:
            return False
        if w.cls == BATCH and self.slots >= 2 and self.used_slots >= self.slots - 1:
            return False  # batch work leaves the last slot to interactive work
        if self.used_slots == 0:
            return True  # alone, anything runs: work bigger than the budget only runs alone
        return self.used_bytes + w.need() <= self.capacity_bytes

    def _apply_target(self, res: Reservation) -> None:
        new = res.target()
        self.used_bytes += new - res.need_bytes
        res.need_bytes = new

    def _grant(self, w: _Waiter) -> None:
        w.done = True
        if w.grow_hold is not None:
            hold = w.grow_hold
            if not hold.released and not hold.reservation.released:
                hold.need_bytes = w.grow_to
                self._apply_target(hold.reservation)
            for p in w.parties:
                p.hold = hold
            return
        need = w.need()
        res = Reservation(self, need, w.key, w.cls, w.seq)
        self.used_bytes += need
        self.used_slots += 1
        for p in w.parties:
            p.hold = Hold(res, p.need_bytes, p.label)
            res.holds.append(p.hold)
        if w.key is not None:
            self._shared[w.key] = res
            if self._pending.get(w.key) is w:
                del self._pending[w.key]

    def _admit_waiting(self) -> list[_Waiter]:
        granted = []
        while self._queue and self._fits(self._queue[0]):
            w = self._queue.pop(0)
            self._grant(w)
            granted.append(w)
        return granted

    def _drop_hold(self, hold: Hold) -> tuple[list[_Waiter], bool]:
        res = hold.reservation
        try:
            res.holds.remove(hold)
        except ValueError:
            pass
        if not res.holds:
            res.released = True
            self.used_bytes -= res.need_bytes
            self.used_slots -= 1
            if res.key is not None:
                if self._shared.get(res.key) is res:
                    del self._shared[res.key]
                self._write_ticket(res.key, res.seq)
        else:
            self._apply_target(res)  # its need left: the check's room shrinks to the rest
        return self._admit_waiting(), self.used_slots == 0

    def _leave_line(self, w: _Waiter, party: _Party) -> list[_Waiter]:
        """A party stops waiting: the waiter leaves the line when none is left."""
        if party in w.parties:
            w.parties.remove(party)
        if w.parties or w.done:
            return self._admit_waiting()  # its need may have dropped
        if w in self._queue:
            self._queue.remove(w)
        if w.key is not None and w.grow_hold is None:
            if self._pending.get(w.key) is w:
                del self._pending[w.key]
            self._write_ticket(w.key, w.seq)  # the same person and file, back soon: same place
        return self._admit_waiting()  # a big head leaving can let others in

    # -- outside the lock ----------------------------------------------------
    def _after_release(self, idle: bool) -> None:
        """After heavy work: give freed heap back, and when idle, measure the baseline.

        Never on an event loop's thread (a trim of a big heap takes a while):
        there it is handed to the loop's executor.
        """
        now = time.monotonic()
        if not idle and now - self._last_trim < TRIM_EVERY_SECONDS:
            return
        self._last_trim = now
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            try:
                loop.run_in_executor(None, self._trim_and_measure, idle)
            except RuntimeError:
                pass
            return
        self._trim_and_measure(idle)

    def _trim_and_measure(self, idle: bool) -> None:
        give_memory_back()
        if idle:
            rss = _tree_rss_bytes()
            with self._lock:
                if self.used_slots == 0 and rss:
                    self.idle_baseline_bytes = rss

    def _wake(self, granted: list[_Waiter]) -> None:
        for w in granted:
            for p in list(w.parties):
                try:
                    p.loop.call_soon_threadsafe(_set_done, p.future)
                except RuntimeError:  # its loop is gone: nobody will use this room
                    if p.hold is not None and w.grow_hold is None:
                        p.hold.leave()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "used_bytes": self.used_bytes, "capacity_bytes": self.capacity_bytes,
                "used_slots": self.used_slots, "slots": self.slots,
                "running": self.used_slots, "waiting": len(self._queue),
                "idle_baseline_bytes": self.idle_baseline_bytes,
                "checks": len(self._shared),
            }

    async def _wait_for(self, w: _Waiter, party: _Party, wait: Optional[float], label: str, need: int,
                        t0: float) -> Hold:
        """Wait on ``party`` (in line in ``w``) up to ``wait`` seconds; ComputeBusy when it passes."""
        try:
            if wait is None:
                await asyncio.shield(party.future)
            else:
                await asyncio.wait_for(asyncio.shield(party.future), max(0.0, wait))
        except asyncio.TimeoutError:
            with self._lock:
                got = party.hold
                granted = [] if got is not None else self._leave_line(w, party)
            self._wake(granted)
            if got is None:
                waited = time.monotonic() - t0
                slog.info("compute_busy", label=label, need_mb=round(need / MB), waited_s=round(waited, 1),
                          grow=w.grow_hold is not None, **self._state_fields())
                raise ComputeBusy(waited)
        except BaseException:
            with self._lock:
                got = party.hold
                granted = [] if got is not None else self._leave_line(w, party)
            self._wake(granted)
            if got is not None and w.grow_hold is None:
                got.leave()
            raise
        waited = time.monotonic() - t0
        if waited >= 1.0:
            slog.info("compute_waited", label=label, need_mb=round(need / MB), waited_s=round(waited, 1),
                      grow=w.grow_hold is not None, **self._state_fields())
        hold = party.hold
        if hold is None:  # _grant sets the hold before _wake resolves the future
            raise RuntimeError("compute budget: a granted wait has no hold")
        return hold

    async def reserve(self, need_bytes: int, *, wait: Optional[float], label: str = "cad",
                      key: Any = DEFAULT, priority: Optional[int] = None) -> Hold:
        """Room for ``need_bytes`` and a slot; waits up to ``wait`` seconds (None: no limit).

        ``key`` (default: the current check, ``check_scope``) names the check
        this work belongs to: work of the same check shares its room. Raises
        :class:`ComputeBusy` when the wait passes with no room.
        """
        need = max(0, int(need_bytes))
        key = check_key() if isinstance(key, _Default) else key
        cls = _PRIORITY.get() if priority is None else priority
        loop = asyncio.get_running_loop()
        tree_rss = _tree_rss_bytes()  # a few /proc reads, outside the lock
        party: Optional[_Party] = None
        w: Optional[_Waiter] = None
        granted: list[_Waiter] = []
        with self._lock:
            self._refresh(tree_rss)
            shared = self._shared.get(key) if key is not None else None
            if shared is not None and not shared.released:
                # Another call of this check holds its room: share it.
                joined = Hold(shared, 0, label)
                shared.holds.append(joined)
            else:
                joined = None
                party = _Party(loop, need, label)
                w = self._pending.get(key) if key is not None else None
                if w is not None and not w.done:
                    w.parties.append(party)  # another call of this check is in line: wait with it
                else:
                    w = _Waiter(cls, self._next_seq(key), key, [party])
                    self._enqueue(w)
                    if key is not None:
                        self._pending[key] = w
                granted = self._admit_waiting()  # the limits may have just grown
        if joined is not None:
            try:
                await self.resize(joined, need, wait=wait)
            except BaseException:
                joined.leave()
                raise
            return joined
        if party is None or w is None:  # not joined: the branch above put this call in line
            raise RuntimeError("compute budget: reserve() put no call in line")
        self._wake(granted)
        if party.hold is not None:
            return party.hold
        return await self._wait_for(w, party, wait, label, need, time.monotonic())

    async def resize(self, hold: Hold, need_bytes: int, *, wait: Optional[float]) -> None:
        """Set ``hold``'s need to ``need_bytes``: less is given back now; more waits for room.

        More waits up to ``wait`` seconds, ahead of every new reservation, and
        never past the capacity while other work holds room (alone, anything
        runs). When it can't grow in time it raises :class:`ComputeBusy` and
        the hold keeps its old size; the caller ends its hold (and answers busy).
        """
        need = max(0, int(need_bytes))
        loop = asyncio.get_running_loop()
        tree_rss = _tree_rss_bytes()
        with self._lock:
            self._refresh(tree_rss)
            res = hold.reservation
            if res.released or hold.released:
                return
            if res.target(hold, need) <= res.need_bytes:
                hold.need_bytes = need
                self._apply_target(res)
                granted = self._admit_waiting()  # the room it gave back may let others in
                party = None
                w = None
            else:
                party = _Party(loop, need, hold.label)
                w = _Waiter(GROW, res.seq, res.key, [party], grow_hold=hold, grow_to=need)
                self._enqueue(w)
                granted = self._admit_waiting()
        self._wake(granted)
        if party is None or w is None or party.hold is not None:  # party and w are set together
            return
        await self._wait_for(w, party, wait, hold.label, need, time.monotonic())

    def _state_fields(self) -> dict[str, Any]:
        s = self.snapshot()
        return {"used_mb": round(s["used_bytes"] / MB), "capacity_mb": round(s["capacity_bytes"] / MB),
                "baseline_mb": round((s["idle_baseline_bytes"] or 0) / MB),
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
# What a piece of work needs
# ---------------------------------------------------------------------------


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


# A STEP or IGES file while it is parsed, before its triangle count is known.
# The parse worker of the catalog's small parts (28-330 KB, 1-30 bodies) grew by
# 86-370 MB above its warm size (the most: IGES open shells that try several
# meshing strategies); the main process only receives the mesh.
# docs/BIG_FILES.md, "The compute budget: sized to the mesh".
PARSE_MEMORY_MB = 400.0
# Up to this size the file model is the 820 MB face-budget floor; above it the
# model follows measured assemblies by file size, and the parse reserves that.
PARSE_SIZED_UP_TO_MB = 1.52
# (file MB, MB added) for repeated-bracket STEP assemblies of 1-250 bodies: the
# measured file-size curve before the 820 MB floor (docs/BIG_FILES.md). After
# tessellation a multi-body file needs at least this: its OpenCASCADE model and
# bodies cost more than their triangles alone.
ASSEMBLY_MEMORY_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 270.0), (0.036, 275.0), (1.16, 745.0), (4.92, 1531.0), (10.07, 2396.0),
)


def _format(filename: str) -> str:
    from src.services.stored_check_service import _KIND

    return _KIND.get(os.path.splitext((filename or "").lower())[1], "step")


def parse_need_for_data(data: bytes, filename: str) -> int:
    """The provisional room for a check whose mesh isn't known yet (``size_to_mesh`` re-sizes it).

    A STEP or IGES file up to 1.52 MB reserves its parse (400 MB, with the
    headroom), not the 820 MB its mesh could reach at the face budget; any
    other file reserves the file model, as before.
    """
    from src.services.stored_check_service import MEMORY_HEADROOM

    full = need_for_data(data, filename)
    if _format(filename) in ("step", "iges") and len(data or b"") <= PARSE_SIZED_UP_TO_MB * MB:
        return min(full, int(PARSE_MEMORY_MB * MEMORY_HEADROOM * MB))
    return full


def need_for_mesh(faces: int, size_bytes: int, filename: str) -> int:
    """The memory a check needs once its mesh is known (with the model's headroom).

    Any format is sized by its triangle count on the STL curve
    (``STL_MEMORY_POINTS``): every STEP and IGES part measured in the catalog
    (45-190k faces, one body or 30) needed less than an STL of the same count,
    and at the mesher's 250,000-face budget the curve gives the 820 MB the file
    model reserves for every small STEP. A STEP or IGES file needs at least
    what the measured assemblies of its file size needed
    (``ASSEMBLY_MEMORY_POINTS``), for its OpenCASCADE model and its bodies.
    """
    from src.services.stored_check_service import MEMORY_HEADROOM, STL_MEMORY_POINTS, _interp

    need_mb = _interp(STL_MEMORY_POINTS, max(0, int(faces)))
    if _format(filename) in ("step", "iges"):
        need_mb = max(need_mb, _interp(ASSEMBLY_MEMORY_POINTS, max(0, int(size_bytes)) / MB))
    return int(need_mb * MEMORY_HEADROOM * MB)


# ---------------------------------------------------------------------------
# Holds and executor calls
# ---------------------------------------------------------------------------

_CURRENT: contextvars.ContextVar[Optional[Hold]] = contextvars.ContextVar(
    "cadverify_compute_reservation", default=None
)


def current() -> Optional[Hold]:
    res = _CURRENT.get()
    return res if res is not None and not res.released else None


@asynccontextmanager
async def hold(need_bytes: int, *, wait=DEFAULT, label: str = "cad", provisional: bool = False) -> AsyncIterator[Hold]:
    """Hold room for a piece of work made of several steps.

    Inside another hold this joins it (no second reservation). Within a check
    (``check_scope``) it shares the check's room. The room comes back when the
    block ends and every executor thread started in it has ended.
    ``provisional``: sized before the mesh is known; ``size_to_mesh`` re-sizes it.
    """
    outer = current()
    if outer is not None and outer.join():
        try:
            yield outer
        finally:
            outer.leave()
        return
    res = await budget().reserve(need_bytes, wait=_resolve_wait(wait), label=label)
    res.provisional = provisional
    token = _CURRENT.set(res)
    try:
        yield res
    finally:
        try:
            _CURRENT.reset(token)
        except ValueError:  # finalized in another context
            _CURRENT.set(None)
        res.leave()


def hold_for_data(data: bytes, filename: str, *, wait=DEFAULT, label: str = "cad", provisional: bool = False):
    """``hold`` sized by the memory model for this file. Inside a hold it joins it and sizes nothing.

    ``provisional``: the caller re-sizes the hold from the mesh (``size_to_mesh``)
    once it has one, or only parses; a small STEP or IGES reserves its parse.
    """
    if current() is not None:
        need = 0
    else:
        need = parse_need_for_data(data, filename) if provisional else need_for_data(data, filename)
    return hold(need, wait=wait, label=label, provisional=provisional)


async def size_to_mesh(mesh: Any, data: Any, filename: str, *, wait=DEFAULT) -> None:
    """Re-size the current hold to what its mesh needs (``need_for_mesh``).

    ``mesh`` is a mesh (its faces are counted) or a triangle count; ``data`` the
    file's bytes or its size. Less is given back at once. More waits for room
    (up to the web's ``COMPUTE_WAIT_SECONDS``), ahead of new work, and never past
    the capacity while other work holds room: when it can't grow in time this
    raises :class:`ComputeBusy` (429 ``server_busy``; nothing was charged).
    No-op outside a hold, and for a hold sized by its file (``provisional``
    not set: a catalog part's or a big file's whole job keeps its own size).
    """
    h = current()
    if h is None or not h.provisional:
        return
    if isinstance(mesh, int):
        faces = mesh
    else:
        try:
            faces = len(mesh.faces)
        except Exception:
            return
    size = data if isinstance(data, int) else len(data or b"")
    need = need_for_mesh(faces, size, filename)
    await budget().resize(h, need, wait=_resolve_wait(wait))


class DeferredHold:
    """A hold taken part way through a call (``take``), at the point real work starts.

    For a function that may finish without computing (a cached analysis): the
    room is reserved only when it reaches the work, and given back when the
    ``deferred_hold`` block around the call ends.
    """

    def __init__(self, label: str, wait) -> None:
        self.label = label
        self.wait = wait
        self.reservation: Optional[Hold] = None
        self._token: Optional[contextvars.Token] = None

    async def take(self, need_bytes: int, *, provisional: bool = False) -> Hold:
        if self.reservation is not None:
            return self.reservation
        outer = current()
        if outer is not None and outer.join():
            self.reservation = outer
            return outer
        res = await budget().reserve(need_bytes, wait=_resolve_wait(self.wait), label=self.label)
        res.provisional = provisional
        self.reservation = res
        # Set in the caller's task, so every step after this point joins it.
        self._token = _CURRENT.set(res)
        return res

    async def take_for_data(self, data: bytes, filename: str, *, provisional: bool = False) -> Hold:
        if current() is not None:
            need = 0
        else:
            need = parse_need_for_data(data, filename) if provisional else need_for_data(data, filename)
        return await self.take(need, provisional=provisional)


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
    """One executor call under a hold: it leaves the hold when the call ends."""

    __slots__ = ("res", "label", "_lock", "_claimed", "abandoned_at", "started_at")

    def __init__(self, res: Hold, label: str):
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
                    held_mb=round(self.res.reservation.need_bytes / MB),
                )

    def settle(self, fut: asyncio.Future) -> None:
        """Done callback: a call cancelled before its thread started gives its room back."""
        if fut.cancelled():
            if self._claim():
                self.res.leave()
            return
        fut.exception()  # retrieved: an abandoned call's error is logged by its thread, not as "never retrieved"


async def run_within_budget(
    fn: Callable[..., _T],
    *args,
    need_bytes: Optional[int] = None,
    timeout: Optional[float] = None,
    wait=DEFAULT,
    label: Optional[str] = None,
    **kwargs,
) -> _T:
    """reserve -> ``run_in_executor`` -> ``wait_for(shield(fut), timeout)``.

    Joins the current hold, or reserves ``need_bytes`` (default: the model's
    smallest check) when there is none; waiting for room doesn't count toward
    ``timeout``. On a timeout (``asyncio.TimeoutError``, as ``wait_for`` raises)
    or a cancellation the thread runs on and keeps the room until it returns;
    ``abandoned_compute_finished`` is logged then. The thread runs in a copy of
    the caller's context, as ``asyncio.to_thread`` does.
    """
    label = label or cast(str, getattr(fn, "__name__", "cad"))
    loop = asyncio.get_running_loop()
    res = current()
    if res is None or not res.join():
        res = await budget().reserve(default_need() if need_bytes is None else need_bytes,
                                     wait=_resolve_wait(wait), label=label)
    call = _Thread(res, label)
    ctx = contextvars.copy_context()
    try:
        # call.run gives None only when the future was cancelled before it started,
        # so a result that is awaited here is always fn's.
        fut = cast("asyncio.Future[_T]", loop.run_in_executor(None, call.run, ctx, fn, args, kwargs))
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
                      held_mb=round(res.reservation.need_bytes / MB))
        raise
