"""Async single-flight parse dedup — the concurrent-burst fix.

The Verify stage fires ``/validate`` + ``/validate/cost`` + ``/validate/preview-
mesh`` CONCURRENTLY on one upload. On a cold cache, without coordination each of
the three starts its OWN full tessellation on a 3-worker pool; for a periodic-
surface part (~30s) ``/validate/preview-mesh`` blows ANALYSIS_TIMEOUT_SEC and
504s. These tests prove the single-flight layer in ``_parse_mesh_async``:

  * N CONCURRENT parses of the SAME content => exactly ONE underlying parse;
  * every caller gets a VALID, INDEPENDENT (copy-on-hit) mesh — waiters never
    share a mutable object;
  * BEFORE (MESH_PARSE_CACHE_DISABLED=1) => N parses; AFTER (default) => 1 parse;
  * a shared parse FAILURE propagates identically to every awaiter (no hang);
  * DISTINCT content is NOT deduped (still parses in parallel).

These use a monkeypatched pool dispatch (a counting fake) so they run fast
without gmsh. Real wall-clock numbers on the NIST periodic part live in the
committed artifact outputs/perf-proof/single-flight-2026-07-09.txt.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi import HTTPException

from src.api import routes
from src.api.routes import _parse_mesh_async
from src.parsers import mesh_cache, parse_pool


def _fake_step_bytes(tag: bytes = b"") -> bytes:
    """Bytes that pass validate_magic for .step (only the ISO-10303-21 prefix is
    checked). ``tag`` makes the sha256 (and thus the single-flight key) unique."""
    return b"ISO-10303-21;\nHEADER;\nENDSEC;\n" + tag + b" " * 64


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "PARSE_PROCESS_POOL_DISABLED",
        "MESH_PARSE_CACHE_DISABLED",
        "MAX_TRIANGLES",
        "ANALYSIS_TIMEOUT_SEC",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    parse_pool.shutdown()
    mesh_cache.get_cache().clear()
    yield
    parse_pool.shutdown()
    mesh_cache.get_cache().clear()


def _counting_submit(calls: dict, hold: float, mesh: trimesh.Trimesh):
    """A fake pool dispatch that counts real parses and simulates the parse time.

    ``calls['peak']`` tracks the max concurrency, so we can also assert the parses
    do not serialize spuriously. Returns a distinct mesh copy each call."""
    calls.setdefault("n", 0)
    calls.setdefault("live", 0)
    calls.setdefault("peak", 0)

    async def _submit(data, suffix):
        calls["n"] += 1
        calls["live"] += 1
        calls["peak"] = max(calls["peak"], calls["live"])
        try:
            await asyncio.sleep(hold)
            return mesh.copy()
        finally:
            calls["live"] -= 1

    return _submit


# ──────────────────────────────────────────────────────────────
# The core assertion: 1 parse for N concurrent same-content requests
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_single_flight_one_parse_for_concurrent_same_content(monkeypatch):
    calls: dict = {}
    stub = trimesh.creation.box(extents=(20, 20, 20))
    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit(calls, 0.30, stub))

    data = _fake_step_bytes()
    N = 6
    results = await asyncio.gather(
        *[_parse_mesh_async(data, "part.step") for _ in range(N)]
    )

    assert calls["n"] == 1, f"exactly ONE underlying parse for {N} concurrent (got {calls['n']})"
    # every caller got a valid mesh, geometrically equal to the shared parse ...
    meshes = [m for m, _ in results]
    for m in meshes:
        assert isinstance(m, trimesh.Trimesh)
        assert np.array_equal(m.faces, stub.faces)
        assert np.array_equal(m.vertices, stub.vertices)
    # ... but each is an INDEPENDENT object (no two callers share a mesh).
    ids = {id(m) for m in meshes}
    assert len(ids) == N, "each caller must own a distinct mesh object"


@pytest.mark.asyncio
async def test_before_after_disabled_switch_controls_dedup(monkeypatch):
    """BEFORE (cache disabled): N concurrent = N parses (today's behavior).
    AFTER (default): N concurrent = 1 parse. The switch is a full escape hatch."""
    stub = trimesh.creation.box(extents=(12, 12, 12))
    N = 5

    # BEFORE: disabled => no coordination, N independent parses.
    monkeypatch.setenv("MESH_PARSE_CACHE_DISABLED", "1")
    before: dict = {}
    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit(before, 0.20, stub))
    data = _fake_step_bytes(b"switch")
    await asyncio.gather(*[_parse_mesh_async(data, "p.step") for _ in range(N)])
    assert before["n"] == N, f"disabled cache must not dedup (got {before['n']})"

    # AFTER: default (enabled) => single-flight, exactly one parse.
    monkeypatch.delenv("MESH_PARSE_CACHE_DISABLED", raising=False)
    mesh_cache.get_cache().clear()
    after: dict = {}
    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit(after, 0.20, stub))
    await asyncio.gather(*[_parse_mesh_async(data, "p.step") for _ in range(N)])
    assert after["n"] == 1, f"single-flight must dedup to one parse (got {after['n']})"


@pytest.mark.asyncio
async def test_waiters_get_independent_mutable_copies(monkeypatch):
    """Copy-on-hit under single-flight: mutating one caller's mesh must not
    corrupt any other caller's mesh nor the shared parse."""
    calls: dict = {}
    stub = trimesh.creation.box(extents=(10, 10, 10))
    baseline_vol = float(stub.volume)
    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit(calls, 0.15, stub))

    data = _fake_step_bytes(b"mutate")
    results = await asyncio.gather(
        *[_parse_mesh_async(data, "p.step") for _ in range(4)]
    )
    assert calls["n"] == 1
    meshes = [m for m, _ in results]
    meshes[0].apply_scale(25.4)  # one caller mutates its copy
    assert not np.isclose(float(meshes[0].volume), baseline_vol)
    for m in meshes[1:]:
        assert np.isclose(float(m.volume), baseline_vol), "other callers must be pristine"


