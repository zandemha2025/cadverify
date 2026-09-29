"""Fillet detector recall / precision on canonical geometry.

detect_fillets identifies rounded-edge strips (partial cylinders) and
fits axis + radius. Canonical internal pocket fillets at radii 1/2/5mm
must be found at BOTH fine (64-section) and coarse (16-section,
22.5deg/step) tessellations, with fitted radius matching nominal.
Controls (sharp corners, bare drill holes, chamfers, tori, plain
boxes) must yield NOTHING - a missed fillet is honest, an invented
radius is not.
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.features.base import FeatureKind

CORPUS = Path(__file__).parent / "corpus-v3"


def _fillets(mesh):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return [f for f in ctx.features if f.kind == FeatureKind.FILLET]


def _rounded_pocket(r, sections):
    """60x60x20 block, 28x28 through-pocket with r-radius internal corner fillets."""
    block = trimesh.creation.box(extents=(60, 60, 20))
    R = 14 - r
    parts = [
        trimesh.creation.box(extents=(2 * R, 28, 25)),
        trimesh.creation.box(extents=(28, 2 * R, 25)),
    ]
    for sx in (-1, 1):
        for sy in (-1, 1):
            c = trimesh.creation.cylinder(radius=r, height=25, sections=sections)
            c.apply_translation((sx * R, sy * R, 0))
            parts.append(c)
    cutter = trimesh.boolean.union(parts, engine="manifold")
    return trimesh.boolean.difference([block, cutter], engine="manifold")


@pytest.mark.parametrize("r", [1.0, 2.0, 5.0])
@pytest.mark.parametrize("sections", [16, 32, 64])
def test_internal_pocket_fillets_found_and_radius_exact(r, sections):
    fillets = _fillets(_rounded_pocket(r, sections))
    assert len(fillets) == 4
    for f in fillets:
        assert f.radius == pytest.approx(r, abs=0.05)
        assert f.metadata["convex"] is False  # internal = concave


def test_plain_cube_no_fillets():
    assert _fillets(trimesh.creation.box(extents=(60, 60, 60))) == []


def test_sharp_pocket_no_fillets():
    m = trimesh.boolean.difference(
        [trimesh.creation.box(extents=(60, 60, 20)), trimesh.creation.box(extents=(28, 28, 25))],
        engine="manifold",
    )
    assert _fillets(m) == []


def test_bare_drill_hole_is_not_a_fillet():
    m = trimesh.boolean.difference(
        [trimesh.creation.box(extents=(60, 60, 5)), trimesh.creation.cylinder(radius=4, height=20, sections=32)],
        engine="manifold",
    )
    assert _fillets(m) == []


def test_torus_is_not_a_fillet():
    assert _fillets(trimesh.creation.torus(major_radius=20, minor_radius=3, major_sections=32, minor_sections=12)) == []


def test_chamfered_plate_no_fillets():
    m = trimesh.load_mesh(CORPUS / "trap-chamfered-plate-prismatic.stl")
    assert _fillets(m) == []


def test_seam_scarred_perimeter_ring_rejected_honestly():
    # The corpus filleted plate's perimeter fillet ring carries seam
    # artifacts (degree-3 nodes at edge midpoints). The detector must
    # reject it outright rather than emit a guessed radius.
    m = trimesh.load_mesh(CORPUS / "trap-filleted-plate-prismatic.stl")
    assert _fillets(m) == []
