"""Milling's setup proof reads a STEP's round walls as walls, like the STL's.

ScaleCAD meshes a STEP's bore or turned diameter with an unstructured
triangulation: a facet between nodes at different heights and angles cuts the
chord and leans a few degrees off the axis. The setup proof read those facets
as faces pointing down (re-entrant), so the STEP of a block with a blind hole,
or of a stepped shaft, got "a setup without re-entrant surfaces could not be
verified" while the STL of the same part (straight facets) did not. A facet
leaning by tessellation alone is now a wall; a real undercut still isn't.
"""
from pathlib import Path

import pytest

gmsh = pytest.importorskip("gmsh")


def _step(tmp_path: Path, name: str, build) -> bytes:
    path = tmp_path / f"{name}.step"
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(name)
        build(gmsh.model.occ)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path.read_bytes()


def _cnc_codes(data: bytes, filename: str) -> set[str]:
    from src.api.routes import _parse_mesh, _run_cost_engine_ctx

    mesh, _ = _parse_mesh(data, filename)
    result, _m, _ctx = _run_cost_engine_ctx(mesh, filename)
    return {i.code for s in result.process_scores if s.process.value == "cnc_3axis" for i in s.issues}


def _blind_hole(occ):
    block = occ.addBox(0, 0, 0, 10, 10, 35)
    hole = occ.addCylinder(5, 5, 5, 0, 0, 31, 0.5)
    occ.cut([(3, block)], [(3, hole)])


def _stepped_shaft(occ):
    a = occ.addCylinder(0, 0, 0, 0, 0, 30, 15)
    b = occ.addCylinder(0, 0, 30, 0, 0, 30, 10)
    c = occ.addCylinder(0, 0, 60, 0, 0, 30, 5)
    occ.fuse([(3, a)], [(3, b), (3, c)])


def _dovetail_hole(occ):
    # A blind hole that widens 5 degrees on a side as it goes down: a real undercut.
    block = occ.addBox(0, 0, 0, 30, 30, 30)
    cone = occ.addCone(15, 15, 10, 0, 0, 21, 6.0, 6.0 - 21 * 0.0875)
    occ.cut([(3, block)], [(3, cone)])


@pytest.mark.parametrize("name, build", [("blind-hole", _blind_hole), ("stepped-shaft", _stepped_shaft)])
def test_a_step_of_round_walls_proves_its_setup(tmp_path, name, build):
    codes = _cnc_codes(_step(tmp_path, name, build), f"{name}.step")
    assert "SETUP_ACCESS_UNVERIFIED" not in codes


def test_a_real_undercut_is_still_unverified(tmp_path):
    codes = _cnc_codes(_step(tmp_path, "dovetail", _dovetail_hole), "dovetail.step")
    assert "SETUP_ACCESS_UNVERIFIED" in codes