@pytest.mark.asyncio
async def test_shared_failure_propagates_to_all_awaiters(monkeypatch):
    """A parse that FAILS must fail every concurrent caller with the same mapped
    error — a waiter sees the exception, it never hangs."""
    calls = {"n": 0}

    async def _failing_submit(data, suffix):
        calls["n"] += 1
        await asyncio.sleep(0.10)
        raise ValueError("unreadable geometry")  # route maps ValueError -> 400

    monkeypatch.setattr(parse_pool, "submit_async", _failing_submit)

    data = _fake_step_bytes(b"fail")
    outcomes = await asyncio.gather(
        *[_parse_mesh_async(data, "p.step") for _ in range(4)],
        return_exceptions=True,
    )
    assert calls["n"] == 1, "only one shared parse ran before failing"
    assert all(isinstance(o, HTTPException) and o.status_code == 400 for o in outcomes), (
        f"every awaiter must see the same mapped failure: {outcomes}"
    )


@pytest.mark.asyncio
async def test_timeout_504_shared_across_concurrent_callers(monkeypatch):
    """The 504-on-timeout contract survives single-flight: if the shared parse
    exceeds ANALYSIS_TIMEOUT_SEC, every concurrent caller gets the 504."""
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.3")
    calls = {"n": 0}

    async def _slow_submit(data, suffix):
        calls["n"] += 1
        await asyncio.sleep(5)  # far beyond the timeout
        return trimesh.creation.box()

    monkeypatch.setattr(parse_pool, "submit_async", _slow_submit)
    monkeypatch.setattr(parse_pool, "recycle_pool", lambda *a, **k: None)

    data = _fake_step_bytes(b"timeout")
    outcomes = await asyncio.gather(
        *[_parse_mesh_async(data, "p.step") for _ in range(3)],
        return_exceptions=True,
    )
    assert calls["n"] == 1, "one shared parse timed out for all callers"
    assert all(isinstance(o, HTTPException) and o.status_code == 504 for o in outcomes)


@pytest.mark.asyncio
async def test_distinct_content_not_deduped(monkeypatch):
    """Single-flight keys on content: DISTINCT parts must each parse (in parallel),
    never collapsed into one."""
    calls: dict = {}
    stub = trimesh.creation.box(extents=(8, 8, 8))
    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit(calls, 0.20, stub))

    datas = [_fake_step_bytes(f"d{i}".encode()) for i in range(3)]
    await asyncio.gather(*[_parse_mesh_async(d, "p.step") for d in datas])
    assert calls["n"] == 3, "distinct content must not be deduped"
    assert calls["peak"] == 3, "distinct parts must still run concurrently (not serialized)"


