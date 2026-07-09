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

# ── Per-rung wall-clock budget (the periodic-surface fix) ───────────────────
# gmsh's DEFAULT 2D algorithm (retry-ladder rung 0) grinds for 2+ MINUTES before
# FAILING on a periodic-surface part (e.g. nist_ctc_05), then the fast MeshAdapt
# recovery rung runs — but by then the route's ANALYSIS_TIMEOUT_SEC has already
# fired a 504, so the recovery never reaches the user. mesh.generate is an
# uninterruptible in-thread C call, so the ONLY way to bound a rung is to run it
# in a KILLABLE subprocess and hard-kill it at a wall-clock cap.
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
    """A single ladder rung exceeded its wall-clock cap and was hard-killed."""


def _budget_sec() -> float:
    """Total analysis budget to split across rungs (mirrors routes._analysis_
    timeout_sec; the route's outer wait_for enforces the same total as a 504)."""
    try:
        return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    except ValueError:
        return 60.0


def _rung_caps(budget: float, n_rungs: int) -> list[float]:
    """Per-rung wall-clock caps. rung 0 gets min(0.4*budget, 25s); the recovery
    rungs evenly share 0.5*budget. Sum < budget so the honest 400 (all rungs
    failed) beats the route's total-budget 504."""
    rung0 = min(_RUNG0_FRACTION * budget, _RUNG0_CAP_MAX, budget)
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


def _rung_worker(data: bytes, suffix: str, idx: int) -> trimesh.Trimesh:
    """PURE, picklable worker entry for ONE ladder rung. Returns a
    ``trimesh.Trimesh`` or raises the step_mesher rung exceptions
    (``_StepReadError`` / ``_EmptyMeshError`` / other) that the orchestrator maps.
    Module-level so ``ProcessPoolExecutor`` can pickle it by qualified name."""
    from src.parsers.step_mesher import mesh_single_rung_from_bytes

    return mesh_single_rung_from_bytes(data, f"upload{suffix}", idx)


def _get_pool() -> ProcessPoolExecutor:
    """Lazily create the module-level singleton pool (spawn context)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            ctx = multiprocessing.get_context("spawn")  # NEVER fork under asyncio
            _POOL = ProcessPoolExecutor(max_workers=worker_count(), mp_context=ctx)
            logger.info("parse process pool created (workers=%d)", worker_count())
        return _POOL


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
    pool recovers via ``submit_async``'s ``BrokenProcessPool`` -> in-thread
    fallback (a correct mesh, never a 500), so the hard kill is safe. Without
    ``kill`` we leave live workers alone (default; protects sibling in-flight work).
    """
    global _POOL
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
    if pool is None:
        return
    if kill:
        for proc in list(getattr(pool, "_processes", {}).values()):
            try:
                proc.kill()
            except Exception:  # already dead / racing shutdown
                pass
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


def _hard_kill(ex: ProcessPoolExecutor) -> None:
    """SIGKILL every worker of a single-use executor. Safe to hard-kill because
    each recovery-rung executor owns exactly ONE worker running ONLY this rung —
    no sibling request shares it (unlike the concurrency pool, which we never
    hard-kill; see recycle_pool)."""
    for proc in list(getattr(ex, "_processes", {}).values()):
        try:
            proc.kill()
        except Exception:  # already dead / racing shutdown
            pass


async def _run_rung_killable(data: bytes, suffix: str, idx: int, cap: float):
    """Run ONE ladder rung in a dedicated single-worker spawn subprocess, bounded
    by ``cap`` seconds. On cap, HARD-KILL the worker (gmsh's mesh.generate is an
    uninterruptible C call — only SIGKILL reclaims it) and raise ``_RungTimeout``.
    Worker exceptions (``_StepReadError`` / ``_EmptyMeshError`` / other) propagate
    for the orchestrator to map. A crashed worker surfaces as ``BrokenProcessPool``.
    """
    ctx = multiprocessing.get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=1, mp_context=ctx)
    try:
        cfut = ex.submit(_rung_worker, data, suffix, idx)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(cfut), cap)
        except asyncio.TimeoutError:
            _hard_kill(ex)
            raise _RungTimeout(f"rung {idx} exceeded {cap:.0f}s cap")
    finally:
        # wait=False: never block the request on a worker we may have just killed.
        ex.shutdown(wait=False, cancel_futures=True)


