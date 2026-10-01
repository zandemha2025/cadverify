"""Tests for POST /validate/preview-mesh — the browser-renderable shell stream.

The Verify stage renders STEP/IGES/STL parts as their REAL tessellated shape via
this endpoint (a decimated GLB), replacing the old bounding-box fallback. These
prove the contract: a valid GLB comes back, it is decimated to the browser budget,
the honest decimation headers ride along, and unparseable input is refused (so the
stage can fall back to the honest box).
"""
from __future__ import annotations

import importlib
import io
import struct
from pathlib import Path

import pytest
import numpy as np
import trimesh
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


@pytest.mark.parametrize("kind", ["obj", "3mf"])
def test_pair_formats_preview_the_measured_shell_with_the_same_limits(client, monkeypatch, kind):
    # A bored part distinguishes the submitted surface from an envelope box.
    source = trimesh.creation.annulus(r_min=2, r_max=4, height=6, sections=16)
    source.apply_translation([10, 20, 30])
    data = source.export(file_type=kind)
    if isinstance(data, str):
        data = data.encode()
    files = {"file": (f"part.{kind}", data, "application/octet-stream")}
    response = client.post("/api/v1/validate/preview-mesh", files=files)
    assert response.status_code == 200, response.text
    rendered = trimesh.load(io.BytesIO(response.content), file_type="glb").to_mesh()
    np.testing.assert_allclose(rendered.bounds, source.bounds, atol=1e-5)
    assert rendered.volume == pytest.approx(source.volume, abs=1e-4)
    assert response.headers["x-mesh-source"] == kind
    assert int(response.headers["x-mesh-original-faces"]) == len(source.faces)

    # Extra fit formats do not silently become supported DFM analysis inputs.
    assert client.post("/api/v1/validate/preview-mesh?purpose=analysis", files=files).status_code == 400
    monkeypatch.setenv("MAX_TRIANGLES", "1")
    refused = client.post("/api/v1/validate/preview-mesh", files=files)
    assert refused.status_code == 400
    assert "MAX_TRIANGLES" in refused.json()["message"]


def test_3mf_expansion_is_bounded_before_preview_or_fit_parser(client, monkeypatch):
    from zipfile import ZipFile, ZIP_DEFLATED
    from src.services import fit_service

    archive = io.BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as z:
        z.writestr("padding.bin", b"0" * (1024 * 1024 + 1))
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    def must_not_parse(*args, **kwargs):
        raise AssertionError("The oversized expanded package reached trimesh")
    monkeypatch.setattr(fit_service.trimesh, "load", must_not_parse)
    file = ("part.3mf", archive.getvalue(), "application/octet-stream")
    for url, fields in [
        ("/api/v1/validate/preview-mesh", {"file": file}),
        ("/api/v1/validate/fit", {"part_a": file, "part_b": file}),
    ]:
        response = client.post(url, files=fields)
        assert response.status_code == 422, response.text
        assert "expanded" in response.json()["message"]


@pytest.mark.parametrize("cap", [3000, 10000])
def test_analysis_preview_preserves_analysis_triangle_order(monkeypatch, cap):
    from src.api.routes import _build_preview_glb
    from src.analysis.context import _maybe_decimate, analysis_mesh_hash

    monkeypatch.setenv("MAX_ANALYSIS_FACES", str(cap))
    part = trimesh.creation.icosphere(subdivisions=4)
    expected, _ = _maybe_decimate(part)
    data, original, rendered, decimated, face_hash = _build_preview_glb(part, "part.stl", for_analysis=True)
    scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
    actual = next(iter(scene.geometry.values()))
    assert rendered == len(expected.faces)
    assert original == len(part.faces)
    assert decimated == (rendered < original)
    np.testing.assert_allclose(actual.triangles, expected.triangles, atol=1e-6)
    assert face_hash == analysis_mesh_hash(expected) == analysis_mesh_hash(actual)
    assert face_hash != analysis_mesh_hash(trimesh.Trimesh(vertices=expected.vertices, faces=expected.faces[::-1], process=False))


def test_analysis_preview_scales_declared_units(client, cube_10mm, stl_bytes_of):
    response = client.post(
        "/api/v1/validate/preview-mesh?purpose=analysis&units=inch",
        files={"file": ("cube.stl", stl_bytes_of(cube_10mm), "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.headers["x-mesh-face-space"] == "analysis"
    scene = trimesh.load(io.BytesIO(response.content), file_type="glb", process=False)
    np.testing.assert_allclose(next(iter(scene.geometry.values())).extents, [254, 254, 254], atol=1e-5)


def test_preview_mesh_honors_analysis_admission_before_parsing(
    client, cube_10mm, stl_bytes_of
):
    """Preview tessellation cannot bypass the same capacity gate as analysis."""
    import main
    from fastapi import HTTPException

    from src.api.admission import admit_analysis

    async def reject_at_capacity():
        raise HTTPException(
            status_code=429,
            detail={"code": "server_busy", "message": "capacity closed"},
        )

    main.app.dependency_overrides[admit_analysis] = reject_at_capacity
    try:
        r = client.post(
            "/api/v1/validate/preview-mesh",
            files={
                "file": (
                    "cube.stl",
                    stl_bytes_of(cube_10mm),
                    "application/octet-stream",
                )
            },
        )
    finally:
        main.app.dependency_overrides.pop(admit_analysis, None)

    assert r.status_code == 429, r.text
    assert r.json()["code"] == "server_busy"
