"""Tests for POST /validate/preview-mesh — the browser-renderable shell stream.

The Verify stage renders STEP/IGES/STL parts as their REAL tessellated shape via
this endpoint (a decimated GLB), replacing the old bounding-box fallback. These
prove the contract: a valid GLB comes back, it is decimated to the browser budget,
the honest decimation headers ride along, and unparseable input is refused (so the
stage can fall back to the honest box).
"""
from __future__ import annotations

import importlib
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ASSETS = Path(__file__).parent / "assets"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)
    return TestClient(main.app)


def _assert_glb(body: bytes) -> None:
    """A GLB starts with the 'glTF' magic and a version-2 header."""
    assert len(body) > 20, "GLB too small to be real geometry"
    magic, version = struct.unpack_from("<4sI", body, 0)
    assert magic == b"glTF", "response is not a GLB"
    assert version == 2


def test_preview_mesh_stl_returns_glb(client, cube_10mm, stl_bytes_of):
    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate/preview-mesh",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("model/gltf-binary")
    _assert_glb(r.content)
    assert r.headers["x-mesh-source"] == "stl"
    assert int(r.headers["x-mesh-preview-faces"]) > 0


@pytest.mark.skipif(
    not __import__("src.parsers.step_mesher", fromlist=["is_step_supported"]).is_step_supported(),
    reason="gmsh/STEP path unavailable",
)
def test_preview_mesh_step_is_real_and_budgeted(client):
    """cube.step tessellates to ~185k faces; the preview must be a real, non-empty
    shell decimated under the 150k browser ceiling (target ~50k)."""
    data = (ASSETS / "cube.step").read_bytes()
    r = client.post(
        "/api/v1/validate/preview-mesh",
        files={"file": ("cube.step", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    _assert_glb(r.content)
    assert r.headers["x-mesh-source"] == "step"

    original = int(r.headers["x-mesh-original-faces"])
    preview = int(r.headers["x-mesh-preview-faces"])
    assert original > 50_000, "expected a real tessellated shell, not a box"
    assert 0 < preview <= 150_000, "preview must fit the browser budget"
    assert preview < original, "an oversize shell must be decimated"
    assert r.headers["x-mesh-decimated"] == "true"


def test_preview_mesh_rejects_bad_extension(client):
    r = client.post(
        "/api/v1/validate/preview-mesh",
        files={"file": ("foo.txt", b"not cad", "text/plain")},
    )
    # Unparseable → 400 so the stage keeps the HONEST bbox fallback (never a fake).
    assert r.status_code == 400, r.text
