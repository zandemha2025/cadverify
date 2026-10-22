"""STEP/IGES tessellation fits the engine's analysis face budget.

A part whose first-pass mesh is over MAX_ANALYSIS_FACES is re-tessellated from
its B-rep instead of being decimated by the engine: small fillets stop
spreading their tiny segment size across the flat walls next to them, and
only if that isn't enough the flat-face size grows (at most 2x). Every part
under the budget keeps its first-pass mesh byte for byte.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.parsers import step_mesher as sm

ASSETS = Path(__file__).parent / "assets"


def _rounded_pocket(path: Path, radius: float = 0.5) -> Path:
    """A 60 x 40 x 12 mm block with a 48 x 28 x 8 mm pocket, inside edges filleted."""
    import gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("rounded-pocket")
        occ = gmsh.model.occ
        block = occ.addBox(0, 0, 0, 60, 40, 12)
        tool = occ.addBox(6, 6, 4, 48, 28, 12)
        occ.synchronize()
        surfaces = gmsh.model.getBoundary([(3, tool)], oriented=False)
        edges = sorted({abs(t) for d, t in gmsh.model.getBoundary(surfaces, combined=False, oriented=False) if d == 1})
        rounded = occ.fillet([tool], edges, [radius])
        occ.cut([(3, block)], rounded)
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def _mesh(path: Path, segments: int = 60) -> trimesh.Trimesh:
    verts, faces = sm._tessellate_once(str(path), None, sm._CURVATURE_PTS, False, target_diag_segments=segments)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=True)


def _refit_record(caplog) -> dict:
    record = next(r for r in caplog.records if "refit" in r.getMessage())
    # logging unpacks a lone mapping argument into record.args itself
    return record.args if isinstance(record.args, dict) else record.args[0]


def _sharp_concave(mesh: trimesh.Trimesh) -> int:
    angles = np.degrees(mesh.face_adjacency_angles)
    return int(((angles > 30.0) & ~mesh.face_adjacency_convex).sum())


def test_a_part_under_the_budget_keeps_its_mesh_byte_for_byte(monkeypatch):
    data = (ASSETS / "plate-with-boss.step").read_bytes()
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1")
    fitted = sm.step_to_trimesh_from_bytes(data, "plate-with-boss.step")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "0")
    plain = sm.step_to_trimesh_from_bytes(data, "plate-with-boss.step")
    assert len(fitted.faces) < 250_000
    assert np.array_equal(fitted.vertices, plain.vertices)
    assert np.array_equal(fitted.faces, plain.faces)


def test_small_fillets_no_longer_inflate_the_flat_walls(tmp_path, monkeypatch, caplog):
    part = _rounded_pocket(tmp_path / "rounded-pocket.step")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "0")
    first = _mesh(part)
    budget = len(first.faces) - 1
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1")
    monkeypatch.setenv("MAX_ANALYSIS_FACES", str(budget))
    with caplog.at_level(logging.INFO, logger="cadverify.step_mesher"):
        fitted = _mesh(part)
    assert len(fitted.faces) <= budget
    assert fitted.is_watertight
    # Exact geometry, not an approximation: same volume as the first pass.
    assert fitted.volume == pytest.approx(first.volume, rel=1e-3)
    # The fillets keep their curvature sizing: they read exactly as smooth as before.
    assert _sharp_concave(fitted) == _sharp_concave(first)
    passes = _refit_record(caplog)["passes"]
    assert passes[1]["extend_from_boundary"] == 0
    assert passes[1]["size_max"] == passes[0]["size_max"], "pass 2 keeps the flat-face size"


def test_coarsening_is_bounded_and_the_fewest_faces_win(tmp_path, monkeypatch, caplog):
    part = _rounded_pocket(tmp_path / "rounded-pocket.step")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1")
    monkeypatch.setenv("MAX_ANALYSIS_FACES", "1000")  # unreachable at 2x
    # A 1,000-face budget is far under this part's predicted first pass, which
    # would mesh its flat faces coarse up front (test_step_thin_walls.py); this
    # test is about the refit after a first pass.
    monkeypatch.setattr(sm, "_PREDICT_OVER", float("inf"))
    with caplog.at_level(logging.INFO, logger="cadverify.step_mesher"):
        fitted = _mesh(part)
    fit = _refit_record(caplog)
    first, *_rest, last = fit["passes"]
    assert not fit["fits"]
    assert last["size_max"] <= sm._FIT_MAX_COARSEN * first["size_max"] + 1e-12
    assert len(fitted.faces) == last["faces"] < first["faces"]
    assert fitted.is_watertight, "the engine still gets a closed solid to decimate"


def test_a_refit_that_would_run_past_the_rung_cap_is_not_started(tmp_path, monkeypatch, caplog):
    part = _rounded_pocket(tmp_path / "rounded-pocket.step")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "0")
    first = _mesh(part)
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1")
    monkeypatch.setenv("MAX_ANALYSIS_FACES", str(len(first.faces) - 1))
    monkeypatch.setattr(sm, "_fit_time_cap_sec", lambda: 0.0)
    with caplog.at_level(logging.INFO, logger="cadverify.step_mesher"):
        kept = _mesh(part)
    fit = _refit_record(caplog)
    assert fit["stopped"] == "time" and len(fit["passes"]) == 1
    assert np.array_equal(kept.faces, first.faces), "the first pass is kept; the engine decimates as before"


def test_the_time_cap_follows_the_pool_rung_cap(monkeypatch):
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "60")
    assert sm._fit_time_cap_sec() == pytest.approx(0.8 * 24.0)
    assert sm._fit_triangle_cap() == int(sm._FIT_TRIANGLES_PER_SEC * 0.8 * 24.0)
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "20")
    assert sm._fit_time_cap_sec() == pytest.approx(0.8 * 8.0)
    assert sm._fit_triangle_cap() == int(sm._FIT_TRIANGLES_PER_SEC * 0.8 * 8.0)


def test_a_busy_machine_gets_the_same_refit(tmp_path, monkeypatch, caplog):
    """The refit's gate counts triangles: a part gets the same passes whatever the
    clocks say. Every clock here jumps 1,000 s at each reading (a box far busier than
    any cap), and the refit is still made, pass for pass and triangle for triangle."""
    import itertools
    import time

    part = _rounded_pocket(tmp_path / "rounded-pocket.step")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "0")
    first = _mesh(part)
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1")
    monkeypatch.setenv("MAX_ANALYSIS_FACES", str(len(first.faces) - 1))
    with caplog.at_level(logging.INFO, logger="cadverify.step_mesher"):
        calm = _mesh(part)
    calm_fit = _refit_record(caplog)
    caplog.clear()
    for name in ("perf_counter", "monotonic", "thread_time", "process_time", "time"):
        ticks = itertools.count(1_000.0, 1_000.0)
        monkeypatch.setattr(time, name, lambda ticks=ticks: next(ticks))
    with caplog.at_level(logging.INFO, logger="cadverify.step_mesher"):
        busy = _mesh(part)
    busy_fit = _refit_record(caplog)
    monkeypatch.undo()
    assert len(calm_fit["passes"]) >= 2 and calm_fit["fits"], calm_fit
    assert busy_fit == calm_fit
    assert np.array_equal(busy.faces, calm.faces) and np.array_equal(busy.vertices, calm.vertices)


def test_switch_off_restores_the_first_pass(tmp_path, monkeypatch):
    part = _rounded_pocket(tmp_path / "rounded-pocket.step")
    monkeypatch.setenv("MAX_ANALYSIS_FACES", "1000")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "0")
    off = _mesh(part)
    monkeypatch.delenv("MAX_ANALYSIS_FACES")
    on_under_budget = _mesh(part)
    assert np.array_equal(off.faces, on_under_budget.faces)


def test_a_rounded_studio_enclosure_is_checked_without_decimation():
    """The case that made fixes unverifiable: 1 mm inside fillets on the Studio enclosure."""
    import gmsh  # noqa: F401  (the generator and fillet both need it)

    from src.api.routes import _parse_mesh, _run_cost_engine_ctx
    from src.designs.generator import _build_shape
    from src.designs.schema import validate_design_plan
    from src.fixes.brep_fixes import run_fix

    plan = validate_design_plan({"kind": "enclosure", "width_mm": 120, "depth_mm": 80,
                                 "height_mm": 40, "wall_thickness_mm": 0.6})
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "enclosure.step"
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("enclosure")
            _build_shape(gmsh, plan)
            gmsh.model.occ.synchronize()
            gmsh.write(str(path))
        finally:
            gmsh.finalize()
        raw = path.read_bytes()
    rounded = run_fix("fillet_inside_corners", raw, ".step", {"radius_mm": 1.0})
    assert rounded.applied, rounded.reason
    mesh, _ = _parse_mesh(rounded.data, "enclosure-rounded.step")
    assert len(mesh.faces) <= 250_000
    result, _m, ctx = _run_cost_engine_ctx(mesh, "enclosure-rounded.step")
    assert not (ctx.metadata or {}).get("decimation")
    codes = {i.code for s in result.process_scores for i in s.issues} | {i.code for i in result.universal_issues}
    assert "DECIMATED_MESH" not in codes
    assert not {"SHARP_INTERNAL_CORNERS", "MISSING_FILLETS"} & codes
    # The 0.6 mm walls are still measured, and still too thin for milling.
    assert "THIN_WALL" in codes and "WALL_UNIFORMITY_UNAVAILABLE" not in codes