async def submit_async(data: bytes, suffix: str) -> trimesh.Trimesh:
    """Await the retry-ladder tessellation with a PER-RUNG wall-clock cap.

    rung 0 runs on the shared warm process pool (byte-identical, concurrent, no
    latency regression for normal parts). Its cap only fires on a periodic-surface
    GRIND, in which case we HARD-KILL the grinding worker (recycle_pool(kill=True))
    and fall to the recovery rungs, each run in its OWN killable subprocess and
    hard-killed at its cap. This is what lets a periodic part return a valid shell
    WITHIN the route budget instead of 504-ing after a 2-minute rung-0 grind.

    On ``BrokenProcessPool`` (segfaulted worker, adversarial gmsh input) we recycle
    the shared pool and parse THIS request in the default thread executor — the
    caller still receives a correct mesh, never a 500 (unchanged contract). Any
    other worker exception propagates unchanged for the route to map.
    """
    from src.parsers import step_mesher as sm

    loop = asyncio.get_event_loop()
    n = len(sm._MESH_RUNGS)
    caps = _rung_caps(_budget_sec(), n)
    last_msg = ""

    async with _ladder_semaphore():
        for idx in range(n):
            try:
                if idx == 0:
                    mesh = await _rung0_via_pool(data, suffix, caps[0], loop)
                else:
                    mesh = await _run_rung_killable(data, suffix, idx, caps[idx])
            except sm._StepReadError as exc:
                # Unreadable STEP: a different algorithm cannot fix it — abort now.
                raise ValueError(
                    "Could not read STEP geometry (not a valid/supported STEP file)."
                ) from exc
            except _RungTimeout as exc:
                last_msg = str(exc) or "periodic surface grind (rung capped)"
                logger.info("step ladder rung %d hit its cap; advancing (%s)", idx, exc)
                continue
            except sm._EmptyMeshError as exc:
                last_msg = str(exc)
                continue
            except BrokenProcessPool:
                # A worker died mid-rung. rung 0 keeps its historical contract:
                # recycle + correct in-thread parse (never a 500). Recovery-rung
                # crashes just advance to the next rung.
                if idx == 0:
                    logger.warning(
                        "parse pool worker died on rung 0; recycling + in-thread fallback"
                    )
                    recycle_pool()
                    return await loop.run_in_executor(None, tessellate, data, suffix)
                last_msg = f"rung {idx} worker crashed"
                logger.warning("step ladder rung %d worker crashed; advancing", idx)
                continue
            except Exception as exc:  # this rung failed to MESH a readable shape
                last_msg = str(exc)
                logger.info("step ladder rung %d failed (%s); advancing", idx, last_msg[:120])
                continue

            if idx > 0:
                logger.info(
                    "step ladder recovered on rung %d (faces=%d, watertight=%s)",
                    idx, len(mesh.faces), mesh.is_watertight,
                )
            return mesh

    # Every rung failed within budget -> the SPECIFIC, honest 400 (not a 504).
    raise sm.ladder_failure_error(last_msg)


async def _rung0_via_pool(data: bytes, suffix: str, cap: float, loop):
    """Run rung 0 on the shared warm pool with a wall-clock cap. Success is
    byte-identical to the historical primary path. On cap (a periodic grind) raise
    ``_RungTimeout`` and leave the runaway worker to finish in the background — we
    do NOT hard-kill a shared pool worker (it may serve sibling requests; see
    recycle_pool). ``BrokenProcessPool`` propagates for the caller's fallback."""
    pool = _get_pool()
    cfut = pool.submit(_rung_worker, data, suffix, 0)
    try:
        return await asyncio.wait_for(asyncio.wrap_future(cfut), cap)
    except asyncio.TimeoutError:
        # Hard-kill the grinding worker + rebuild the pool so we don't leak a
        # runaway (or block exit) while the recovery rungs run. Siblings recover
        # via submit_async's BrokenProcessPool -> in-thread fallback.
        recycle_pool(kill=True)
        raise _RungTimeout(f"rung 0 exceeded {cap:.0f}s cap (periodic-surface grind)")


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


# ── Assembly ingestion (multi-solid STEP/IGES) ──────────────────────────────
def _extract_assembly_worker(data: bytes, suffix: str):
    """PURE, picklable worker entry: extract the full AssemblyModel (per-part
    meshes + world positions + product tree) IN THIS PROCESS. Module-level so
    ``ProcessPoolExecutor`` can pickle it by qualified name. Raises plain
    ``ValueError`` (route -> 400) for a bad/native/unmeshable file."""
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    return extract_assembly_from_bytes(data, f"upload{suffix}")


async def submit_assembly_async(data: bytes, suffix: str):
    """Extract an ``AssemblyModel`` off the event loop, bounded by the route
    budget. Runs the CPU-bound multi-solid gmsh extraction in the shared spawn
    pool (so N assemblies don't serialize on the GIL/gmsh lock and the loop stays
    responsive), hard-bounded by ``ANALYSIS_TIMEOUT_SEC`` at the caller. On
    ``BrokenProcessPool`` (a worker died on adversarial gmsh input) we recycle the
    pool and extract THIS request in the default thread executor — the caller
    still gets a correct model, never a 500 (same contract as ``submit_async``).

    The per-assembly retry ladder (primary -> MeshAdapt-uniform -> +OCC-heal) runs
    WITHIN the worker call (``assembly_mesher._extract_with_ladder``); the caller's
    outer ``wait_for`` provides the wall-clock bound.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    if is_disabled():
        return await loop.run_in_executor(
            None, _extract_assembly_worker, data, suffix
        )
    pool = _get_pool()
    try:
        cfut = pool.submit(_extract_assembly_worker, data, suffix)
        return await asyncio.wrap_future(cfut)
    except BrokenProcessPool:
        logger.warning(
            "parse pool worker died during assembly extraction; recycling + "
            "in-thread fallback"
        )
        recycle_pool()
        return await loop.run_in_executor(
            None, _extract_assembly_worker, data, suffix
        )
