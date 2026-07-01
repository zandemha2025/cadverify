"""gmsh STEP -> trimesh.Trimesh loader (Cycle 5 §A).

Always-on, no network. Each test skips cleanly when gmsh is absent so a
no-gmsh CI runner stays green (the route degrades to a clean 501 in that case).
The committed STEP input is synthesized by gmsh at test time (no binary blob).
"""
from __future__ import annotations

import glob
import os
import tempfile

import pytest

from src.parsers.step_mesher import is_step_supported, step_to_trimesh_from_bytes

_STEP_MAGIC = b"ISO-10303-21;"


def test_gmsh_available():
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")
    assert is_step_supported() is True


def test_box_step_meshes_watertight(box_step_bytes):
    """A 20mm solid box STEP -> watertight mesh, correct volume, bounded faces."""
    mesh = step_to_trimesh_from_bytes(box_step_bytes, "box.step")
    assert mesh.is_watertight, "single solid should recover watertightness"
    assert mesh.volume > 0
    # 20mm cube == 8000 mm^3 == 8 cm^3; tessellation is exact for a box.
    assert abs(mesh.volume / 1000.0 - 8.0) < 0.1
    # bbox is 20x20x20 mm
    assert all(abs(e - 20.0) < 0.1 for e in mesh.extents)
    assert 100 < len(mesh.faces) < 2_000_000


def test_empty_step_raises_valueerror():
    """Garbage-after-magic bytes -> ValueError (the route maps it to a 400)."""
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")
    with pytest.raises(ValueError):
        step_to_trimesh_from_bytes(_STEP_MAGIC + b"\nNOT REAL STEP DATA;\n", "bad.step")


def test_no_temp_file_leak():
    """step_to_trimesh_from_bytes must unlink its temp file even on parse failure."""
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")
    pat = os.path.join(tempfile.gettempdir(), "tmp*.step")
    pat2 = os.path.join(tempfile.gettempdir(), "tmp*.stp")
    before = set(glob.glob(pat)) | set(glob.glob(pat2))
    try:
        step_to_trimesh_from_bytes(_STEP_MAGIC + b"\nNOT REAL;\n", "bad.step")
    except Exception:
        pass  # parse failure expected; we assert cleanup
    after = set(glob.glob(pat)) | set(glob.glob(pat2))
    assert after == before, f"Leaked temp files: {after - before}"


def test_temp_file_mode_is_0o600(monkeypatch):
    """Temp file created by the loader must be owner-only (0o600), IP-local."""
    if not is_step_supported():
        pytest.skip("gmsh not installed; STEP path unavailable")
    import src.parsers.step_mesher as sm

    captured = {}

    def fake_mesh(path):
        captured["mode"] = os.stat(path).st_mode & 0o777
        raise ValueError("stop here")  # force the finally cleanup

    monkeypatch.setattr(sm, "_mesh_step_file", fake_mesh)
    with pytest.raises(ValueError):
        sm.step_to_trimesh_from_bytes(_STEP_MAGIC + b"\nX;\n", "x.step")
    assert captured.get("mode") == 0o600, f"mode was {oct(captured.get('mode', 0))}"
