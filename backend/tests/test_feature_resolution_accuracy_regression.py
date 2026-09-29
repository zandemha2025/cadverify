"""PROD-020: manufacturing size must not depend on export tessellation."""
import numpy as np
import pytest
import trimesh

from src.analysis import context
from src.analysis.additive_analyzer import check_small_features as legacy_check
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_small_features


@pytest.mark.parametrize("refine", [0, 5])
@pytest.mark.parametrize("width,expected", [(10.0, False), (0.39, True), (0.41, False)])
def test_physical_width_survives_tessellation(refine, width, expected, monkeypatch):
    part = trimesh.creation.box(extents=[10, 10, width])
    for _ in range(refine):
        part = part.subdivide()
    part.apply_transform(trimesh.transformations.rotation_matrix(0.67, [1, 2, 3]))
    # Wall rays are independent of this edge-resolution check.
    monkeypatch.setattr(context, "_compute_wall_thickness", lambda mesh, *args: np.full(len(mesh.faces), np.inf))
    ctx = context.GeometryContext.build(part, analyze_geometry(part))
    assert bool(check_small_features(ctx, 0.4, ProcessType.FDM)) is expected
    assert bool(legacy_check(part, ProcessType.FDM)) is expected


@pytest.mark.parametrize("sections", [64, 256])
def test_smooth_bore_rim_segments_are_not_small_features(sections, monkeypatch):
    part = trimesh.creation.annulus(r_min=3, r_max=10, height=10, sections=sections)
    monkeypatch.setattr(context, "_compute_wall_thickness", lambda mesh, *args: np.full(len(mesh.faces), np.inf))
    ctx = context.GeometryContext.build(part, analyze_geometry(part))
    assert check_small_features(ctx, 0.4, ProcessType.FDM) == []
    assert legacy_check(part, ProcessType.FDM) == []
