"""Bounded analysis: untrusted CAD work runs in a killable child, never here.

The containment envelope (audit follow-up): customer geometry can ask for
arbitrary memory (a tessellated cylinder made one hull query allocate 3.6 GB
and OOM-kill the whole API instance — twice). Three layers make that class of
failure impossible:

1. **A separate process.** The full analysis engine (geometry → context →
   features → every analyzer) runs in a spawned worker. The worst a file can
   do to it — hang, explode, die — costs one recycled worker, never the web
   instance that serves everyone else.
2. **An allocation cap.** On Linux the child sets ``RLIMIT_AS``: runaway
   allocations fail *inside the child* as catchable ``MemoryError`` (which the
   engine's per-analyzer containment degrades into an honest ANALYSIS_PARTIAL
   finding) instead of the cgroup OOM killer taking the instance with no
   Python-level chance to answer.
3. **A wall-clock cap and an RSS watchdog.** A stuck analysis is killed and
   reported as budget-exceeded; the pool recycles.

The runner is OFF by default (tests and dev call the engine in-process) and ON
in the deployed images via ``CADVERIFY_ANALYSIS_POOL=1``. Every knob is env-
overridable so the envelope itself is testable at tight budgets.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

logger = logging.getLogger("cadverify.bounded_analysis")

DEFAULT_MEM_MB = 768          # VA cap; generous vs RSS so numpy doesn't false-trip
DEFAULT_RSS_MB = 420          # the real limiter: sampled watchdog kill level
DEFAULT_TIMEOUT_S = 180.0     # wall clock for one whole analysis
DEFAULT_WATCHDOG_S = 0.5


class AnalysisBudgetExceeded(Exception):
    """The bounded runner could not finish within its caps. The stage names
    which envelope layer fired: 'memory' (RSS watchdog), 'time', or 'died'
    (worker crash). Never retried silently — the caller answers honestly."""

    def __init__(self, stage: str, detail: str = ""):
        self.stage = stage
        super().__init__(f"analysis budget exceeded ({stage}): {detail}"[:300])


def enabled() -> bool:
    return os.getenv("CADVERIFY_ANALYSIS_POOL", "0") == "1"


def _mem_mb() -> int:
    try:
        return max(128, int(os.getenv("ANALYSIS_POOL_MEM_MB", str(DEFAULT_MEM_MB))))
    except ValueError:
        return DEFAULT_MEM_MB


def _rss_mb() -> int:
    try:
        return max(128, int(os.getenv("ANALYSIS_POOL_RSS_MB", str(DEFAULT_RSS_MB))))
    except ValueError:
        return DEFAULT_RSS_MB


def _timeout_s() -> float:
    try:
        return max(5.0, float(os.getenv("ANALYSIS_POOL_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _child_init() -> None:
    """Pool worker initializer: cap THIS process's address space (Linux only —
    RLIMIT_AS is not enforced meaningfully on macOS). A runaway allocation
    raises MemoryError here, inside the child, where it degrades gracefully
    instead of triggering the instance-level OOM killer."""
    try:
        import resource

        if hasattr(resource, "RLIMIT_AS") and os.uname().sysname == "Linux":
            cap = _mem_mb() * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    except Exception:  # never let the initializer itself kill a worker
        pass


def _sleep_worker(seconds: float):
    """Test-only worker: sleep, so the wall-clock cap is deterministic."""
    import time

    time.sleep(seconds)
    return seconds


def _memory_bomb_worker(mb: int):
    """Test-only worker: allocate ~mb megabytes, so the envelope's memory cap
    can be exercised deterministically on Linux (where RLIMIT_AS turns this
    into a catchable failure inside the child)."""
    chunks = []
    for _ in range(mb):
        chunks.append(bytearray(1024 * 1024))
    return len(chunks)


def _engine_worker(mesh, filename: str, orientation):
    """PURE, picklable worker entry: the full cost-engine analysis pass, run
    in the child. Returns whatever ``routes._run_cost_engine_ctx`` returns so
    the parent keeps its exact contract. Module-level for pickling."""
    from src.api.routes import _run_cost_engine_ctx

    return _run_cost_engine_ctx(mesh, filename, orientation=orientation)


def _analysis_core_worker(mesh, target_process_values, orientation, suffix,
                          filename, cost_cache_key):
    """PURE, picklable worker entry: the analysis-service synchronous core
    (``analysis_service._analysis_core``) run in the child. Single source of
    truth — the parent and the child call the same function, so the envelope
    can never drift from the in-thread path."""
    import src.analysis.processes  # noqa: F401  populate registry
    from src.analysis.models import ProcessType
    from src.services.analysis_service import _analysis_core

    return _analysis_core(
        mesh,
        [ProcessType(v) for v in target_process_values],
        None,                      # bounded path is the no-rule-pack shape
        orientation,
        suffix,
        filename,
        cost_cache_key,
    )


class _BoundedPool:
    """Singleton spawn pool with recycle-on-poison and an RSS watchdog."""

    def __init__(self) -> None:
        self._pool: ProcessPoolExecutor | None = None
        self._lock = threading.Lock()
        self._stopping = False
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()

    def _get(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._stopping:
                raise RuntimeError("bounded analysis pool is stopping")
            if self._pool is None:
                import multiprocessing

                ctx = multiprocessing.get_context("spawn")  # NEVER fork under asyncio
                self._pool = ProcessPoolExecutor(max_workers=1, mp_context=ctx,
                                                 initializer=_child_init)
                logger.info("bounded analysis pool created (mem_cap=%dMB rss_cap=%dMB)",
                            _mem_mb(), _rss_mb())
                self._ensure_watchdog()
            return self._pool

    def _ensure_watchdog(self) -> None:
        if self._watchdog is not None or Path("/proc").exists() is False:
            return
        self._watchdog = threading.Thread(target=self._watch_loop, daemon=True,
                                          name="bounded-analysis-watchdog")
        self._watchdog.start()

    def _watch_loop(self) -> None:
        """Sample each worker's VmRSS; a worker past the cap is killed, which
        surfaces to its caller as BrokenProcessPool → a budget-exceeded
        answer. Linux only (reads /proc); elsewhere RLIMIT/time carry the
        envelope."""
        cap_kb = _rss_mb() * 1024
        while not self._watchdog_stop.wait(DEFAULT_WATCHDOG_S):
            pool = self._pool
            if pool is None:
                continue
            for pid in list(getattr(pool, "_processes", {}) or {}):
                try:
                    with open(f"/proc/{pid}/status") as fh:
                        for line in fh:
                            if line.startswith("VmRSS:"):
                                rss_kb = int(line.split()[1])
                                if rss_kb > cap_kb:
                                    logger.warning(
                                        "bounded analysis worker %d RSS %dMB > cap %dMB; killing",
                                        pid, rss_kb // 1024, _rss_mb())
                                    os.kill(pid, signal.SIGKILL)
                                break
                except (OSError, ValueError, IndexError):
                    continue

    def recycle(self) -> None:
        """Drop the pool entirely (workers die with it). Called after any
        budget trip so the next request starts from a clean worker."""
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def stop(self) -> None:
        self._stopping = True
        self._watchdog_stop.set()
        self.recycle()


_POOL = _BoundedPool()


def _run_bounded(fn, /, *args, timeout_s: float | None = None):
    """Submit to the child and enforce the wall clock. Any budget trip
    (timeout, worker death) recycles the worker and raises
    AnalysisBudgetExceeded — never a raw crash into the caller."""
    deadline_cap = timeout_s or _timeout_s()
    fut = _POOL._get().submit(fn, *args)
    try:
        return fut.result(timeout=deadline_cap)
    except MemoryError as exc:
        _POOL.recycle()
        raise AnalysisBudgetExceeded("memory", "allocation cap hit inside the worker") from exc
    except BrokenProcessPool as exc:
        _POOL.recycle()
        raise AnalysisBudgetExceeded("died", "analysis worker died (budget or crash)") from exc
    except TimeoutError as exc:
        _POOL.recycle()
        raise AnalysisBudgetExceeded("time", f"exceeded {deadline_cap:g}s wall clock") from exc


async def run_analysis_core(mesh, target_process_values, orientation, suffix,
                            filename, cost_cache_key, timeout_s: float | None = None):
    """Bounded analysis-service core: returns the core's 9-tuple."""
    import functools

    loop = asyncio.get_running_loop()
    job = functools.partial(_run_bounded, timeout_s=timeout_s)
    return await loop.run_in_executor(
        None, job, _analysis_core_worker, mesh, target_process_values,
        orientation, suffix, filename, cost_cache_key)


def run_engine_ctx_sync(mesh, filename: str, orientation=None):
    """Bounded ``routes._run_cost_engine_ctx``, BLOCKING form for callers that
    already run off the event loop (the cost path's executor thread). Same
    return contract; raises AnalysisBudgetExceeded instead of ever crashing the
    calling process."""
    return _run_bounded(_engine_worker, mesh, filename, orientation)


async def run_engine_ctx(mesh, filename: str, orientation=None):
    """Bounded ``routes._run_cost_engine_ctx``: same return contract, never a
    process-level blast radius."""
    import functools

    loop = asyncio.get_running_loop()
    job = functools.partial(_run_bounded)
    return await loop.run_in_executor(None, job, _engine_worker, mesh, filename, orientation)
