"""Regression tests for GeometryContext + vectorized wall thickness."""

from __future__ import annotations

import warnings

import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext, _finite_body_volume


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
    assert ctx.body_volumes == [1000.0]


def test_zero_volume_watertight_shell_has_bounded_volume_without_warning():
    # Tetrahedral topology collapsed onto one plane: topologically watertight,
    # but its signed volume is exactly zero. Trimesh.mass_properties divides by
    # zero for this shape; the context helper must classify it without warning.
    mesh = trimesh.Trimesh(
        vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
        faces=[[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]],
        process=False,
    )
    assert mesh.is_watertight
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        assert _finite_body_volume(mesh) == 0.0


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
