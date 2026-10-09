"""Regression QA-004: dense IGES cost/DFM repeated full surface searches.

Found by /qa on 2026-10-08; report:
.gstack/qa-reports/qa-report-scalecad-ai-2026-10-08.md.
The work bound is independent of machine speed; the geometry stays intact.
"""
import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext


def test_dense_convex_box_keeps_exact_thickness_without_per_triangle_searches(monkeypatch):
    mesh = trimesh.creation.box(extents=[20., 15., 10.])
    for _ in range(7):
        mesh = mesh.subdivide()
    assert len(mesh.faces) > 160_000
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    original = trimesh.proximity.ProximityQuery.on_surface
    queried_points = 0

    def measured(self, points):
        nonlocal queried_points
        queried_points += len(points)
        return original(self, points)

    monkeypatch.setattr(trimesh.proximity.ProximityQuery, "on_surface", measured)
    assert ctx.undercut_free_geometry is True
    assert ctx.maximum_inscribed_diameter == pytest.approx(10., abs=1e-8)
    assert queried_points <= 16, "only planar facet centers need triangle queries"
    assert len(ctx.mesh.faces) == len(mesh.faces), "no coarsening or decimation"


def test_support_planes_remain_exact_after_rotation_and_large_translation():
    mesh = trimesh.creation.box(extents=[20., 15., .81])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.67, [1., 2., 3.]))
    mesh.apply_translation([10_000., -20_000., 30_000.])
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    assert ctx.convex_support_planes is not None
    assert ctx.maximum_inscribed_diameter == pytest.approx(.81, abs=1e-8)
    assert ctx.undercut_free_geometry is True


def test_local_convex_candidate_cannot_certify_a_hole(monkeypatch):
    mesh = trimesh.creation.annulus(r_min=9., r_max=10., height=30., sections=32)
    # Even an optimistic adjacency nomination must pass the global plane proof.
    monkeypatch.setattr(type(mesh), "face_adjacency_projections",
        property(lambda self: np.zeros(len(self.face_adjacency))))
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    assert ctx.convex_support_planes is None
    assert ctx.maximum_inscribed_diameter == pytest.approx(1., rel=.02)


@pytest.mark.parametrize("unsafe", ["open", "uncertain", "decimated", "cavity"])
def test_unproved_surfaces_do_not_use_convex_clearance(unsafe):
    mesh = trimesh.creation.box(extents=[20., 15., 10.])
    if unsafe == "open":
        mesh.update_faces(np.arange(len(mesh.faces) - 1))
    elif unsafe == "uncertain":
        mesh.metadata["coordinate_error"] = .01
    elif unsafe == "cavity":
        inner = trimesh.creation.box(extents=[2., 2., 2.])
        inner.invert()
        mesh = trimesh.util.concatenate([mesh, inner])
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    if unsafe == "decimated":
        ctx.metadata["decimation"] = {"succeeded": True}
    assert ctx.convex_support_planes is None
