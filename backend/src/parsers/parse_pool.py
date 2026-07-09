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
  * Robust fallback: on ``BrokenProcessPool`` (a worker segfaulted on adversarial
    gmsh input) we recycle the pool AND parse THIS request in-thread, so the
    caller still gets a correct mesh — never a 500. Subsequent requests use the
    recreated pool.
  * Only STEP/IGES is dispatched. STL is sub-second; the pickle round-trip would
    cost more than the parse, so the route keeps STL in-thread.

Scope caveat: the pool is PER-PROCESS (per uvicorn worker / replica), exactly
like the mesh cache. Worker startup pays a one-time ``spawn`` import cost on
first use.
"""
from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import trimesh

logger = logging.getLogger("cadverify.parse_pool")

# Upper bound on workers regardless of CPU count — parsing is memory-heavy
# (each gmsh worker holds a full OCC context + mesh), so we cap independently
# of core count. Env override wins over the derived default either way.
_WORKER_CAP = 8

_POOL_LOCK = threading.Lock()
_POOL: ProcessPoolExecutor | None = None


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
    responsive under a parse burst.
    """
    cpu = os.cpu_count() or 2
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


def _get_pool() -> ProcessPoolExecutor:
    """Lazily create the module-level singleton pool (spawn context)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            ctx = multiprocessing.get_context("spawn")  # NEVER fork under asyncio
            _POOL = ProcessPoolExecutor(max_workers=worker_count(), mp_context=ctx)
            logger.info("parse process pool created (workers=%d)", worker_count())
        return _POOL


def recycle_pool() -> None:
    """Tear down the current pool and drop the singleton so the NEXT dispatch
    lazily builds a fresh one.

    Used on (a) ``BrokenProcessPool`` — a worker died, the whole pool is unusable;
    and (b) request timeout — a pooled tessellation may still be running in a
    worker, so we recycle to stop leaking a runaway rather than hold it forever.

    ``shutdown(wait=False, cancel_futures=True)`` cancels QUEUED work and lets any
    RUNNING worker finish its current tessellation (a mid-flight C call cannot be
    interrupted from Python); dropping the singleton means new requests get a
    fresh, healthy pool immediately. We intentionally do NOT hard-terminate live
    workers, which would break sibling in-flight requests sharing the pool.
    """
    global _POOL
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
    if pool is None:
        return
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:  # never let recycle raise into the request path
        logger.exception("parse pool shutdown during recycle failed")


def shutdown() -> None:
    """Best-effort teardown for process exit / tests. Idempotent."""
    global _POOL
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            logger.exception("parse pool shutdown failed")


async def submit_async(data: bytes, suffix: str) -> trimesh.Trimesh:
    """Await a pooled tessellation, with robust in-thread fallback.

    On ``BrokenProcessPool`` (segfaulted worker, e.g. adversarial gmsh input) we
    recycle the pool and parse THIS request in the default thread executor, so the
    caller still receives a correct mesh — never a 500. Any other worker exception
    (e.g. ``ValueError`` on bad geometry) propagates unchanged for the route to map.

    Cancellation: if the caller's ``asyncio.wait_for`` times out, the awaited
    wrapper is cancelled. A RUNNING pool worker can't be cancelled mid-C-call, so
    the route recycles the pool on timeout (see routes.py) to reclaim it.
    """
    loop = asyncio.get_event_loop()
    pool = _get_pool()
    try:
        cfut = pool.submit(tessellate, data, suffix)
    except BrokenProcessPool:
        logger.warning("parse pool broken on submit; recycling + in-thread fallback")
        recycle_pool()
        return await loop.run_in_executor(None, tessellate, data, suffix)
    try:
        return await asyncio.wrap_future(cfut)
    except BrokenProcessPool:
        logger.warning("parse pool worker died; recycling + in-thread fallback")
        recycle_pool()
        return await loop.run_in_executor(None, tessellate, data, suffix)


def submit_sync(data: bytes, suffix: str) -> trimesh.Trimesh:
    """Synchronous pooled tessellation (round-trips through a worker). For
    correctness tests that assert the pickled mesh is byte-identical to an
    in-thread parse. Same BrokenProcessPool fallback as ``submit_async``."""
    pool = _get_pool()
    try:
        return pool.submit(tessellate, data, suffix).result()
    except BrokenProcessPool:
        logger.warning("parse pool broken (sync); recycling + in-thread fallback")
        recycle_pool()
        return tessellate(data, suffix)
