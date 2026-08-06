"""Regression tests for the chamfer / fillet detectors and tapped-hole inference.

Fixtures here are built procedurally (matching the rest of the suite's
convention — see tests/conftest.py's module docstring) since a chamfered
box and a filleted edge aren't available as trimesh.creation primitives.

The false-positive guards (a sharp cube -> 0 chamfers/0 fillets, a plain
cylinder wall -> 0 fillets) are the honesty backbone of this file: these
detectors are meant to say nothing rather than invent a feature, and these
tests pin that behavior.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon

from src.analysis.features.base import FeatureKind
from src.analysis.features.chamfers import detect_chamfers
from src.analysis.features.cylinders import detect_cylinders
from src.analysis.features.detector import detect_all
from src.analysis.features.fillets import detect_fillets
from src.analysis.features.threads import infer_tapped_holes


# ──────────────────────────────────────────────────────────────
# Fixtures: a box with one edge chamfered / filleted, built by
# extruding a 2D cross-section (a square with one corner replaced by a
# straight bevel or an arc) along Z.
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def chamfered_box() -> trimesh.Trimesh:
    """20x20x20 box with one long edge chamfered (3mm x 45deg bevel)."""
    c = 3.0
    poly = Polygon([(-10, -10), (10, -10), (10, 10 - c), (10 - c, 10), (-10, 10)])
    return trimesh.creation.extrude_polygon(poly, height=20.0)


@pytest.fixture
def filleted_box() -> trimesh.Trimesh:
    """20x20x20 box with one long edge rounded (3mm radius, 9-segment arc)."""
    r = 3.0
    n_seg = 9
    cx, cy = 10 - r, 10 - r
    angles = np.linspace(0, np.pi / 2, n_seg + 1)
    arc_pts = [(cx + r * np.cos(a), cy + r * np.sin(a)) for a in angles]
    pts = [(-10, -10), (10, -10)] + arc_pts + [(-10, 10)]
    poly = Polygon(pts)
    return trimesh.creation.extrude_polygon(poly, height=20.0)


# ──────────────────────────────────────────────────────────────
# Chamfer detection
# ──────────────────────────────────────────────────────────────
def test_chamfered_box_detects_chamfer(chamfered_box):
    chamfers = detect_chamfers(chamfered_box)
    assert len(chamfers) >= 1
    c = chamfers[0]
    assert c.kind is FeatureKind.CHAMFER
    assert c.area is not None
    # 20mm long x 3*sqrt(2)mm wide band.
    assert abs(c.area - 20.0 * 3.0 * np.sqrt(2)) < 5.0
    assert 15.0 <= c.metadata["dihedral_deg"] <= 75.0
    assert 0.5 <= c.confidence <= 0.8


def test_cube_has_no_chamfers(cube_10mm):
    """A sharp-edged cube has no bevels — every dihedral is a clean 90deg corner."""
    assert detect_chamfers(cube_10mm) == []


def test_cylinder_has_no_chamfers(cylinder_50h_10r):
    """A cylinder's side facets meet at a small (<15deg) angle — below bevel range."""
    assert detect_chamfers(cylinder_50h_10r) == []


# ──────────────────────────────────────────────────────────────
# Fillet detection
# ──────────────────────────────────────────────────────────────
def test_filleted_box_detects_fillet(filleted_box):
    fillets = detect_fillets(filleted_box)
    assert len(fillets) >= 1
    f = fillets[0]
    assert f.kind is FeatureKind.FILLET
    assert f.radius is not None
    # 3mm nominal fillet radius, recovered via a Kasa circle fit of the
    # strip's cross-section vertices (unbiased for a partial arc, unlike a
    # naive mean-centroid-radial-distance estimate — see fillets.py).
    assert abs(f.radius - 3.0) < 0.5
    assert 45.0 <= f.metadata["total_turn_deg"] <= 135.0
    assert 0.5 <= f.confidence <= 0.75


