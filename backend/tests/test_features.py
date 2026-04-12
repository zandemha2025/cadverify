"""Regression tests for deterministic feature detection."""

from __future__ import annotations

from src.analysis.features import detect_all
from src.analysis.features.base import FeatureKind
from src.analysis.features.cylinders import detect_cylinders
from src.analysis.features.flats import detect_flats


def test_cube_has_six_flats(cube_10mm):
    flats = detect_flats(cube_10mm)
    # A 10mm cube tessellates to 12 triangles in 6 coplanar groups.
    assert len(flats) == 6
    for f in flats:
        assert f.kind is FeatureKind.FLAT
        assert f.area is not None
        # Each face = 10×10 = 100 mm².
        assert abs(f.area - 100.0) < 0.5


def test_cylinder_is_detected_as_boss(cylinder_50h_10r):
    """A solid cylinder is an exterior curved surface → BOSS."""
    features = detect_cylinders(cylinder_50h_10r)
    bosses = [f for f in features if f.kind is FeatureKind.CYLINDER_BOSS]
    assert len(bosses) >= 1
    largest = max(bosses, key=lambda f: f.area or 0)
    assert largest.radius is not None
    assert abs(largest.radius - 10.0) < 0.75  # 20mm diameter → 10mm radius
    assert largest.depth is not None
    assert abs(largest.depth - 50.0) < 1.0
    assert largest.axis is not None
    # Cylinder was created along Z, so the fitted axis should be ~±Z.
    assert abs(abs(largest.axis[2]) - 1.0) < 0.1


def test_plate_with_hole_detects_hole(plate_with_hole):
    features = detect_cylinders(plate_with_hole)
    holes = [f for f in features if f.kind is FeatureKind.CYLINDER_HOLE]
    assert len(holes) >= 1
    hole = max(holes, key=lambda f: f.area or 0)
    assert hole.radius is not None
    assert abs(hole.radius - 5.0) < 0.75


def test_detect_all_runs_on_empty_mesh():
    import numpy as np
    import trimesh

    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=int))
    assert detect_all(empty) == []
