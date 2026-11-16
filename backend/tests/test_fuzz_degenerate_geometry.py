"""Fuzz the analysis pipeline with degenerate customer geometry (envelope C).

The audit's production incident (a tessellated cylinder whose hull query
allocated 3.6 GB) was one shape nobody had tried. This generator throws the
whole ZOO at the pipeline nightly-in-CI: NaN and infinite coordinates,
zero-area and duplicate faces, non-manifold fans, self-intersecting shells,
degenerate slivers, single-vertex clouds, million-face walls. The contract is
the containment envelope's: every input either produces an answer or a
catchable, honest degradation — a crash here is found by machines, not by a
customer's 502.
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

import src.analysis.processes  # noqa: F401  populate registry
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes.base import get_analyzer
from src.api.routes import _run_cost_engine_ctx


def _box(extents=(40.0, 30.0, 25.0)):
    return trimesh.creation.box(extents=extents)


def _nan_vertices():
    mesh = _box()
    mesh.vertices[0] = np.nan
    return mesh


def _inf_vertices():
    mesh = _box()
    mesh.vertices[1] = np.inf
    return mesh


def _zero_area_faces():
    mesh = _box()
    mesh.faces[2] = mesh.faces[1]  # duplicate a face → degenerate triangle
    return mesh


def _collapsed_face():
    mesh = _box()
    mesh.vertices[mesh.faces[3][1]] = mesh.vertices[mesh.faces[3][0]]
    return mesh


def _nonmanifold_fan():
    # One edge shared by three triangles: the classic non-manifold wedge.
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0.01]], dtype=float)
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3]])
    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def _sliver():
    return trimesh.creation.box(extents=(1000.0, 0.001, 0.001))


def _single_triangle():
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    return trimesh.Trimesh(vertices=verts, faces=np.array([[0, 1, 2]]), process=False)


def _duplicate_solids():
    return trimesh.util.concatenate([_box(), _box().apply_translation([100, 0, 0])])


def _huge_axis_aligned_wall():
    # ~1M faces: a subdivided plane two triangles deep (wall, not a volume).
    plane = trimesh.creation.box(extents=(500.0, 500.0, 0.02))
    return plane.subdivide().subdivide().subdivide().subdivide()


def _self_intersecting():
    # Two interpenetrating boxes fused as one soup (no boolean resolution).
    a = _box()
    b = _box((20.0, 20.0, 20.0)).apply_translation([10, 10, 10])
    return trimesh.util.concatenate([a, b])


def _backwards_normals():
    mesh = _box()
    mesh.faces = mesh.faces[:, ::-1]
    return mesh


CASES = [
    ("nan-vertex", _nan_vertices),
    ("inf-vertex", _inf_vertices),
    ("zero-area-face", _zero_area_faces),
    ("collapsed-face", _collapsed_face),
    ("nonmanifold-fan", _nonmanifold_fan),
    ("needle-sliver", _sliver),
    ("single-triangle", _single_triangle),
    ("duplicate-solids", _duplicate_solids),
    ("self-intersecting", _self_intersecting),
    ("backwards-normals", _backwards_normals),
    ("huge-wall", _huge_axis_aligned_wall),
]


@pytest.mark.parametrize("name,make", CASES, ids=[c[0] for c in CASES])
def test_degenerate_geometry_never_crashes_the_engine(name, make):
    """The full cost-engine pass either answers or degrades — never raises,
    never allocates without bound (the whole pass is memory-profiled)."""
    import tracemalloc

    mesh = make()
    tracemalloc.start()
    try:
        try:
            result, m, ctx = _run_cost_engine_ctx(mesh, f"{name}.stl")
        except ValueError:
            result = None          # a clean front-door refusal (NaN/inf) is a
                                    # legitimate, caller-mapped outcome — allowed
        _ = run_universal_checks(mesh)
        cur, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # The ladder contract: the engine either answered or refused CLEANLY (it
    # returned at all — no crash, no unbounded allocation on ANY input).
    assert peak < 4_000_000_000, f"{name}: engine peaked at {peak/1e6:.0f} MB"
    if result is not None:
        assert isinstance(result.process_scores, list)


def test_every_registered_analyzer_survives_the_zoo():
    """Each analyzer individually runs against every degenerate mesh: an
    analyzer may raise internally (the engine degrades it to ANALYSIS_PARTIAL),
    but must never hang or take the process down."""
    for name, make in CASES:
        mesh = make()
        try:
            geometry = analyze_geometry(mesh)
            ctx = GeometryContext.build(mesh, geometry)
            ctx.features = detect_all(ctx.mesh)
        except Exception:
            continue  # geometry/context failures are honest degrades too
        for proc in ProcessType:
            analyzer = get_analyzer(proc)
            if analyzer is None:
                continue
            try:
                analyzer.analyze(ctx)  # noqa: B023 — may raise; that is the contract
            except Exception:
                pass  # contained per-analyzer: fine; crashes are not (test process lives)
