"""The assembly reader's retry ladder has the same per-rung CPU caps as a single part's.

An assembly's bodies are meshed in one gmsh call, so one body that grinds held the
whole file: nist_ctc05's periodic surface 103 takes rung 0 (gmsh's default
algorithm) 220 s before it fails, and an assembly holding that body answered 504
at the route's 60 s on the probe, the 3D view and the analysis, every retry.
``parse_pool.submit_assembly_async`` now runs rung 0 on the shared pool and the
recovery rungs each in their own killable subprocess, each bounded by its share of
the budget in the worker's CPU seconds (``_rung_caps``); running out of the
ladder's wall time is busy, never a reason to advance.

The fast tests stand in for the rungs; the slow one drives a real two-body
assembly (a box and the ctc05 solid) through the real caps.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.parsers import parse_pool

ASSETS = Path(__file__).parent / "assets"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in ("PARSE_PROCESS_POOL_DISABLED", "PARSE_POOL_WORKERS", "ANALYSIS_TIMEOUT_SEC"):
        monkeypatch.delenv(var, raising=False)


def _model(parts: int = 2):
    import trimesh

    meshes = [trimesh.creation.box(extents=(10, 10, 10)) for _ in range(parts)]
    return SimpleNamespace(part_count=parts, parts=[SimpleNamespace(mesh=m) for m in meshes])


# ── The ladder, rungs stood in for ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_rung_that_uses_its_cpu_cap_moves_the_assembly_to_the_next_rung(monkeypatch):
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "3")
    budget = parse_pool._budget_sec()
    caps = parse_pool._rung_caps(budget, 3)
    seen = []

    async def _grind(data, suffix, cap, loop, *, worker=None, extra=()):
        seen.append((0, cap, worker, extra))
        await asyncio.sleep(cap)  # what a grinding rung does: use its cap
        raise parse_pool._RungTimeout(f"rung 0 used its {cap:.0f}s of CPU")

    async def _recover(data, suffix, idx, cap, *, worker=None, extra=()):
        seen.append((idx, cap, worker, extra))
        return _model()

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _grind)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _recover)
    start = time.perf_counter()
    model = await parse_pool.submit_assembly_async(b"step", ".step", mesh_single_part=False)
    took = time.perf_counter() - start

    assert model.part_count == 2
    assert [s[0] for s in seen] == [0, 1]
    assert [s[1] for s in seen] == caps[:2]
    assert all(s[2] is parse_pool._assembly_rung_worker and s[3] == (False,) for s in seen)
    assert caps[0] * 0.9 <= took < budget


@pytest.mark.asyncio
async def test_every_rung_capped_is_the_honest_error_within_the_budget(monkeypatch):
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "3")
    budget = parse_pool._budget_sec()

    async def _grind0(data, suffix, cap, loop, **_kw):
        await asyncio.sleep(cap)
        raise parse_pool._RungTimeout(f"rung 0 used its {cap:.0f}s of CPU")

    async def _grind(data, suffix, idx, cap, **_kw):
        await asyncio.sleep(cap)
        raise parse_pool._RungTimeout(f"rung {idx} used its {cap:.0f}s of CPU")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _grind0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _grind)
    start = time.perf_counter()
    with pytest.raises(ValueError) as caught:
        await parse_pool.submit_assembly_async(b"step", ".step")
    assert str(caught.value).startswith("Could not tessellate this assembly [rung 2 used its")
    assert str(caught.value).endswith("(all 3 mesh strategies failed).")
    assert time.perf_counter() - start < budget


@pytest.mark.asyncio
async def test_out_of_wall_time_is_busy_and_never_advances(monkeypatch):
    calls = []

    async def _starved(data, suffix, cap, loop, **_kw):
        calls.append(0)
        raise parse_pool._RungStarved(0, used=3.0, cap=cap)

    async def _never(*_a, **_kw):
        calls.append("next")
        raise AssertionError("time must not advance the ladder")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _starved)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _never)
    with pytest.raises(parse_pool.ParseBusy):
        await parse_pool.submit_assembly_async(b"step", ".step")
    assert calls == [0]


@pytest.mark.asyncio
async def test_an_unreadable_file_stops_the_ladder_with_the_same_words(monkeypatch):
    from src.parsers.step_mesher import _StepReadError

    async def _unreadable(data, suffix, cap, loop, **_kw):
        raise _StepReadError("OCC could not read it")

    async def _never(*_a, **_kw):
        raise AssertionError("no strategy reads an unreadable file")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _unreadable)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _never)
    with pytest.raises(ValueError, match=r"^Could not read STEP/IGES geometry \(not a valid/supported file\)\.$"):
        await parse_pool.submit_assembly_async(b"step", ".step")


@pytest.mark.asyncio
async def test_an_unreadable_embedded_tessellation_is_answered_as_before(monkeypatch):
    async def _ap242(data, suffix, cap, loop, **_kw):
        raise parse_pool._FinalRungError(ValueError("The embedded tessellation is empty."))

    async def _never(*_a, **_kw):
        raise AssertionError("another strategy can't read embedded tessellation")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _ap242)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _never)
    with pytest.raises(ValueError, match="^The embedded tessellation is empty.$"):
        await parse_pool.submit_assembly_async(b"step", ".step")


@pytest.mark.asyncio
async def test_a_native_cad_file_is_refused_before_any_worker(monkeypatch):
    monkeypatch.setattr(parse_pool, "_get_pool", lambda: pytest.fail("no worker for a native file"))
    with pytest.raises(ValueError):
        await parse_pool.submit_assembly_async(b"data", ".sldasm")


def test_the_route_answers_busy_when_the_ladder_runs_out_of_time(monkeypatch):
    from fastapi import HTTPException

    from src.api import routes

    async def _busy(data, suffix, *, mesh_single_part=True):
        raise parse_pool.ParseBusy("ScaleCAD is busy; this part ran out of time before its meshing finished.")

    monkeypatch.setattr(parse_pool, "submit_assembly_async", _busy)
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    data = (ASSETS / "cube.step").read_bytes()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes._extract_assembly_async(data, "cube.step"))
    assert caught.value.status_code == 429 and caught.value.detail["code"] == "server_busy"


# ── A real assembly whose periodic body grinds on rung 0 ─────────────────────
@pytest.mark.slow
@pytest.mark.asyncio
async def test_a_two_body_assembly_with_a_grinding_body_meshes_on_rung_1(monkeypatch, tmp_path, caplog):
    """A box and the nist_ctc05 solid in one STEP file. Rung 0 grinds on the
    periodic surface and is killed at its CPU cap (24 s of the worker's CPU at the
    60 s budget); rung 1 meshes both bodies within its own cap (15 s). So the
    ladder's CPU is bounded by the two caps, whatever the load; before, rung 0 alone
    ran 220 s and the route answered 504."""
    from src.parsers.step_mesher import is_step_supported

    if not is_step_supported():
        pytest.skip("gmsh not installed")
    import gmsh

    path = tmp_path / "box-and-ctc05.step"
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.importShapes(str(ASSETS / "nist_periodic_ctc05.stp"))
        gmsh.model.occ.addBox(-200, -200, -200, 20, 20, 20)
        gmsh.model.occ.synchronize()
        assert len(gmsh.model.getEntities(3)) == 2
        gmsh.write(str(path))
    finally:
        gmsh.finalize()

    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "60")
    budget = parse_pool._budget_sec()
    caps = parse_pool._rung_caps(budget, 3)
    parse_pool.shutdown()
    caplog.set_level(logging.INFO, logger="cadverify.parse_pool")
    start = time.perf_counter()
    try:
        model = await parse_pool.submit_assembly_async(path.read_bytes(), ".step")
    finally:
        parse_pool.shutdown()
    took = time.perf_counter() - start

    assert (model.kind, model.part_count) == ("assembly", 2)
    assert all(p.mesh is not None and len(p.mesh.faces) > 0 for p in model.parts)
    text = caplog.text
    assert "assembly ladder rung 0 hit its CPU cap" in text, text
    assert "recovered on retry rung 'meshadapt-uniform'" in text, text
    assert caps[0] == 24.0 and caps[1] == 15.0
    assert took < budget, took
