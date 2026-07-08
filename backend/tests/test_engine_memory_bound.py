"""Regression: the wall-thickness ray cast is memory-bounded (arch-audit P0).

Closes the P0 finding that ``_compute_wall_thickness`` cast one inward ray per
face in a single ``mesh.ray.intersects_location(multiple_hits=True)`` call. With
no fast ray backend installed the pure-Python ``RayMeshIntersector`` materialises
(rays × candidate-triangle) arrays, spiking peak RSS to gigabytes — measured at
2,345 MB for a 9.5k-face part and 19,331 MB for a 36.7k-face part, with a 1.5M
face part timing out. The old ``RAYCAST_SAMPLE_THRESHOLD`` default of 50000 left
the entire dangerous 10k-50k face zone (most real CAD) on that un-bounded path.

The fix: (1) lower the sample threshold to 5000, (2) cast rays in adaptive,
face-count-aware batches with scatter-min accumulation so the working set stays
flat, and (3) decimate meshes over MAX_ANALYSIS_FACES on ingest.

These tests prove the bound by running the real code paths in a *fresh* spawned
subprocess (so ``ru_maxrss`` — a monotonic high-water mark — is measured cleanly)
and asserting the incremental peak RSS is a small fraction of the pre-fix 19 GB.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import platform
import resource
import sys

import pytest


# Hard bounds (MB). All are a *small fraction* of the pre-fix 19,331 MB.
# Realistic-CAD paths (subdivided box) come in around ~50-150 MB; the generous
# ceilings below absorb allocator/GC noise without letting a regression slip.
_REALISTIC_BOUND_MB = 1024        # box build + full un-sampled ray path
_PATHOLOGICAL_BOUND_MB = 1800     # hollow-sphere worst case (was OOM / >120s)


def _peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports kilobytes.
    return r / (1024 * 1024) if platform.system() == "Darwin" else r / 1024


def _worker(backend_root, env, kind, target_faces, mode, q):
    """Run in a *fresh* spawned process; report (n_faces, peak_delta_mb, finite)."""
    sys.path.insert(0, backend_root)
    os.environ.update(env)

    import numpy as np
    import trimesh

    if kind == "sphere":
        mesh = trimesh.creation.icosphere(subdivisions=1)
    else:
        mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    while len(mesh.faces) < target_faces:
        mesh = mesh.subdivide()

    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    centroids = np.asarray(mesh.triangles_center, dtype=np.float64)
    eps = max(1e-4, min(float(np.linalg.norm(mesh.extents)) * 1e-4, 0.1))

    baseline = _peak_rss_mb()  # after imports + mesh construction
    if mode == "build":
        from src.analysis.base_analyzer import analyze_geometry
        from src.analysis.context import GeometryContext
        info = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, info)
        result = ctx.wall_thickness
    else:  # "wall_thickness"
        from src.analysis.context import _compute_wall_thickness
        result = _compute_wall_thickness(mesh, normals, centroids, eps)

    peak_delta = _peak_rss_mb() - baseline
    finite = int(np.isfinite(result).sum())
    q.put((len(mesh.faces), float(peak_delta), finite, int(len(result))))


def _measure(kind, target_faces, mode, env=None):
    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    env = dict(env or {})
    p = ctx.Process(
        target=_worker,
        args=(backend_root, env, kind, target_faces, mode, q),
    )
    p.start()
    p.join(timeout=180)
    if p.is_alive():
        p.terminate()
        p.join()
        pytest.fail(f"memory-bound worker ({kind}/{mode}) exceeded 180s")
    assert not q.empty(), f"worker ({kind}/{mode}) produced no result (crashed?)"
    return q.get()  # (n_faces, peak_delta_mb, finite, n)


def test_build_37k_box_is_memory_bounded():
    """GeometryContext.build on a ~37k-face realistic part stays well under 1 GB.

    This is the direct closure of the P0 finding: the 36.7k-face scenario that
    measured 19,331 MB now builds the full context (including wall thickness) in
    a small fraction of that.
    """
    n_faces, peak, finite, n = _measure("box", 37_000, "build")
    assert n_faces >= 37_000
    assert finite > 0, "all-inf wall thickness — ray cast produced nothing"
    assert peak < _REALISTIC_BOUND_MB, (
        f"build peak RSS delta {peak:.0f} MB exceeds {_REALISTIC_BOUND_MB} MB "
        f"({n_faces} faces) — memory bound regressed"
    )


def test_full_unsampled_ray_path_is_batched_and_bounded():
    """Force the un-sampled full-ray path (the exact pre-fix bomb) on 37k faces.

    With RAYCAST_SAMPLE_THRESHOLD raised so all faces take the full ray path,
    the adaptive batching alone must keep peak RSS bounded — this proves the
    batching (not just the sampling threshold) fixes the allocation.
    """
    env = {"RAYCAST_SAMPLE_THRESHOLD": "100000000"}
    n_faces, peak, finite, n = _measure("box", 37_000, "wall_thickness", env)
    assert finite > 0
    assert peak < _REALISTIC_BOUND_MB, (
        f"full-ray-path peak RSS delta {peak:.0f} MB exceeds "
        f"{_REALISTIC_BOUND_MB} MB ({n_faces} faces) — batching failed to bound it"
    )


@pytest.mark.slow
def test_pathological_sphere_wall_thickness_is_bounded():
    """Worst case: a ~37k-face hollow sphere (broad phase prunes nothing).

    The pre-fix code could not finish this within the timeout and spiked to many
    GB; the adaptive batch must keep it to a small fraction of 19 GB.
    """
    n_faces, peak, finite, n = _measure("sphere", 37_000, "wall_thickness")
    assert finite > 0
    assert peak < _PATHOLOGICAL_BOUND_MB, (
        f"pathological-sphere peak RSS delta {peak:.0f} MB exceeds "
        f"{_PATHOLOGICAL_BOUND_MB} MB ({n_faces} faces) — worst case not bounded"
    )


# ──────────────────────────────────────────────────────────────
# Honesty: decimation must be VISIBLY labelled to the user
# ──────────────────────────────────────────────────────────────
def _big_box_composite(min_faces: int):
    """A >min_faces watertight mesh that is cheap to ray-cast (boxes prune well),
    so the decimation-honesty tests stay fast."""
    import trimesh
    from trimesh.util import concatenate

    a = trimesh.creation.box(extents=[20.0, 20.0, 20.0])
    for _ in range(7):
        a = a.subdivide()  # 196,608
    b = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    for _ in range(6):
        b = b.subdivide()  # 49,152
    b.apply_translation([60.0, 0.0, 0.0])
    c = trimesh.creation.box(extents=[8.0, 8.0, 8.0])
    for _ in range(6):
        c = c.subdivide()  # 49,152
    c.apply_translation([-60.0, 0.0, 0.0])
    mesh = concatenate([a, b, c])
    assert len(mesh.faces) > min_faces, f"only {len(mesh.faces)} faces"
    return mesh


def test_decimation_records_metadata_and_emits_warning():
    """A mesh over MAX_ANALYSIS_FACES is decimated, recorded in ctx.metadata, and
    turned into a user-visible DECIMATED_MESH warning (the honesty contract)."""
    from src.analysis.base_analyzer import analyze_geometry, decimation_issue
    from src.analysis.context import GeometryContext, _max_analysis_faces

    mesh = _big_box_composite(_max_analysis_faces())  # > 250k faces by default
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)

    dec = ctx.metadata.get("decimation")
    assert dec and dec["succeeded"], "decimation not recorded in ctx.metadata"
    assert dec["original_faces"] == len(mesh.faces)
    assert dec["analysis_faces"] < dec["original_faces"]

    issue = decimation_issue(ctx)
    assert issue is not None, "no DECIMATED_MESH issue produced"
    assert issue.code == "DECIMATED_MESH"
    assert issue.severity.value == "warning"
    assert issue.process is None  # universal issue
    assert "approximate" in issue.message.lower()
    assert f"{dec['original_faces']:,}" in issue.message


def test_no_decimation_no_warning_for_normal_part():
    """Ordinary parts (under the cap) are untouched and emit NO decimation warning."""
    import trimesh

    from src.analysis.base_analyzer import analyze_geometry, decimation_issue
    from src.analysis.context import GeometryContext

    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    for _ in range(3):
        mesh = mesh.subdivide()  # 768 faces — well under the cap
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    assert not ctx.metadata.get("decimation")
    assert decimation_issue(ctx) is None


def test_decimation_warning_is_visible_in_api_response(monkeypatch):
    """End-to-end: a >250k-face upload returns a DECIMATED_MESH warning in the
    response's ``universal_issues`` — the exact field the frontend renders.

    This is the proof the honest label actually reaches the user, not just
    ctx.metadata that no consumer reads.
    """
    import importlib
    import io

    from fastapi.testclient import TestClient

    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    monkeypatch.setenv("DEMO_MAX_TRIANGLES", "500000")  # composite (~295k) is allowed
    import main

    importlib.reload(main)
    client = TestClient(main.app)

    mesh = _big_box_composite(250_000)
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")

    r = client.post(
        "/api/v1/validate/demo",
        files={"file": ("big.stl", buf.getvalue(), "application/octet-stream")},
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:300]}"
    body = r.json()
    issues = body.get("universal_issues", [])
    codes = [i.get("code") for i in issues]
    assert "DECIMATED_MESH" in codes, f"DECIMATED_MESH not in response; codes={codes}"

    dec = next(i for i in issues if i["code"] == "DECIMATED_MESH")
    assert dec["severity"] == "warning"
    assert "approximate" in dec["message"].lower()
