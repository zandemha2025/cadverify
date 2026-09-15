"""Regression: GeometryContext.build must not explode on unmerged triangle soup.

FAIL-10MB-TIMEOUT-001 / worker OOM: trimesh.split constructed one Trimesh per
face for disconnected soup (200k faces -> ~35s + ~200k objects), timing out
/validate and OOM-restarting the batch worker. The context now counts connected
components cheaply first and collapses over-cap meshes to a single body,
recording body_split_skipped in metadata.
"""
import time

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext


def _soup(n_faces: int) -> trimesh.Trimesh:
    """n_faces isolated triangles sharing no vertices (unmerged STL soup)."""
    rng = np.random.default_rng(7)
    verts = rng.random((n_faces * 3, 3)) * 100
    faces = np.arange(n_faces * 3).reshape(-1, 3)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def test_over_cap_soup_collapses_to_single_body(monkeypatch):
    monkeypatch.setenv("MAX_SPLIT_BODIES", "100")
    mesh = _soup(2000)
    info = analyze_geometry(mesh)
    started = time.perf_counter()
    ctx = GeometryContext.build(mesh, info)
    elapsed = time.perf_counter() - started
    assert len(ctx.bodies) == 1
    assert ctx.metadata["body_split_skipped"] == {"components": 2000, "cap": 100}
    assert elapsed < 5.0  # pre-fix this path ran ~0.17s per 1k faces of split


def test_welded_multibody_still_splits():
    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[5, 5, 5]).apply_translation([50, 0, 0])
    mesh = trimesh.util.concatenate([a, b])
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    assert len(ctx.bodies) == 2
    assert sorted(ctx.body_volumes) == [125.0, 1000.0]
    assert "body_split_skipped" not in ctx.metadata


def test_under_cap_soup_uses_normal_split(monkeypatch):
    monkeypatch.setenv("MAX_SPLIT_BODIES", "512")
    mesh = _soup(50)
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    assert len(ctx.bodies) == 50
    assert "body_split_skipped" not in ctx.metadata
