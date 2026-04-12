"""Regression tests for GeometryContext + vectorized wall thickness."""

from __future__ import annotations

import numpy as np

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext


def test_cube_context_shapes(cube_10mm):
    ctx = GeometryContext.build(cube_10mm, analyze_geometry(cube_10mm))
    n = len(cube_10mm.faces)
    assert ctx.normals.shape == (n, 3)
    assert ctx.centroids.shape == (n, 3)
    assert ctx.face_areas.shape == (n,)
    assert ctx.angles_from_up_deg.shape == (n,)
    assert ctx.wall_thickness.shape == (n,)
    assert ctx.bbox_diag > 0
    assert ctx.scale_eps > 0


def test_cube_wall_thickness_is_10mm(cube_10mm):
    """A 10mm cube — every outward face should see 10mm to the opposite wall."""
    ctx = GeometryContext.build(cube_10mm, analyze_geometry(cube_10mm))
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0
    # Every face of a cube hits the opposite face at 10mm.
    assert abs(float(finite.mean()) - 10.0) < 0.5
    assert abs(float(finite.min()) - 10.0) < 0.5


def test_thin_plate_minimum_thickness(plate_thin_2mm):
    """30×30×2 plate — minimum thickness measured should be ~2mm (the Z extent)."""
    ctx = GeometryContext.build(plate_thin_2mm, analyze_geometry(plate_thin_2mm))
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0
    # The top and bottom face rays cross 2mm; the side rays cross 30mm.
    # Minimum must be ~2mm, not zero or self-hit.
    assert 1.5 < float(finite.min()) < 2.5


def test_empty_mesh_safety():
    """A zero-face mesh should still produce a valid (degenerate) context."""
    import trimesh

    mesh = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=int))
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    assert ctx.wall_thickness.shape == (0,)
    assert ctx.normals.shape == (0, 3)
