"""STEP and STL of the same part agree on its walls (engine audit W9, W10).

W9: a 40 x 40 x 30 mm open box with 0.5 mm walls tessellated to 286,290
triangles as STEP (flat faces at diag / 200), took ~28 s, went past the refit
time cap and was vertex-clustered by the engine: the 0.5 mm walls vanished and
every thin-wall check passed while the STL failed them. Its face count is now
predicted from the B-rep and flat faces are meshed coarse instead.

W10: a 10 x 10 x 30 mm block with a 1 mm through-hole (minimum wall 4.5 mm)
read 0.777 mm as STEP: a tessellated facet at the hole's rim, tilted 3 degrees,
sent its ray out through the bottom face 0.78 mm away. Such grazing exits are
now left unmeasured instead of read as a wall.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from src.parsers import step_mesher as sm


def _write_step(path: Path, build) -> Path:
    import gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(path.stem)
        build(gmsh.model.occ)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def _open_box(occ):
    occ.cut([(3, occ.addBox(0, 0, 0, 40, 40, 30))], [(3, occ.addBox(0.5, 0.5, 0.5, 39, 39, 30))])


def _deep_hole(occ):
    occ.cut([(3, occ.addBox(0, 0, 0, 10, 10, 30))], [(3, occ.addCylinder(5, 5, -1, 0, 0, 32, 0.5))])


def _analyse(data: bytes, name: str):
    from src.api.routes import _parse_mesh, _run_cost_engine_ctx

    mesh, _ = _parse_mesh(data, name)
    result, _m, ctx = _run_cost_engine_ctx(mesh, name)
    return mesh, result, ctx


def _scores(result):
    return {s.process.value: s for s in result.process_scores}


@pytest.mark.skipif(not sm.is_step_supported(), reason="gmsh not installed")
def test_a_half_millimetre_open_box_keeps_its_walls_as_step(tmp_path, monkeypatch, caplog):
    import logging

    monkeypatch.setenv("MESH_PARSE_CACHE_DISABLED", "1")
    step = _write_step(tmp_path / "open-box.step", _open_box)
    with caplog.at_level(logging.INFO, logger="cadverify.step_mesher"):
        mesh, result, ctx = _analyse(step.read_bytes(), "open-box.step")
    record = next(r for r in caplog.records if "refit" in r.getMessage())
    fit = record.args if isinstance(record.args, dict) else record.args[0]
    assert fit["flat_coarse"] and fit["fits"]
    assert fit["passes"][0]["predicted_first_pass"] > 250_000  # the old first pass, never meshed
    assert len(mesh.faces) < 20_000 and mesh.is_watertight
    assert mesh.volume == pytest.approx(40 * 40 * 30 - 39 * 39 * 29.5, rel=1e-6)
    assert not ctx.metadata.get("decimation")
    assert "DECIMATED_MESH" not in {i.code for i in result.universal_issues}
    scores = _scores(result)
    fdm = next(i for i in scores["fdm"].issues if i.code == "THIN_WALL")
    assert fdm.severity.value == "error" and fdm.measured_value == pytest.approx(0.5, abs=1e-3)
    assert scores["fdm"].verdict == "fail"
    assert scores["wire_edm"].verdict == "fail"  # the floor closes the cavity


@pytest.mark.skipif(not sm.is_step_supported(), reason="gmsh not installed")
def test_a_part_predicted_under_the_budget_is_meshed_exactly_as_before(tmp_path, monkeypatch):
    step = _write_step(tmp_path / "hole.step", _deep_hole)
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "1")
    fitted = sm.step_to_trimesh_from_bytes(step.read_bytes(), "hole.step")
    monkeypatch.setenv("STEP_MESH_FIT_ANALYSIS_BUDGET", "0")
    plain = sm.step_to_trimesh_from_bytes(step.read_bytes(), "hole.step")
    assert np.array_equal(fitted.faces, plain.faces) and np.array_equal(fitted.vertices, plain.vertices)


@pytest.mark.skipif(not sm.is_step_supported(), reason="gmsh not installed")
def test_a_step_hole_rim_does_not_read_as_a_thin_wall(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_PARSE_CACHE_DISABLED", "1")
    step = _write_step(tmp_path / "deep-hole.step", _deep_hole)
    mesh, result, ctx = _analyse(step.read_bytes(), "deep-hole.step")
    measured = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert measured.min() == pytest.approx(4.5, abs=0.02)  # hole wall to the outside
    scores = _scores(result)
    assert not [i for i in scores["investment_casting"].issues if i.code.startswith("THIN_WALL")]
    assert scores["investment_casting"].verdict != "fail"
