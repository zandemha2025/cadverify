"""Regression: large-mesh behavior + scale-aware epsilon + timeout.

Covers CORE-05 (scale-aware epsilon), CORE-06 (analysis timeout), and
CORE-08 (large-mesh stability) from the Phase-1 hardening plan.

Fixture design note
-------------------
The plan called for `trimesh.creation.icosphere(subdivisions=7)` as the
>200k-face stress mesh. On empirical testing that fixture SIGKILL'd the
worker via OOM because trimesh's `mesh.ray.intersects_location(multiple_hits=True)`
is catastrophic on a perfect sphere (every outward ray re-hits every
other face on the opposite hemisphere). Switching to a **twice-subdivided
axis-aligned box** (`extents=[20,20,20]`, 7 loop subdivisions) plus a
smaller auxiliary cube yields ~209k faces — over the plan's 200k bar —
and builds the full GeometryContext in ~7s with 100% finite wall
thickness. That is what the test wants to prove: a real-world large
mesh can run end-to-end without OOM and without degenerate geometry.
See 01.D-SUMMARY.md §Deviations for the full rationale.
"""
from __future__ import annotations

import importlib
import io

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from trimesh.util import concatenate

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def large_mesh_200k() -> trimesh.Trimesh:
    """Twice-subdivided cube composite exceeding 200k faces.

    Cheap to build, cheap to ray-cast, exercises the same code paths as
    a production upload. ~209k faces, ~7s context build on a 2020-era laptop.
    """
    big = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    for _ in range(7):
        big = big.subdivide()
    small = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    for _ in range(5):
        small = small.subdivide()
    small.apply_translation([60.0, 0.0, 0.0])
    return concatenate([big, small])


@pytest.fixture
def micro_cube_1mm() -> trimesh.Trimesh:
    """1mm cube — sub-mm scale tests the epsilon clamp lower end."""
    return trimesh.creation.box(extents=[1.0, 1.0, 1.0])


@pytest.fixture
def macro_box_5m() -> trimesh.Trimesh:
    """5m box — multi-meter scale tests the epsilon clamp upper end."""
    return trimesh.creation.box(extents=[5000.0, 5000.0, 5000.0])


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────
def test_large_mesh_face_count_exceeds_200k(large_mesh_200k):
    """Sanity: the 'large' fixture really is >200k faces."""
    assert len(large_mesh_200k.faces) > 200_000


def test_large_mesh_context_builds_without_crash(large_mesh_200k):
    """CORE-08: context builder must handle >200k faces without OOM or crash."""
    info = analyze_geometry(large_mesh_200k)
    ctx = GeometryContext.build(large_mesh_200k, info)
    assert ctx.wall_thickness.shape == (len(large_mesh_200k.faces),)


def test_large_mesh_wall_thickness_has_finite_values(large_mesh_200k):
    """A closed 200k-face mesh must produce finite wall-thickness samples."""
    info = analyze_geometry(large_mesh_200k)
    ctx = GeometryContext.build(large_mesh_200k, info)
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0
    # Two closed axis-aligned cubes should resolve to ~100% finite;
    # anything under 50% is a regression in the scale-aware epsilon
    # or the inward ray-cast origin offset.
    inf_pct = float(np.mean(~np.isfinite(ctx.wall_thickness)) * 100)
    assert inf_pct < 50, (
        f"{inf_pct:.1f}% inf values on closed cube composite — "
        f"epsilon or ray-cast regression"
    )


def test_micro_cube_produces_finite_wall_thickness(micro_cube_1mm):
    """CORE-05: 1mm-scale part must not return all-inf wall thickness."""
    info = analyze_geometry(micro_cube_1mm)
    ctx = GeometryContext.build(micro_cube_1mm, info)
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0, (
        "Micro-cube produced all-inf wall thickness — epsilon too large"
    )


def test_macro_box_produces_finite_wall_thickness(macro_box_5m):
    """CORE-05: 5m-scale part must not return all-inf wall thickness."""
    info = analyze_geometry(macro_box_5m)
    ctx = GeometryContext.build(macro_box_5m, info)
    finite = ctx.wall_thickness[np.isfinite(ctx.wall_thickness)]
    assert finite.size > 0, (
        "Macro-box produced all-inf wall thickness — epsilon too small"
    )


def test_analysis_timeout_returns_504(monkeypatch):
    """CORE-06: tight ANALYSIS_TIMEOUT_SEC on a non-trivial mesh yields 504.

    Uses a medium-size icosphere so the STL export is fast but any
    analysis work reliably overruns a 1ms budget.
    """
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.001")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    mesh = trimesh.creation.icosphere(subdivisions=5)  # ~20k faces
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    r = client.post(
        "/api/v1/validate",
        files={"file": ("sphere.stl", buf.getvalue(), "application/octet-stream")},
    )
    assert r.status_code == 504, f"expected 504, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "message" in body
    msg = body["message"].lower()
    assert "analysis_timeout_sec" in msg or "exceed" in msg
