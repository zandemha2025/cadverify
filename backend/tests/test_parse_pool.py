"""Process-pool STEP/IGES parsing — correctness, safety, and concurrency.

CORRECTNESS IS SACRED on the untrusted CAD parse path: a process-pool parse MUST
produce a mesh byte-identical to the in-thread parse, and crash recovery must
stay isolated and bounded — never a hung server or in-process retry. These tests
prove:
  * pooled parse == in-thread parse, byte-for-byte (real spawn worker + pickle);
  * kill switch (PARSE_PROCESS_POOL_DISABLED=1) => in-thread, pool never created;
  * BrokenProcessPool => hard recycle + fresh killable subprocess retry;
  * the per-request triangle cap is still enforced on the pooled path (400);
  * the timeout still returns 504 and recycles the pool;
  * the mesh cache composes — a warm hit is served without touching the pool;
  * STL is parsed in-thread (never dispatched to the pool);
  * the process pool actually PARALLELIZES concurrent distinct parts.

gmsh-dependent tests importorskip; the rest use valid-magic STEP stubs + a
monkeypatched dispatch so they run fast without gmsh.
"""
from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi import HTTPException

from src.api import routes
from src.api.routes import _parse_mesh, _parse_mesh_async
from src.parsers import mesh_cache, parse_pool

CUBE_STEP = Path(__file__).parent / "assets" / "cube.step"


def _require_step():
    from src.parsers.step_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP parse path unavailable")


def _fake_step_bytes() -> bytes:
    """Bytes that pass validate_magic for .step (only the ISO-10303-21 prefix is
    checked) — lets the cap/timeout/cache/warm-hit tests exercise the pooled
    dispatch WITHOUT paying a real gmsh tessellation."""
    return b"ISO-10303-21;\nHEADER;\nENDSEC;\n" + b" " * 64


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Every test starts from default env, a fresh (uncreated) pool singleton,
    and an empty cache; and tears the pool down after so it can't leak."""
    for var in (
        "PARSE_PROCESS_POOL_DISABLED",
        "PARSE_POOL_WORKERS",
        "MESH_PARSE_CACHE_DISABLED",
        "MAX_TRIANGLES",
        "ANALYSIS_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(var, raising=False)
    parse_pool.shutdown()
    mesh_cache.get_cache().clear()
    yield
    parse_pool.shutdown()
    mesh_cache.get_cache().clear()


# ──────────────────────────────────────────────────────────────
# Config knobs
# ──────────────────────────────────────────────────────────────
def test_is_disabled_default_enabled(monkeypatch):
    assert parse_pool.is_disabled() is False
    monkeypatch.setenv("PARSE_PROCESS_POOL_DISABLED", "1")
    assert parse_pool.is_disabled() is True


def test_worker_count_bounds_and_override(monkeypatch):
    assert parse_pool.worker_count() >= 1
    monkeypatch.setenv("PARSE_POOL_WORKERS", "2")
    assert parse_pool.worker_count() == 2
    monkeypatch.setenv("PARSE_POOL_WORKERS", "0")
    assert parse_pool.worker_count() == 1  # floored
    monkeypatch.setenv("PARSE_POOL_WORKERS", "garbage")
    assert parse_pool.worker_count() >= 1  # falls back to derived default


def test_final_shutdown_blocks_late_prewarm_recreation():
    """A detached startup thread cannot recreate workers after ASGI shutdown."""
    parse_pool.startup()
    parse_pool.shutdown(final=True)

    assert parse_pool.prewarm(block=True) == 0
    assert parse_pool._POOL is None

    # A later test/server lifespan can explicitly reopen the lifecycle.
    parse_pool.startup()


def test_killed_shutdown_reaps_executor_resources_before_returning():
    """Killed workers cannot leave queue/semaphore cleanup to resource_tracker."""
    calls: list[tuple[str, object]] = []

    class _Process:
        def kill(self):
            calls.append(("kill", None))

    class _Executor:
        _processes = {1: _Process(), 2: _Process()}

        def shutdown(self, *, wait, cancel_futures):
            calls.append(("shutdown", (wait, cancel_futures)))

    parse_pool.startup()
    parse_pool._POOL = _Executor()
    parse_pool.shutdown(kill=True, final=True)

    assert calls == [
        ("kill", None),
        ("kill", None),
        ("shutdown", (True, True)),
    ]
    assert parse_pool._POOL is None
    parse_pool.startup()


# ──────────────────────────────────────────────────────────────
# Correctness: pooled parse is byte-identical to in-thread (the crux)
# ──────────────────────────────────────────────────────────────
def test_pool_matches_in_thread_byte_identical():
    _require_step()
    data = CUBE_STEP.read_bytes()
    m_thread, s = _parse_mesh(data, "cube.step")           # in-thread full path
    m_pool = parse_pool.submit_sync(data, ".step")          # real worker + pickle
    assert s == ".step"
    assert np.array_equal(m_thread.vertices, m_pool.vertices)
    assert np.array_equal(m_thread.faces, m_pool.faces)
    assert m_thread.volume == m_pool.volume                 # full precision
    assert np.array_equal(m_thread.bounds, m_pool.bounds)


@pytest.mark.asyncio
async def test_pooled_async_matches_in_thread():
    _require_step()
    data = CUBE_STEP.read_bytes()
    m_thread, _ = _parse_mesh(data, "cube.step")
    mesh_cache.get_cache().clear()
    m_pool, s = await _parse_mesh_async(data, "cube.step")  # default => pooled
    assert s == ".step"
    assert np.array_equal(m_thread.vertices, m_pool.vertices)
    assert np.array_equal(m_thread.faces, m_pool.faces)
    assert m_thread.volume == m_pool.volume


# ──────────────────────────────────────────────────────────────
# Kill switch: identical result, pool never created
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_kill_switch_bypasses_pool(monkeypatch):
    _require_step()
    monkeypatch.setenv("PARSE_PROCESS_POOL_DISABLED", "1")

    def _no_pool():
        raise AssertionError("pool must never be created when kill switch is on")

    monkeypatch.setattr(parse_pool, "_get_pool", _no_pool)

    data = CUBE_STEP.read_bytes()
    m_thread, _ = _parse_mesh(data, "cube.step")
    mesh_cache.get_cache().clear()
    m_async, s = await _parse_mesh_async(data, "cube.step")
    assert s == ".step"
    assert np.array_equal(m_thread.faces, m_async.faces)
    assert np.array_equal(m_thread.vertices, m_async.vertices)
    assert parse_pool._POOL is None  # singleton never built


# ──────────────────────────────────────────────────────────────
# Robust fallback: BrokenProcessPool -> hard recycle + isolated retry
# ──────────────────────────────────────────────────────────────
class _FakeBrokenPool:
    def submit(self, *args, **kwargs):
        raise BrokenProcessPool("simulated worker segfault on adversarial input")


@pytest.mark.asyncio
async def test_broken_pool_retries_in_isolated_subprocess(monkeypatch):
    recycled = {"n": 0, "kill": False}
    isolated = {"calls": []}
    expected = trimesh.creation.box(extents=(9, 8, 7))

    def _spy_recycle(*, kill=False):
        recycled["n"] += 1
        recycled["kill"] = kill

    async def _isolated_retry(data, suffix, idx, cap):
        isolated["calls"].append((data, suffix, idx, cap))
        return expected.copy()

    def _must_not_parse_in_api_process(*_args, **_kwargs):
        raise AssertionError("crash recovery must not parse in the API process")

    monkeypatch.setattr(parse_pool, "recycle_pool", _spy_recycle)
    monkeypatch.setattr(parse_pool, "_get_pool", lambda: _FakeBrokenPool())
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _isolated_retry)
    monkeypatch.setattr(parse_pool, "tessellate", _must_not_parse_in_api_process)

    mesh = await parse_pool.submit_async(b"untrusted-step", ".step")

    assert recycled == {"n": 1, "kill": True}
    assert len(isolated["calls"]) == 1
    assert isolated["calls"][0][0:3] == (b"untrusted-step", ".step", 0)
    assert np.array_equal(mesh.faces, expected.faces)