def test_cube_has_no_fillets(cube_10mm):
    """A sharp-edged cube has no smooth rolls."""
    assert detect_fillets(cube_10mm) == []


def test_cylinder_wall_is_not_a_fillet(cylinder_50h_10r):
    """The whole point of the closed-loop guard: a bare cylindrical wall must
    not be swallowed whole and reported as one giant fillet."""
    assert detect_fillets(cylinder_50h_10r) == []


def test_plate_with_hole_bore_is_not_a_fillet(plate_with_hole):
    """A drilled hole's bore is a closed cylindrical loop too."""
    assert detect_fillets(plate_with_hole) == []


# ──────────────────────────────────────────────────────────────
# detect_all wiring — additive only
# ──────────────────────────────────────────────────────────────
def test_detect_all_includes_new_kinds_without_breaking_existing(chamfered_box):
    features = detect_all(chamfered_box)
    kinds = {f.kind for f in features}
    assert FeatureKind.FLAT in kinds
    assert FeatureKind.CHAMFER in kinds


def test_detect_all_runs_on_empty_mesh_with_new_detectors():
    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=int))
    assert detect_all(empty) == []


# ──────────────────────────────────────────────────────────────
# Tapped-hole inference (metadata-only annotation, no new feature kind)
# ──────────────────────────────────────────────────────────────
def test_five_mm_hole_is_flagged_possibly_tapped(plate_with_hole):
    """plate_with_hole drills a 5mm-RADIUS (10mm diameter) hole — not a tap-drill
    match. Use a purpose-built 2.5mm-radius (5.0mm diameter) hole instead, which
    is the M6 coarse tap-drill diameter exactly."""
    plate = trimesh.creation.box(extents=[50.0, 50.0, 10.0])
    drill = trimesh.creation.cylinder(radius=2.5, height=12.0, sections=64)
    try:
        part = plate.difference(drill)
    except Exception as e:
        pytest.skip(f"boolean ops unavailable: {e}")

    features = detect_cylinders(part)
    holes = [f for f in features if f.kind is FeatureKind.CYLINDER_HOLE]
    assert len(holes) >= 1
    infer_tapped_holes(features)
    hole = max(holes, key=lambda f: f.area or 0)
    assert hole.metadata.get("possibly_tapped") is True
    assert hole.metadata.get("nearest_thread") == "M6"
    # kind must be unchanged — this is an annotation, not a reclassification.
    assert hole.kind is FeatureKind.CYLINDER_HOLE


def test_twenty_mm_hole_is_not_flagged_tapped(plate_with_hole):
    """plate_with_hole's 5mm-radius (10mm-diameter) bore is nowhere near any
    standard metric tap-drill diameter (max in the table is 10.2mm for M12,
    and even that's not within tolerance of 10.0mm... use an explicit 20mm
    hole to make the non-match unambiguous)."""
    plate = trimesh.creation.box(extents=[60.0, 60.0, 10.0])
    drill = trimesh.creation.cylinder(radius=10.0, height=12.0, sections=64)
    try:
        part = plate.difference(drill)
    except Exception as e:
        pytest.skip(f"boolean ops unavailable: {e}")

    features = detect_cylinders(part)
    holes = [f for f in features if f.kind is FeatureKind.CYLINDER_HOLE]
    assert len(holes) >= 1
    infer_tapped_holes(features)
    hole = max(holes, key=lambda f: f.area or 0)
    assert "possibly_tapped" not in hole.metadata


def test_infer_tapped_holes_never_emits_thread_kind(plate_with_hole):
    plate = trimesh.creation.box(extents=[50.0, 50.0, 10.0])
    drill = trimesh.creation.cylinder(radius=2.5, height=12.0, sections=64)
    try:
        part = plate.difference(drill)
    except Exception as e:
        pytest.skip(f"boolean ops unavailable: {e}")

    features = detect_cylinders(part)
    infer_tapped_holes(features)
    assert all(f.kind is not FeatureKind.THREAD for f in features)
