"""A bent sheet with holes in its flanges still reads as bent sheet.

The bent-sheet reading needed a straight extrusion along the bend lines, so a
hole in a flange (or a slot, or a notch) made an L bracket "not sheet": no
sheet price and no sheet route for the most common bent part there is. Holes
and cut-outs straight through the sheet are allowed now; a blind pocket or a
boss (not one gauge) still isn't sheet.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.analysis.context import bent_sheet_geometry
from tests.test_bent_sheet import _report, _strip


def _cyl(r, h, at, axis):
    m = trimesh.creation.cylinder(radius=r, height=h, sections=64)
    turn = {"x": (0, 1, 0), "y": (1, 0, 0)}[axis]
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, turn))
    m.apply_translation(at)
    return m


def _bracket():
    """3 mm L bracket, 40 mm legs, 30 mm wide (bend line along Z)."""
    return _strip([(0, 40), (0, 0), (40, 0)])


def _with_holes():
    holes = [_cyl(3, 10, (20, 0, 15), "y"), _cyl(3, 10, (0, 20, 15), "x")]
    return trimesh.boolean.difference([_bracket(), *holes], engine="manifold")


def test_holes_in_both_flanges_keep_the_bent_sheet_reading():
    plain = bent_sheet_geometry(_bracket())
    holed = bent_sheet_geometry(_with_holes())
    assert holed is not None
    assert (holed.gauge_mm, holed.width_mm, holed.developed_mm, holed.bends) == pytest.approx(
        (plain.gauge_mm, plain.width_mm, plain.developed_mm, plain.bends), abs=1e-6)


def test_a_notch_at_the_end_of_a_flange_is_a_cut_out():
    notch = trimesh.creation.box(extents=(10, 10, 10))
    notch.apply_translation((40, 0, 0))
    bent = bent_sheet_geometry(trimesh.boolean.difference([_bracket(), notch], engine="manifold"))
    assert bent is not None and bent.bends == 1


def test_a_blind_pocket_or_a_boss_is_not_one_gauge():
    pocket = trimesh.creation.box(extents=(8, 2, 8))
    pocket.apply_translation((20, 1.5, 15))  # 1 mm deep into the 3 mm flange
    assert bent_sheet_geometry(trimesh.boolean.difference([_bracket(), pocket], engine="manifold")) is None
    boss = _cyl(4, 6, (20, 3, 15), "y")
    assert bent_sheet_geometry(trimesh.boolean.union([_bracket(), boss], engine="manifold")) is None


def test_the_holed_bracket_gets_a_sheet_metal_price():
    report, scores = _report(_with_holes())
    sheet = [e for e in report.estimates if e["process"] == "sheet_metal"]
    assert sheet, "no sheet-metal price for a holed bent bracket"
    assert report.routing["drivers"]["sheet_like"] is True


@pytest.mark.skipif(importlib.util.find_spec("gmsh") is None, reason="gmsh is not installed")
def test_a_step_of_the_holed_bracket_reads_the_same(tmp_path: Path):
    import gmsh

    from src.api.routes import _parse_mesh

    path = tmp_path / "holed-bracket.step"
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("bracket")
        occ = gmsh.model.occ
        base = occ.addBox(-1.5, -1.5, 0, 41.5, 3, 30)
        upright = occ.addBox(-1.5, -1.5, 0, 3, 41.5, 30)
        fused, _ = occ.fuse([(3, base)], [(3, upright)])
        h1 = occ.addCylinder(20, -5, 15, 0, 10, 0, 3)
        h2 = occ.addCylinder(-5, 20, 15, 10, 0, 0, 3)
        occ.cut(fused, [(3, h1), (3, h2)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    mesh, _ = _parse_mesh(path.read_bytes(), path.name)
    bent = bent_sheet_geometry(mesh)
    assert bent is not None
    assert (bent.gauge_mm, bent.width_mm, bent.bends) == pytest.approx((3.0, 30.0, 1), abs=1e-3)