def test_sync_broken_pool_retries_in_isolated_subprocess(monkeypatch):
    expected = trimesh.creation.box()
    recycled = {"kill": False}
    calls = []

    monkeypatch.setattr(parse_pool, "_get_pool", lambda: _FakeBrokenPool())
    monkeypatch.setattr(
        parse_pool,
        "recycle_pool",
        lambda *, kill=False: recycled.update(kill=kill),
    )
    monkeypatch.setattr(
        parse_pool,
        "_run_tessellate_killable_sync",
        lambda data, suffix, cap: calls.append((data, suffix, cap)) or expected,
    )
    monkeypatch.setattr(
        parse_pool,
        "tessellate",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("crash recovery must not parse in the API process")
        ),
    )

    mesh = parse_pool.submit_sync(b"untrusted-step", ".step")

    assert mesh is expected
    assert recycled["kill"] is True
    assert calls and calls[0][0:2] == (b"untrusted-step", ".step")


@pytest.mark.asyncio
async def test_assembly_broken_pool_retries_in_isolated_subprocess(monkeypatch):
    expected = object()
    recycled = {"kill": False}
    calls = []

    async def _isolated_retry(data, suffix):
        calls.append((data, suffix))
        return expected

    monkeypatch.setattr(parse_pool, "_get_pool", lambda: _FakeBrokenPool())
    monkeypatch.setattr(
        parse_pool,
        "recycle_pool",
        lambda *, kill=False: recycled.update(kill=kill),
    )
    monkeypatch.setattr(parse_pool, "_run_assembly_killable", _isolated_retry)
    monkeypatch.setattr(
        parse_pool,
        "_extract_assembly_worker",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("crash recovery must not parse in the API process")
        ),
    )

    model = await parse_pool.submit_assembly_async(b"untrusted-step", ".step")

    assert model is expected
    assert recycled["kill"] is True
    assert calls == [(b"untrusted-step", ".step")]


