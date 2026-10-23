"""Process-pool STEP/IGES tessellation — parallelize distinct parts past the GIL.

gmsh/OCC STEP/IGES tessellation is CPU-bound AND serialized twice in-process:
by the GIL and by ``step_mesher._GMSH_LOCK`` (gmsh has a single process-global,
non-thread-safe context). So N concurrent DISTINCT parts run one-at-a-time in the
default ThreadPoolExecutor. Dispatching the RAW tessellation to a
``ProcessPoolExecutor`` gives each worker its own interpreter AND its own gmsh
context, so distinct parts tessellate truly in parallel.

What lives WHERE (deliberate split):
  * MAIN process (routes.py): suffix check, ``validate_magic`` (the untrusted-
    bytes security gate — we never ship un-validated bytes to a worker), the
    mesh-cache lookup/put + deep-copy-on-hit, and ``enforce_triangle_cap`` (a
    per-REQUEST policy). A warm cache hit never touches the pool.
  * WORKER process (``tessellate`` below): ONLY the raw gmsh/OCC (or STL) parse.
    No cache, no cap, no ``HTTPException`` — it raises plain exceptions that the
    parent maps to the same status codes the route has always returned.

Safety invariants:
  * ``spawn`` context ONLY. Forking a running asyncio process inherits held
    locks / event-loop fds and can deadlock; ``spawn`` starts a clean interpreter.
  * Fail-closed crash recovery: on ``BrokenProcessPool`` (a worker segfaulted on
    adversarial gmsh input) we hard-recycle the shared pool and retry only in a
    fresh, single-use, killable subprocess. Untrusted CAD bytes are never parsed
    in the API process after a worker crash.
  * Only STEP/IGES is dispatched. STL is sub-second; the pickle round-trip would
    cost more than the parse, so the route keeps STL in-thread.

Scope caveat: the pool is PER-PROCESS (per uvicorn worker / replica), exactly
like the mesh cache. Worker startup pays a one-time ``spawn`` import cost on
first use.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import multiprocessing
import os
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout
from concurrent.futures.process import BrokenProcessPool

import trimesh

logger = logging.getLogger("cadverify.parse_pool")

# Upper bound on workers regardless of CPU count — parsing is memory-heavy
# (each gmsh worker holds a full OCC context + mesh), so we cap independently
# of core count. Env override wins over the derived default either way.
_WORKER_CAP = 8

_POOL_LOCK = threading.Lock()
_POOL: ProcessPoolExecutor | None = None
_STOPPING = False
# The futures running or queued on each shared pool (by id), so a retired pool
# is killed only once its other parses are done (``retire_pool``).
_INFLIGHT: dict[int, set] = {}
# How long a retired pool's other parses may run on before it is killed anyway.
RETIRE_GRACE_SEC = 30.0

# ── Per-rung CPU budget (the periodic-surface fix) ──────────────────────────
# gmsh's DEFAULT 2D algorithm (retry-ladder rung 0) grinds for 2+ MINUTES before
# FAILING on a periodic-surface part (e.g. nist_ctc_05), then the fast MeshAdapt
# recovery rung runs — but by then the route's ANALYSIS_TIMEOUT_SEC has already
# fired a 504, so the recovery never reaches the user. mesh.generate is an
# uninterruptible in-thread C call, so the ONLY way to bound a rung is to run it
# in a KILLABLE subprocess and hard-kill it at its cap.
#
# The caps are CPU seconds in the rung's worker process (read from /proc), not
# wall time: on a loaded box a rung's wall time measures the load, and a
# wall-clock cap gave the same part a different strategy and mesh, or a false
# "can't be meshed". Wall time bounds the whole ladder only; running out of it
# first is "busy" (ParseBusy), never a reason to try the next strategy.
#
# We split the route budget across rungs so no single rung can consume it:
#   * rung 0 (shared warm pool): cap = min(RUNG0_FRACTION*budget, RUNG0_CAP_MAX).
#     A normal part meshes here in ~1-5s (far under the cap) => byte-identical,
#     concurrent, no regression. A periodic grind is abandoned at the cap.
#   * recovery rungs (dedicated, killable): share RECOVERY_FRACTION*budget; each
#     runs in its own single-worker spawn executor that is HARD-KILLED on cap.
# The caps sum to < budget so an all-rungs-fail part surfaces the honest 400
# BEFORE the route's total-budget 504.
_RUNG0_FRACTION = 0.4
_RUNG0_CAP_MAX = 25.0
_RECOVERY_FRACTION = 0.5


class _RungTimeout(Exception):
    """A single ladder rung used its CPU cap and was hard-killed (the strategy doesn't converge)."""


class _RungStarved(Exception):
    """A rung ran out of wall time before it used its CPU budget: the box was busy."""

    def __init__(self, idx: int, used: float = 0.0, cap: float = 0.0, *, started: bool = True):
        self.idx, self.used, self.cap, self.started = idx, used, cap, started
        super().__init__(f"rung {idx} " + (
            f"ran out of time with {used:.0f}s of its {cap:.0f}s of CPU" if started and used >= 0.5
            else "never got started"))

    def plain(self) -> str:
        """What the person is told (the route answers busy; this is the job's and the log's text)."""
        if not self.started or self.used < 0.5:
            return "ScaleCAD is busy; this part didn't get started. Try again."
        return "ScaleCAD is busy; this part ran out of time before its meshing finished. Try again."


class ParseBusy(ValueError):
    """The ladder ran out of wall time before a rung had used its CPU budget.

    A rung's cap is CPU time in its parse worker, the part's own work, the same
    idle or loaded: a rung that uses it up doesn't converge, and the ladder moves
    to the next strategy. Wall time only bounds the whole ladder (the route's
    budget). Running out of that first means the worker was starved of CPU, not
    that the part is bad, so the ladder stops there, never advancing because of
    time, and the route answers "busy, try again" (429 ``server_busy``). It is
    still a ValueError for callers that only map those.
    """


class _Clock:
    """The ladder's wall-clock deadline (``loop.time()``); each rung's worker start-up is added to it."""

    __slots__ = ("deadline",)

    def __init__(self, deadline: float):
        self.deadline = deadline


_LADDER_CLOCK: contextvars.ContextVar[_Clock | None] = contextvars.ContextVar("cadverify_ladder_clock", default=None)
# A rung whose worker hasn't begun it this long after it was handed over (a spawn
# and the mesher's imports on a starved box) never got started: busy.
STARTUP_LIMIT_SEC = 60.0
# How long taking a pool slot waits for a fresh pool's workers to warm up.
WARM_WAIT_SEC = 60.0


def ladder_clock(seconds: float):
    """Set the ladder's wall-clock budget for the current task (returns the token to reset)."""
    return _LADDER_CLOCK.set(_Clock(asyncio.get_event_loop().time() + seconds))
# What a rung's worker reports when it starts: its pid and CPU seconds so far.
_REPORT_DIR = os.path.join(tempfile.gettempdir(), f"cadverify-rungs-{os.getpid()}")
_CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _cpu_seconds(pid: int) -> float | None:
    """CPU seconds (user + system) a process has used, from /proc; None when unreadable."""
    try:
        with open(f"/proc/{pid}/stat") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / _CLK_TCK
    except (OSError, IndexError, ValueError):
        return None


def _new_report() -> str:
    os.makedirs(_REPORT_DIR, exist_ok=True)
    return os.path.join(_REPORT_DIR, uuid.uuid4().hex)


def _report_start(path: str) -> None:
    """In a rung's worker: tell the parent which process runs it and its CPU so far,
    so the rung's budget is measured in this worker's CPU time, not wall time."""
    me = os.getpid()
    with open(path + ".tmp", "w") as fh:
        fh.write(f"{me} {_cpu_seconds(me) or 0.0}")
    os.replace(path + ".tmp", path)  # whole, never half-written


def _read_report(path: str) -> tuple[int, float] | None:
    try:
        with open(path) as fh:
            pid, cpu = fh.read().split()
        return int(pid), float(cpu)
    except (OSError, ValueError):
        return None


def _drop_report(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


async def _await_rung(cfut, report: str, idx: int, cpu_cap: float):
    """A rung's result, bounded by ``cpu_cap`` seconds of its worker's CPU and by the ladder's deadline.

    ``_RungTimeout``: the worker used its CPU budget (the strategy doesn't
    converge; the same on any load). ``_RungStarved``: the ladder's wall-clock
    deadline came first (the box was busy). The caller kills the worker either way.
    """
    loop = asyncio.get_event_loop()
    afut = asyncio.wrap_future(cfut)
    afut.add_done_callback(lambda f: f.cancelled() or f.exception())  # retrieved: no "never retrieved"
    clock = _LADDER_CLOCK.get() or _Clock(loop.time() + max(cpu_cap * 3, cpu_cap + 30.0))
    handed_over = loop.time()
    started = None
    used = 0.0
    while True:
        if started is None:
            left = STARTUP_LIMIT_SEC - (loop.time() - handed_over)
        else:
            left = clock.deadline - loop.time()
        done, _ = await asyncio.wait({afut}, timeout=max(0.0, min(0.25, left)))
        if done:
            return afut.result()
        if started is None:
            started = _read_report(report)  # the worker's pid and CPU when it began this rung
            if started is None:
                if loop.time() - handed_over >= STARTUP_LIMIT_SEC:
                    raise _RungStarved(idx, cap=cpu_cap, started=False)
                continue
            # The ladder's wall clock runs only while a rung's worker is on it:
            # its start-up (a spawn and the mesher's imports, slow on a busy
            # box) isn't the part's time.
            clock.deadline += loop.time() - handed_over
        now_cpu = _cpu_seconds(started[0])
        if now_cpu is not None:
            used = now_cpu - started[1]
        if used >= cpu_cap:
            raise _RungTimeout(f"rung {idx} used its {cpu_cap:.0f}s of CPU")
        if loop.time() >= clock.deadline:
            raise _RungStarved(idx, used, cpu_cap)


def _budget_sec() -> float:
    """Total analysis budget to split across rungs (mirrors routes._analysis_
    timeout_sec; the route's outer wait_for enforces the same total as a 504).
    A big file checked on the worker carries its own (src.config.check_limits)."""
    from src.config import check_limits

    larger = check_limits.current()
    if larger is not None:
        return larger.budget_sec
    try:
        return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    except ValueError:
        return 60.0


def _rung_caps(budget: float, n_rungs: int) -> list[float]:
    """Per-rung wall-clock caps. rung 0 gets min(0.4*budget, 25s); the recovery
    rungs evenly share 0.5*budget. Sum < budget so the honest 400 (all rungs
    failed) beats the route's total-budget 504."""
    # A big file's own budget (src.config.check_limits) lifts the fixed rung-0
    # ceiling: a large assembly can need more than 25 s on its first rung.
    from src.config import check_limits

    cap_max = _RUNG0_CAP_MAX if check_limits.current() is None else max(_RUNG0_CAP_MAX, _RUNG0_FRACTION * budget)
    rung0 = min(_RUNG0_FRACTION * budget, cap_max, budget)
    caps = [rung0]
    rest = n_rungs - 1
    if rest > 0:
        recovery_total = min(_RECOVERY_FRACTION * budget, max(0.0, budget - rung0))
        per = recovery_total / rest
        caps.extend([per] * rest)
    return caps


def is_disabled() -> bool:
    """Kill switch. Default DISABLED=0 (pool ENABLED). When set, the route uses
    today's in-thread executor path with byte-identical behavior."""
    return os.getenv("PARSE_PROCESS_POOL_DISABLED", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def worker_count() -> int:
    """min(cpu_count - 1, cap), env-overridable via PARSE_POOL_WORKERS, >= 1.

    cpu_count-1 leaves a core for the event loop / main process so the box stays
    responsive under a parse burst. The CPUs are the container's (its cgroup CPU
    quota, ``compute_budget.available_cpus``), not the host's.
    """
    from src.services.compute_budget import available_cpus

    cpu = available_cpus()
    default = max(1, min(cpu - 1, _WORKER_CAP))
    raw = os.getenv("PARSE_POOL_WORKERS")
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def tessellate(data: bytes, suffix: str) -> trimesh.Trimesh:
    """PURE, picklable, module-level tessellation — the worker entry point.

    Does ONLY the raw parse. NO cache, NO triangle cap, NO HTTPException. Raises
    plain exceptions (``ValueError`` for bad geometry, ``RuntimeError`` if gmsh is
    absent) that the parent maps to the route's usual 400/501. Must stay importable
    at module scope so ``ProcessPoolExecutor`` can pickle it by qualified name.
    """
    suffix = suffix.lower()
    if suffix == ".stl":
        # STL is handled in-thread by the route; kept here only so the worker
        # entry is total over supported suffixes (and for direct-call tests).
        from src.parsers.stl_parser import parse_stl_from_bytes

        return parse_stl_from_bytes(data, f"upload{suffix}")
    from src.parsers.step_mesher import step_to_trimesh_from_bytes

    return step_to_trimesh_from_bytes(data, f"upload{suffix}")


def _rung_worker(data: bytes, suffix: str, idx: int, report: str | None = None) -> trimesh.Trimesh:
    """PURE, picklable worker entry for ONE ladder rung. Returns a
    ``trimesh.Trimesh`` or raises the step_mesher rung exceptions
    (``_StepReadError`` / ``_EmptyMeshError`` / other) that the orchestrator maps.
    Module-level so ``ProcessPoolExecutor`` can pickle it by qualified name."""
    if report:
        _report_start(report)
    from src.parsers.step_mesher import mesh_single_rung_from_bytes

    return mesh_single_rung_from_bytes(data, f"upload{suffix}", idx)


def _get_pool() -> ProcessPoolExecutor:
    """Lazily create the module-level singleton pool (spawn context)."""
    global _POOL
    with _POOL_LOCK:
        if _STOPPING:
            raise RuntimeError("parse process pool is stopping")
        if _POOL is None:
            ctx = multiprocessing.get_context("spawn")  # NEVER fork under asyncio
            _POOL = ProcessPoolExecutor(max_workers=worker_count(), mp_context=ctx)
            logger.info("parse process pool created (workers=%d)", worker_count())
        return _POOL


def _prewarm_worker() -> int:
    """PURE, picklable per-worker warmup — the eager-startup counterpart to
    ``_rung_worker``. Pays a worker's ONE-TIME cold cost UP FRONT so the first
    real request that lands on it skips ~0.7s:

      * imports ``src.parsers.step_mesher`` (which pulls trimesh + numpy + gmsh —
        the ~0.58s import the worker would otherwise pay on its first rung), and
      * runs a bare ``gmsh.initialize()`` / ``finalize()`` to pay gmsh's one-time
        runtime init (~0.1s the worker's first mesh would otherwise absorb).

    It imports and coarsely meshes only the repository-owned 19 KB cube
    fixture; no customer CAD, cost, or verdict is touched. Production mesh
    density is deliberately not used for this throwaway readiness parse. This
    moves the first real OCC read/mesh to boot without a per-worker 185k-face
    allocation competing with browser-gate CAD parses.
    Module-level so
    ``ProcessPoolExecutor`` can pickle it by qualified name.

    Best-effort: on any failure (e.g. gmsh absent) it swallows and returns — the
    worker still warms lazily on first real use exactly as before.
    """
    import os as _os
    import time as _time

    # Boot-safety self-test hook (OFF by default): lets a caller prove that a
    # failing warmup does NOT crash boot / block readiness. Never set in prod.
    if _os.getenv("PARSE_POOL_PREWARM_FORCE_FAIL") == "1":
        raise RuntimeError("simulated pre-warm failure (boot-safety self-test)")

    # Run a real OCC import + surface mesh, deliberately coarse because this
    # readiness fixture is thrown away. Production tessellation settings are
    # unchanged and apply only when a customer parse arrives.
    from pathlib import Path as _Path
    from src.parsers.step_mesher import prewarm_step_from_bytes
    fixture = (_Path(__file__).parent / "fixtures" / "prewarm-cube.step").read_bytes()
    mesh = prewarm_step_from_bytes(fixture, "prewarm-cube.step")
    if len(mesh.faces) <= 0:
        raise RuntimeError("parse warmup fixture produced no faces")
    # Briefly hold this worker so the executor engages a DISTINCT worker for each
    # queued warmup task (rather than reusing one fast worker for all of them),
    # ensuring every worker in the pool is warmed.
    _time.sleep(0.25)
    return _os.getpid()


def prewarm(block: bool = False, timeout: float | None = 45.0) -> int:
    """Eagerly build the shared pool and warm EVERY worker (import the mesher
    stack + pay gmsh runtime init) so the first real request skips the
    ~0.7s/worker cold-start tax. Reuses the existing singleton pool — does NOT
    rebuild it.

    Parses only a repository-owned fixture and is BEST-EFFORT: never raises.
    Honours the pool kill switch (``is_disabled()``) and a worker warmup failure
    is logged and swallowed, leaving that worker to warm lazily on first use —
    boot is never blocked or crashed. Returns the number of warmup tasks
    dispatched (0 if disabled/skipped).

    ``block=False`` (default) fires the warmups and returns immediately (results
    complete in the background pool). ``block=True`` waits up to ``timeout`` for
    each worker to finish warming (used by the startup thread so warmup outcomes
    are logged, and by tests)."""
    if is_disabled():
        logger.info("parse pool pre-warm skipped (pool disabled)")
        return 0
    try:
        pool = _get_pool()
        n = worker_count()
        futures = [pool.submit(_prewarm_worker) for _ in range(n)]
        with _POOL_LOCK:
            _WARMING.setdefault(id(pool), futures)
        logger.info("parse pool pre-warm dispatched (workers=%d)", n)
    except Exception:  # pool build failed — leave lazy warmup intact
        logger.warning("parse pool pre-warm skipped (pool build error)", exc_info=True)
        return 0
    if block:
        warmed = 0
        for f in futures:
            try:
                f.result(timeout=timeout)
                warmed += 1
            except Exception:
                logger.warning("parse pool worker pre-warm failed", exc_info=True)
        logger.info("parse pool pre-warm complete (%d/%d workers warm)", warmed, len(futures))
    return len(futures)


def _submit_tracked(pool: ProcessPoolExecutor, fn, *args):
    """``pool.submit`` that remembers the future until it is done (for ``retire_pool``)."""
    cfut = pool.submit(fn, *args)
    key = id(pool)
    with _POOL_LOCK:
        _INFLIGHT.setdefault(key, set()).add(cfut)

    def _done(f, key=key):
        with _POOL_LOCK:
            live = _INFLIGHT.get(key)
            if live is not None:
                live.discard(f)

    cfut.add_done_callback(_done)
    return cfut


def retire_pool(pool: ProcessPoolExecutor, stuck=None, *, grace: float | None = None) -> None:
    """Take a shared pool out of service without killing the other parses on it.

    For a parse that ran past its cap or whose request went away: gmsh's C call
    can't be interrupted, so its worker must die, but SIGKILLing the whole pool
    at once (``recycle_pool(kill=True)``) breaks every other request's parse on
    it. Instead new work goes to a fresh pool at once, and this one is
    hard-killed, the stuck worker with it, as soon as its other in-flight
    parses have finished, or after ``grace`` seconds (``RETIRE_GRACE_SEC``),
    whichever is first. A parse still on it then gets ``BrokenProcessPool`` and
    the usual isolated retry.
    """
    global _POOL
    grace = RETIRE_GRACE_SEC if grace is None else grace
    with _POOL_LOCK:
        if _POOL is pool:
            _POOL = None
        _WARMING.pop(id(pool), None)
        others = [f for f in _INFLIGHT.get(id(pool), ()) if f is not stuck and not f.done()]
    logger.info("parse pool retired (%d other parses finish first)", len(others))

    def _reap() -> None:
        if others:
            concurrent.futures.wait(others, timeout=grace)
        _hard_kill(pool)
        try:
            pool.shutdown(wait=False, cancel_futures=False)
        except Exception:
            logger.exception("retired parse pool shutdown failed")
        with _POOL_LOCK:
            _INFLIGHT.pop(id(pool), None)
            _WARMING.pop(id(pool), None)

    if others:
        threading.Thread(target=_reap, name="parse-pool-reaper", daemon=True).start()
    else:
        _reap()


def recycle_pool(kill: bool = False) -> None:
    """Tear down the current pool and drop the singleton so the NEXT dispatch
    lazily builds a fresh one.

    Used on (a) ``BrokenProcessPool`` — a worker died, the whole pool is unusable;
    (b) request timeout — a pooled tessellation may still be running in a worker,
    so we recycle to stop leaking a runaway rather than hold it forever; and
    (c) a rung-0 periodic GRIND that hit its cap (``kill=True``).

    ``shutdown(wait=False, cancel_futures=True)`` cancels QUEUED work and lets any
    RUNNING worker finish its current tessellation (a mid-flight C call cannot be
    interrupted from Python); dropping the singleton means new requests get a
    fresh, healthy pool immediately.

    ``kill=True`` additionally SIGKILLs the live workers. gmsh's mesh.generate is
    an uninterruptible C call, so a rung-0 periodic grind would otherwise keep a
    worker (and a CPU) busy for 2+ minutes AFTER we've abandoned its result — and
    block process exit. We reclaim it immediately. Any SIBLING request sharing the
    pool recovers via ``submit_async``'s isolated retry path, so the hard kill is
    bounded without moving untrusted parsing into the API process. Without
    ``kill`` we leave live workers alone (default; protects sibling in-flight work).
    """
    global _POOL
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
        if pool is not None:
            _WARMING.pop(id(pool), None)  # an id can be reused by the next pool
    if pool is None:
        return
    if kill:
        _hard_kill(pool)
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # never let recycle raise into the request path
        logger.exception("parse pool shutdown during recycle failed")


def startup() -> None:
    """Open the pool lifecycle for one ASGI serving interval."""
    global _STOPPING
    with _POOL_LOCK:
        _STOPPING = False


def shutdown(*, kill: bool = True, final: bool = False) -> None:
    """Bounded process-exit teardown. Idempotent and recreation-safe.

    With ``final=True``, ``_STOPPING`` is set while holding the same lock used by
    ``_get_pool`` so a detached pre-warm thread cannot recreate the singleton
    after shutdown took ownership. Production shutdown hard-kills active CAD
    workers because gmsh C calls are not interruptible, then joins the executor
    manager so its queues and multiprocessing semaphores are actually released.
    The join remains bounded because every worker is killed first. Ordinary test
    cleanup keeps ``final=False`` so a later test can lazily create a fresh pool.
    """
    global _POOL, _STOPPING
    with _POOL_LOCK:
        _STOPPING = final
        pool, _POOL = _POOL, None
        if pool is not None:
            _WARMING.pop(id(pool), None)
    if pool is not None:
        if kill:
            _hard_kill(pool)
        try:
            # wait=False abandons the executor's queue/semaphore handles to
            # multiprocessing.resource_tracker at interpreter exit. Once every
            # worker has been killed there is no uninterruptible CAD call left to
            # wait on, so a full join is both bounded and required for a clean
            # production shutdown.
            pool.shutdown(wait=kill, cancel_futures=True)
        except Exception:
            logger.exception("parse pool shutdown failed")


def _ladder_semaphore() -> "asyncio.Semaphore":
    """Loop-local semaphore bounding concurrent ladders to ``worker_count()`` so
    the dedicated per-rung executors can't oversubscribe the CPU past the shared
    pool's own bound. Attached to the running loop so it never crosses loops (a
    module-global asyncio.Semaphore breaks under pytest's per-test loops)."""
    loop = asyncio.get_event_loop()
    sem = getattr(loop, "_cadverify_ladder_sem", None)
    if sem is None:
        sem = asyncio.Semaphore(worker_count())
        setattr(loop, "_cadverify_ladder_sem", sem)
    return sem


# The task holding a pool slot (a task it starts is not it, and waits for its own).
_SLOT_HOLDER: contextvars.ContextVar[object] = contextvars.ContextVar("cadverify_parse_slot_holder", default=None)


@asynccontextmanager
async def pool_slot(*, warm: bool = True):
    """One of the pool's ``worker_count()`` slots for this task (re-entrant in the task).

    A caller with a time limit takes it before starting its timer, so the time
    spent waiting for a free pool worker behind other parts isn't counted as its
    own (the ladder and the assembly extraction take it again harmlessly), and
    so is a fresh pool's warm-up (``warm``; the ladder's own slot doesn't warm).
    """
    me = asyncio.current_task()
    if me is not None and _SLOT_HOLDER.get() is me:
        yield
        return
    async with _ladder_semaphore():
        token = _SLOT_HOLDER.set(me)
        try:
            # A fresh pool (the first use, or after a retire) warms up here,
            # before the caller's timer starts, so no part pays its spawn.
            if warm:
                await _warm_shared_pool()
            yield
        finally:
            _SLOT_HOLDER.reset(token)


# The warm-up tasks given to each shared pool (by id), so it is warmed once.
_WARMING: dict[int, list] = {}


def _warm_futures(pool: ProcessPoolExecutor) -> list:
    with _POOL_LOCK:
        futs = _WARMING.get(id(pool))
        if futs is None:
            futs = [pool.submit(_prewarm_worker) for _ in range(worker_count())]
            _WARMING[id(pool)] = futs
    return futs


async def _warm_shared_pool() -> None:
    """Wait (bounded) until the shared pool's workers are warm; best effort."""
    if is_disabled():
        return
    try:
        pool = _get_pool()
        if not isinstance(pool, ProcessPoolExecutor):
            return
        pending = [f for f in _warm_futures(pool) if not f.done()]
    except Exception:
        return
    if pending:
        waits = [asyncio.wrap_future(f) for f in pending]
        for w in waits:
            w.add_done_callback(lambda f: f.cancelled() or f.exception())  # a failed warm-up is only slower
        await asyncio.wait(waits, timeout=WARM_WAIT_SEC)


def _hard_kill(ex: ProcessPoolExecutor) -> None:
    """SIGKILL every worker of a single-use executor. Safe to hard-kill because
    each recovery-rung executor owns exactly ONE worker running ONLY this rung —
    no sibling request shares it. The shared pool is hard-killed only through
    ``recycle_pool(kill=True)`` when its state is no longer trustworthy."""
    # A worker can die mid-pickle. Close the parent's unused sending end first
    # so recv sees EOF after the workers die instead of waiting forever for the
    # rest of the payload (and blocking the executor/Python shutdown thread).
    result_queue = getattr(ex, "_result_queue", None)
    if result_queue is not None:
        result_queue._writer.close()
    for proc in list((getattr(ex, "_processes", None) or {}).values()):
        try:
            proc.kill()
        except Exception:  # already dead / racing shutdown
            pass


async def _run_rung_killable(data: bytes, suffix: str, idx: int, cap: float):
    """Run ONE ladder rung in a dedicated single-worker spawn subprocess, bounded
    by ``cap`` seconds of its CPU (and the ladder's deadline). On either, HARD-KILL
    the worker (gmsh's mesh.generate is an uninterruptible C call — only SIGKILL
    reclaims it) and raise ``_RungTimeout`` (CPU) or ``_RungStarved`` (deadline).
    Worker exceptions (``_StepReadError`` / ``_EmptyMeshError`` / other) propagate
    for the orchestrator to map. A crashed worker surfaces as ``BrokenProcessPool``.
    """
    ctx = multiprocessing.get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    report = _new_report()
    try:
        cfut = ex.submit(_rung_worker, data, suffix, idx, report)
        try:
            return await _await_rung(cfut, report, idx, cap)
        except (_RungTimeout, _RungStarved):
            _hard_kill(ex)
            raise
        except asyncio.CancelledError:
            # The request disappeared while gmsh was inside an uninterruptible C
            # call. The executor is single-use, so killing it cannot affect a
            # sibling request and prevents an orphan parser from surviving.
            _hard_kill(ex)
            raise
    finally:
        # wait=False: never block the request on a worker we may have just killed.
        ex.shutdown(wait=False, cancel_futures=True)
        _drop_report(report)


def _run_tessellate_killable_sync(
    data: bytes, suffix: str, cap: float
) -> trimesh.Trimesh:
    """Retry a synchronous parse in one fresh subprocess, never in-process.

    This path exists only after the shared pool has crashed. It has its own
    worker and wall-clock cap, so a second crash or grind cannot poison the API
    process or leave an unbounded parser behind.
    """
    ctx = multiprocessing.get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    try:
        future = ex.submit(tessellate, data, suffix)
        try:
            return future.result(timeout=cap)
        except FuturesTimeout:
            _hard_kill(ex)
            raise TimeoutError(
                f"isolated tessellation retry exceeded {cap:.0f}s cap"
            )
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


async def _run_assembly_killable(data: bytes, suffix: str, mesh_single_part: bool = True):
    """Retry one assembly extraction in a dedicated killable subprocess.

    The route's outer ``wait_for`` owns the total wall-clock budget. If that
    budget expires or the client disconnects, cancellation reaches this helper
    and hard-kills its single worker.
    """
    ctx = multiprocessing.get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    try:
        future = ex.submit(_extract_assembly_worker, data, suffix, mesh_single_part)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            _hard_kill(ex)
            raise
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


async def submit_async(data: bytes, suffix: str) -> trimesh.Trimesh:
    """Await the retry-ladder tessellation with a PER-RUNG CPU-time cap.

    rung 0 runs on the shared warm process pool (byte-identical, concurrent, no
    latency regression for normal parts). Its cap only fires on a periodic-surface
    GRIND, in which case its worker dies (the pool is retired, see retire_pool)
    and the ladder falls to the recovery rungs, each run in its OWN killable
    subprocess and hard-killed at its cap. This is what lets a periodic part
    return a valid shell WITHIN the route budget instead of 504-ing after a
    2-minute rung-0 grind.

    The caps are CPU seconds in the rung's worker, the part's own work, so the
    ladder's path (and the mesh) is the same on an idle or a loaded box. Wall
    time only bounds the whole ladder (the route's budget, less a margin): when
    it runs out first the worker was starved, and the ladder raises ParseBusy
    (the route's 429 busy) instead of trying another strategy because of time.

    On ``BrokenProcessPool`` (segfaulted worker, adversarial gmsh input) we
    hard-recycle the shared pool and retry rung 0 in its own killable subprocess.
    A second crash advances the bounded ladder; it never moves untrusted bytes
    into the API process. Other worker exceptions retain the route's mapping.
    """
    from src.parsers import step_mesher as sm

    loop = asyncio.get_event_loop()
    n = len(sm._MESH_RUNGS)
    budget = _budget_sec()
    caps = _rung_caps(budget, n)
    # The whole ladder's wall clock: the route's budget, less a margin so the
    # honest answer beats the route's own 504.
    token = ladder_clock(max(1.0, budget - min(2.0, 0.05 * budget)))

    try:
        async with pool_slot(warm=False):
            return await _ladder(data, suffix, sm, n, caps, loop)
    finally:
        _LADDER_CLOCK.reset(token)


async def _ladder(data, suffix, sm, n, caps, loop):
    """The rungs in order (see submit_async)."""
    last_msg = ""
    best_open: trimesh.Trimesh | None = None
    for idx in range(n):
        try:
            if idx == 0:
                try:
                    mesh = await _rung0_via_pool(data, suffix, caps[0], loop)
                except BrokenProcessPool:
                    logger.warning(
                        "parse pool worker died on rung 0; hard-recycling + "
                        "isolated retry"
                    )
                    recycle_pool(kill=True)
                    mesh = await _run_rung_killable(
                        data, suffix, idx, caps[idx]
                    )
            else:
                mesh = await _run_rung_killable(data, suffix, idx, caps[idx])
        except sm._StepReadError as exc:
            # Unreadable STEP: a different algorithm cannot fix it — abort now.
            raise ValueError(
                "Could not read STEP geometry (not a valid/supported STEP file)."
            ) from exc
        except _RungTimeout as exc:
            # It used its CPU budget: this strategy doesn't converge on this part.
            last_msg = str(exc) or "periodic surface grind (rung capped)"
            logger.info("step ladder rung %d hit its CPU cap; advancing (%s)", idx, exc)
            continue
        except _RungStarved as exc:
            # Out of wall time before its CPU budget: the box is busy. Never
            # advance because of time (the next strategy meshes differently).
            logger.warning("step ladder stopped busy at rung %d (%s)", idx, exc)
            raise ParseBusy(exc.plain()) from None
        except sm._EmptyMeshError as exc:
            last_msg = str(exc)
            continue
        except BrokenProcessPool:
            last_msg = f"rung {idx} worker crashed"
            logger.warning(
                "isolated step ladder rung %d worker crashed; advancing", idx
            )
            continue
        except Exception as exc:  # this rung failed to MESH a readable shape
            last_msg = str(exc)
            logger.info("step ladder rung %d failed (%s); advancing", idx, last_msg[:120])
            continue

        # A platform/version may return quickly from a periodic rung with an
        # open shell instead of raising or grinding. Keep the best such shell
        # only as a fallback and continue: a later MeshAdapt rung can close it.
        if not mesh.is_watertight:
            best_open = sm._prefer_open_shell(best_open, mesh)
            last_msg = f"rung {idx} produced a non-watertight shell"
            logger.info(
                "step ladder rung %d produced an open shell (%d defective "
                "edges); advancing",
                idx, sm._shell_defect_count(mesh),
            )
            continue

        if idx > 0:
            logger.info(
                "step ladder recovered on rung %d (faces=%d, watertight=%s)",
                idx, len(mesh.faces), mesh.is_watertight,
            )
        return mesh

    if best_open is not None:
        logger.info(
            "step ladder found no watertight strategy; returning least-defective "
            "open shell for the downstream geometry gate (faces=%d, defects=%d)",
            len(best_open.faces), sm._shell_defect_count(best_open),
        )
        return best_open

    # Every rung failed within budget -> the SPECIFIC, honest 400 (not a 504).
    raise sm.ladder_failure_error(last_msg)


async def _rung0_via_pool(data: bytes, suffix: str, cap: float, loop):
    """Run rung 0 on the shared warm pool with a CPU-time cap. Success is
    byte-identical to the historical primary path. On cap (a periodic grind) raise
    ``_RungTimeout``; on the ladder's deadline ``_RungStarved``. Either way the
    pool is retired (its stuck worker killed once the other requests' parses on
    it have finished; see retire_pool). ``BrokenProcessPool`` propagates for the
    caller's fallback."""
    pool = _get_pool()
    report = _new_report()
    cfut = _submit_tracked(pool, _rung_worker, data, suffix, 0, report)
    try:
        return await _await_rung(cfut, report, 0, cap)
    except _RungTimeout:
        # The grinding worker must die so it doesn't keep a CPU (or block exit)
        # while the recovery rungs run, but the other requests' parses on the
        # same pool must not: the pool is retired, not killed outright.
        if not cfut.cancel() and not cfut.done():
            retire_pool(pool, stuck=cfut)
        raise _RungTimeout(f"rung 0 used its {cap:.0f}s of CPU (periodic-surface grind)") from None
    except (_RungStarved, asyncio.CancelledError):
        # Out of time on a busy box, or the request went away mid-rung.
        if not cfut.cancel() and not cfut.done():
            retire_pool(pool, stuck=cfut)
        raise
    finally:
        _drop_report(report)


def submit_sync(data: bytes, suffix: str) -> trimesh.Trimesh:
    """Synchronous pooled tessellation (round-trips through a worker). For
    correctness tests that assert the pickled mesh is byte-identical to an
    in-thread parse. A broken shared pool retries in one fresh, bounded worker;
    it never parses attacker-controlled bytes in this process."""
    pool = _get_pool()
    try:
        return pool.submit(tessellate, data, suffix).result()
    except BrokenProcessPool:
        logger.warning("parse pool broken (sync); hard-recycling + isolated retry")
        recycle_pool(kill=True)
        return _run_tessellate_killable_sync(data, suffix, _budget_sec())


# ── Assembly ingestion (multi-solid STEP/IGES) ──────────────────────────────
def _extract_assembly_worker(data: bytes, suffix: str, mesh_single_part: bool = True):
    """PURE, picklable worker entry: extract the full AssemblyModel (per-part
    meshes + world positions + product tree) IN THIS PROCESS. Module-level so
    ``ProcessPoolExecutor`` can pickle it by qualified name. Raises plain
    ``ValueError`` (route -> 400) for a bad/native/unmeshable file.
    ``mesh_single_part=False``: a file of one solid comes back unmeshed."""
    from src.parsers.ap242_tessellated_parser import is_ap242_tessellated
    from src.parsers.assembly_mesher import (
        extract_assembly_from_bytes,
        single_part_model_from_mesh,
    )

    # The AP242 embedded-tessellation branch is a supported single part but is
    # not a B-rep that gmsh/OCC's assembly importer can read. Reuse the canonical
    # mesh parser and return a truthful single-part classification instead of
    # crashing a parser worker and emitting a misleading assembly 400.
    if suffix.lower() in {".step", ".stp"} and is_ap242_tessellated(data):
        mesh = tessellate(data, suffix)
        return single_part_model_from_mesh(
            mesh,
            source_suffix=suffix,
            name="embedded-tessellated-part",
        )

    return extract_assembly_from_bytes(data, f"upload{suffix}", mesh_single_part=mesh_single_part)


async def submit_assembly_async(data: bytes, suffix: str, *, mesh_single_part: bool = True):
    """Extract an ``AssemblyModel`` off the event loop, bounded by the route
    budget. Runs the CPU-bound multi-solid gmsh extraction in the shared spawn
    pool (so N assemblies don't serialize on the GIL/gmsh lock and the loop stays
    responsive), hard-bounded by ``ANALYSIS_TIMEOUT_SEC`` at the caller. On
    ``BrokenProcessPool`` (a worker died on adversarial gmsh input) we hard-
    recycle the pool and retry THIS request in a dedicated killable subprocess.
    Untrusted assembly bytes are never parsed in the API process after a crash.

    The per-assembly retry ladder (primary -> MeshAdapt-uniform -> +OCC-heal) runs
    WITHIN the worker call (``assembly_mesher._extract_with_ladder``); the caller's
    outer ``wait_for`` provides the wall-clock bound. ``mesh_single_part=False``
    (the probe's question: how many bodies?) reads a one-solid file unmeshed.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    if is_disabled():
        return await loop.run_in_executor(
            None, _extract_assembly_worker, data, suffix, mesh_single_part
        )
    async with pool_slot(warm=False):
        pool = _get_pool()
        try:
            cfut = _submit_tracked(pool, _extract_assembly_worker, data, suffix, mesh_single_part)
            try:
                return await asyncio.wrap_future(cfut)
            except asyncio.CancelledError:
                # The caller's time limit or its request went away. A queued
                # extraction is simply dropped; a running one is gmsh in C: its
                # pool is retired, its siblings left to finish.
                if not cfut.cancel() and not cfut.done():
                    retire_pool(pool, stuck=cfut)
                raise
        except BrokenProcessPool:
            logger.warning(
                "parse pool worker died during assembly extraction; hard-recycling + "
                "isolated retry"
            )
            recycle_pool(kill=True)
            return await _run_assembly_killable(data, suffix, mesh_single_part)