@pytest.mark.asyncio
async def test_single_flight_prevents_contention_timeout(monkeypatch):
    """The reported bug, faithfully reproduced: with parses SERIALIZED on a
    scarce pool (modelled by a 1-permit lock), 3 concurrent same-content requests
    would run back-to-back and the later ones (preview-mesh) blow
    ANALYSIS_TIMEOUT_SEC -> 504. Single-flight collapses them to ONE parse that
    finishes within budget, so EVERY caller (incl. preview-mesh) gets a 200."""
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.8")
    monkeypatch.setattr(parse_pool, "recycle_pool", lambda *a, **k: None)
    stub = trimesh.creation.box(extents=(18, 18, 18))
    worker = asyncio.Lock()  # a single pool worker: parses cannot overlap
    calls = {"n": 0}

    async def _one_worker_submit(data, suffix):
        calls["n"] += 1
        async with worker:            # serialize like a 1-worker pool
            await asyncio.sleep(0.5)  # one parse ~0.5s (< the 0.8s budget)
            return stub.copy()

    data = _fake_step_bytes(b"contend")

    # BEFORE: no coordination -> 3 serialized parses; the 2nd/3rd exceed budget.
    monkeypatch.setenv("MESH_PARSE_CACHE_DISABLED", "1")
    monkeypatch.setattr(parse_pool, "submit_async", _one_worker_submit)
    before = await asyncio.gather(
        *[_parse_mesh_async(data, "p.step") for _ in range(3)], return_exceptions=True
    )
    n_504 = sum(1 for o in before if isinstance(o, HTTPException) and o.status_code == 504)
    assert calls["n"] == 3, "no dedup: three independent parses contend"
    assert n_504 >= 1, f"serialized parses must blow the budget (504); got {before}"

    # AFTER: single-flight -> one shared parse within budget -> all callers 200.
    monkeypatch.delenv("MESH_PARSE_CACHE_DISABLED", raising=False)
    mesh_cache.get_cache().clear()
    calls["n"] = 0
    after = await asyncio.gather(
        *[_parse_mesh_async(data, "p.step") for _ in range(3)], return_exceptions=True
    )
    assert calls["n"] == 1, "single-flight: exactly one shared parse"
    assert all(isinstance(o, tuple) for o in after), (
        f"every caller (incl. preview-mesh) must succeed, no 504: {after}"
    )


@pytest.mark.asyncio
async def test_real_periodic_part_shares_one_parse(monkeypatch):
    """gmsh-gated e2e on the actual NIST periodic part the Verify burst hits:
    3 concurrent parses (validate + cost + preview-mesh) share ONE tessellation
    and every caller gets a valid, independent mesh. Real numbers live in
    outputs/perf-proof/single-flight-2026-07-09.txt."""
    from src.parsers.step_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP parse path unavailable")
    part = Path(
        "/home/user/cadverify/data/real-corpus/NIST-PMI-STEP-Files/"
        "AP203 geometry only/nist_ctc_05_asme1_rd.stp"
    )
    if not part.exists():
        pytest.skip("NIST periodic corpus part not present")

    calls = {"n": 0}
    orig = parse_pool.submit_async

    async def _counting(data, suffix):
        calls["n"] += 1
        return await orig(data, suffix)

    monkeypatch.setattr(parse_pool, "submit_async", _counting)

    data = part.read_bytes()
    results = await asyncio.gather(
        *[_parse_mesh_async(data, "nist.step") for _ in range(3)]
    )
    assert calls["n"] == 1, f"3 concurrent same-content = ONE parse (got {calls['n']})"
    meshes = [m for m, _ in results]
    assert len({id(m) for m in meshes}) == 3, "each caller owns an independent mesh"
    f0 = len(meshes[0].faces)
    assert f0 > 0 and all(len(m.faces) == f0 for m in meshes)


@pytest.mark.asyncio
async def test_warm_hit_shortcuts_before_single_flight(monkeypatch):
    """Once the cache is warm, a request short-circuits WITHOUT registering a
    single-flight Task and without dispatching to the pool (one copy served)."""
    calls: dict = {}
    stub = trimesh.creation.box(extents=(15, 15, 15))
    monkeypatch.setattr(parse_pool, "submit_async", _counting_submit(calls, 0.05, stub))

    data = _fake_step_bytes(b"warm")
    await _parse_mesh_async(data, "p.step")   # cold: one parse, populates cache
    assert calls["n"] == 1
    await asyncio.gather(*[_parse_mesh_async(data, "p.step") for _ in range(4)])
    assert calls["n"] == 1, "warm hits must not re-parse"
    assert mesh_cache.get_cache().hits >= 1