# ──────────────────────────────────────────────────────────────
# Policy still enforced on the pooled path: triangle cap (400) + timeout (504)
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_triangle_cap_enforced_on_pooled_path(monkeypatch):
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    monkeypatch.setenv("MAX_TRIANGLES", "1")
    over_cap = trimesh.creation.box(extents=(10, 10, 10))  # 12 faces > 1

    async def _fake_submit(data, suffix):
        return over_cap.copy()

    monkeypatch.setattr(parse_pool, "submit_async", _fake_submit)

    with pytest.raises(HTTPException) as ei:
        await _parse_mesh_async(_fake_step_bytes(), "part.step")
    assert ei.value.status_code == 400
    assert "MAX_TRIANGLES" in str(ei.value.detail)


@pytest.mark.asyncio
async def test_timeout_returns_504_and_recycles(monkeypatch):
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.3")

    async def _slow_submit(data, suffix):
        await asyncio.sleep(5)  # far beyond the timeout
        return trimesh.creation.box()

    recycled = {"n": 0}
    monkeypatch.setattr(parse_pool, "submit_async", _slow_submit)
    monkeypatch.setattr(
        parse_pool,
        "recycle_pool",
        lambda *, kill=False: recycled.update(n=recycled["n"] + 1, kill=kill),
    )

    with pytest.raises(HTTPException) as ei:
        await _parse_mesh_async(_fake_step_bytes(), "part.step")
    assert ei.value.status_code == 504
    assert recycled["n"] >= 1, "timeout must recycle the pool to reclaim a runaway"
    assert recycled["kill"] is True, "timed-out untrusted CAD workers must be killed"


@pytest.mark.asyncio
async def test_cancelled_parse_hard_kills_pool(monkeypatch):
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)

    started = asyncio.Event()

    async def _never_finishes(_data, _suffix):
        started.set()
        await asyncio.Event().wait()

    recycled = {"kill": False}
    monkeypatch.setattr(parse_pool, "submit_async", _never_finishes)
    monkeypatch.setattr(
        parse_pool,
        "recycle_pool",
        lambda *, kill=False: recycled.update(kill=kill),
    )

    task = asyncio.create_task(_parse_mesh_async(_fake_step_bytes(), "part.step"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert recycled["kill"] is True


# ──────────────────────────────────────────────────────────────
# Cache composition + STL routing
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_warm_cache_hit_never_dispatches_to_pool(monkeypatch):
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    dispatched = {"n": 0}
    stub = trimesh.creation.box(extents=(20, 20, 20))

    async def _counting_submit(data, suffix):
        dispatched["n"] += 1
        return stub.copy()

    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit)

    data = _fake_step_bytes()
    m1, _ = await _parse_mesh_async(data, "part.step")   # MISS -> dispatch
    m2, _ = await _parse_mesh_async(data, "part.step")   # HIT -> no dispatch
    assert dispatched["n"] == 1, "warm hit must be served from cache, not the pool"
    assert np.array_equal(m1.faces, m2.faces)
    assert mesh_cache.get_cache().hits >= 1


@pytest.mark.asyncio
async def test_stl_parsed_in_thread_not_pooled(monkeypatch, cube_10mm, stl_bytes_of):
    async def _boom(*args, **kwargs):
        raise AssertionError("STL must never be dispatched to the process pool")

    monkeypatch.setattr(parse_pool, "submit_async", _boom)

    data = stl_bytes_of(cube_10mm)
    mesh, s = await _parse_mesh_async(data, "cube.stl")
    assert s == ".stl"
    assert len(mesh.faces) == len(cube_10mm.faces)


# ──────────────────────────────────────────────────────────────
# Concurrency: the whole point — pool parallelizes distinct parts
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pool_parallelizes_concurrent_distinct_parts(monkeypatch):
    """Real proof: K distinct heavy STEP parts parsed CONCURRENTLY finish faster
    on the process pool than on the thread executor (which serializes on the GIL
    AND the process-global gmsh lock). Detailed wall-clock numbers live in the
    committed artifact outputs/perf-proof/parse-concurrency-2026-07-09.txt."""
    _require_step()
    cpu = os.cpu_count() or 1
    if cpu < 3:
        pytest.skip(f"needs >=3 CPUs to show parallel STEP parsing (have {cpu})")

    from scripts.perf.step_parts import generate_distinct_parts

    parts = generate_distinct_parts(3)
    parse_pool.submit_sync(parts[0], ".step")  # warm: pay spawn once up front

    async def wall(disabled: bool) -> float:
        if disabled:
            monkeypatch.setenv("PARSE_PROCESS_POOL_DISABLED", "1")
        else:
            monkeypatch.delenv("PARSE_PROCESS_POOL_DISABLED", raising=False)
        mesh_cache.get_cache().clear()
        t = time.perf_counter()
        await asyncio.gather(
            *[_parse_mesh_async(d, f"p{i}.step") for i, d in enumerate(parts)]
        )
        return time.perf_counter() - t

    thread_wall = await wall(True)
    pool_wall = await wall(False)
    assert pool_wall < thread_wall * 0.75, (
        f"process pool ({pool_wall:.2f}s) should beat threads "
        f"({thread_wall:.2f}s) for 3 concurrent distinct parts"
    )
