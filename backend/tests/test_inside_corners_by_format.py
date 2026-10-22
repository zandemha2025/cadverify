"""Milling's sharp-inside-corner finding reads the shape, not its triangles.

The rule used to count sharp concave MESH edges and fire at ten: a STEP
tessellated finely along an L bracket's one inside edge fired while the STL of
the same bracket (one triangle edge) didn't, and the facets of a coarse STL's
round hole fired while the STEP's didn't. Now it counts corners between walls,
where a cutter leaves its radius, and skips corners a flat-ended cutter cuts
sharp (one face is the floor of the cut) and the facets of curved surfaces.
"""
import math

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_internal_radii


def _box(ext, at=(0.0, 0.0, 0.0)):
    m = trimesh.creation.box(extents=ext)
    m.apply_translation(np.asarray(at, dtype=float) + np.asarray(ext, dtype=float) / 2.0)
    return m


def _corners(mesh):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    return check_internal_radii(ctx, 0.5, ProcessType.CNC_3AXIS)


def _fine(mesh, rounds=4):
    for _ in range(rounds):
        mesh = mesh.subdivide()
    return mesh


def _cup():
    """40 x 40 x 30 open-top box, 2 mm walls: four inside corners between walls."""
    return trimesh.boolean.difference([_box((40, 40, 30)), _box((36, 36, 30), at=(2, 2, 2))], engine="manifold")


def _lbracket():
    return trimesh.boolean.union([_box((40, 30, 3)), _box((40, 3, 40))], engine="manifold")


def _pocket_block():
    return trimesh.boolean.difference([_box((80, 60, 30)), _box((60, 40, 21), at=(10, 10, 10))], engine="manifold")


@pytest.mark.parametrize("fine", [False, True], ids=["one edge per corner", "finely tessellated"])
def test_pocket_and_box_corners_are_counted_as_corners(fine):
    for part, depth in ((_cup(), 28.0), (_pocket_block(), 20.0)):
        mesh = _fine(part) if fine else part
        issues = _corners(mesh)
        assert [i.code for i in issues] == ["SHARP_INTERNAL_CORNERS"]
        assert issues[0].message.startswith("4 sharp concave corners between walls")
        # Four corners, each the depth of the box or pocket; the radius follows that depth.
        assert f"({4 * depth:g} mm of edge, the deepest runs {depth:g} mm deep)" in issues[0].message


@pytest.mark.parametrize("fine", [False, True], ids=["one edge per corner", "finely tessellated"])
def test_corners_a_flat_cutter_cuts_sharp_are_not_flagged(fine):
    # The foot of an L bracket's upright: the base is the floor of the cut.
    mesh = _fine(_lbracket()) if fine else _lbracket()
    assert _corners(mesh) == []


def test_facets_of_a_coarse_round_hole_are_not_corners():
    # A 10-sided 6 mm hole through a 3 mm plate: neighbouring facets turn 36 degrees.
    plate = _box((60, 40, 3))
    hole = trimesh.creation.cylinder(radius=3.0, height=5.0, sections=10)
    hole.apply_translation((30, 20, 1.5))
    part = trimesh.boolean.difference([plate, hole], engine="manifold")
    assert part.is_volume
    turns = np.degrees(part.face_adjacency_angles[~part.face_adjacency_convex])
    assert (turns > 30).sum() >= 10  # the old rule fired on these
    assert _corners(part) == []


def test_a_hexagonal_pocket_keeps_its_six_corners():
    block = _box((40, 40, 10))
    pocket = trimesh.creation.cylinder(radius=10.0, height=8.0, sections=6)
    pocket.apply_translation((20, 20, 10 - 2.0))
    part = trimesh.boolean.difference([block, pocket], engine="manifold")
    issues = _corners(part)
    assert [i.code for i in issues] == ["SHARP_INTERNAL_CORNERS"]
    assert issues[0].message.startswith("6 sharp concave corners")
    assert math.isclose(part.volume, 40 * 40 * 10 - 1.5 * math.sqrt(3) * 100 * 6, rel_tol=1e-6)
