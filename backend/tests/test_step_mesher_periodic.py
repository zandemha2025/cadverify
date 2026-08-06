"""Regression: gmsh "Impossible to mesh periodic surface N" retry ladder.

Certain real NIST STEP parts (~19% of the corpus) make gmsh's default
curvature-adaptive 2D mesher abort with "Impossible to mesh periodic surface N".
Before the retry ladder (step_mesher._MESH_RUNGS) this surfaced as the generic
route 400 "Failed to parse mesh file". The ladder retries the failed shape with
MeshAdapt + uniform sizing, which recovers a valid closed shell.

``tests/assets/nist_periodic_ctc05.stp`` is ``nist_ctc_05_asme1_rd.stp`` from the
NIST AP203 corpus — a real part whose primary (rung-0) tessellation raises the
periodic-surface error. It is committed so this regression is permanent and needs
no external data dir.

These tests exercise the REAL gmsh path (no mocks) and are slow: rung 0 meshes
the whole shape before failing (~1-3 min) and only then does the fast MeshAdapt
retry run. They skip cleanly when gmsh is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.parsers.step_mesher import is_step_supported, step_to_trimesh_from_bytes

_PERIODIC_STEP = Path(__file__).parent / "assets" / "nist_periodic_ctc05.stp"
_STEP_MAGIC = b"ISO-10303-21;"


@pytest.mark.slow
def test_periodic_surface_part_now_meshes_to_valid_shell():
    """The real periodic-surface part meshes to a NON-EMPTY, sane, watertight shell.

    Rung 0 (primary) raises "Impossible to mesh periodic surface N"; the ladder
    recovers on the MeshAdapt rung. We assert a valid shell (faces > 0, positive
    finite volume, a real 3D bounding box, watertight, within the 2M triangle
    budget) — exactly what the DFM + cost layer downstream needs. This part
    returned the generic route 400 before the ladder existed.
    """
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")

    data = _PERIODIC_STEP.read_bytes()
    mesh = step_to_trimesh_from_bytes(data, "nist_periodic_ctc05.stp")

    assert len(mesh.faces) > 0, "recovered shell must have triangles"
    assert len(mesh.vertices) > 0
    assert mesh.volume > 0, "recovered shell must have positive volume"
    # sane, real 3D bounding box (this part is a few hundred mm on a side)
    assert all(e > 1.0 for e in mesh.extents), f"degenerate bbox: {mesh.extents}"
    # MeshAdapt recovers a closed, watertight shell within the triangle budget so
    # the route's enforce_triangle_cap (default 2M) does not reject it.
    assert mesh.is_watertight
    assert 100 < len(mesh.faces) < 2_000_000


def test_unmeshable_input_raises_specific_error_not_generic():
    """A truly un-tessellatable input yields a SPECIFIC ValueError that names the
    cause, never a bare/generic failure.

    We monkeypatch the single-rung tessellation to always raise the gmsh periodic
    error, so EVERY rung of the ladder fails. The mesher must then raise a
    ValueError whose message names the periodic-surface cause (the route maps this
    ValueError to a 400 carrying this specific detail, not "Failed to parse mesh
    file").
    """
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")
    import src.parsers.step_mesher as sm

    calls = {"n": 0}

    def _always_periodic(path, algorithm, curvature_pts, heal):
        calls["n"] += 1
        raise Exception("Impossible to mesh periodic surface 103")

    orig = sm._tessellate_once
    sm._tessellate_once = _always_periodic
    try:
        with pytest.raises(ValueError) as ei:
            sm.step_to_trimesh_from_bytes(_STEP_MAGIC + b"\nX;\n", "x.step")
    finally:
        sm._tessellate_once = orig

    msg = str(ei.value).lower()
    assert "periodic" in msg, f"error must name the periodic cause, got: {ei.value}"
    assert "could not tessellate" in msg
    assert "failed to parse mesh file" not in msg  # never the generic route text
    # every rung was attempted before giving up
    assert calls["n"] == len(sm._MESH_RUNGS)


def test_read_error_is_not_retried_across_rungs():
    """An UNreadable STEP (OCC reader rejects it) must NOT trigger the retry ladder
    — a different mesh algorithm cannot fix an invalid file. It raises the read
    ValueError after a single attempt."""
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")
    import src.parsers.step_mesher as sm

    calls = {"n": 0}

    def _always_read_error(path, algorithm, curvature_pts, heal):
        calls["n"] += 1
        raise sm._StepReadError("bad step")

    orig = sm._tessellate_once
    sm._tessellate_once = _always_read_error
    try:
        with pytest.raises(ValueError) as ei:
            sm.step_to_trimesh_from_bytes(_STEP_MAGIC + b"\nX;\n", "x.step")
    finally:
        sm._tessellate_once = orig

    assert "could not read step geometry" in str(ei.value).lower()
    assert calls["n"] == 1, "read errors must not be retried across rungs"
