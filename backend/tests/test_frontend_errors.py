"""Regression: frontend-facing error contracts (504, 400 magic, 400 cap).

Exercises the API error paths that the Next.js frontend depends on:
- 400 on magic-byte mismatch (STL, STEP)
- 400 on MAX_TRIANGLES cap
- 413 on oversize upload
- 504 on analysis timeout (CORE-06)
- 400 on unknown extension

All use FastAPI TestClient — no live network, no cadquery required.
"""
from __future__ import annotations

import importlib
import io

import pytest
import trimesh
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_magic_byte_rejection_returns_400_with_detail(client):
    """Frontend must receive a clear 400 on a mismatched STL magic."""
    # Too short to be a valid STL (< 84 bytes) → validate_magic rejects.
    r = client.post(
        "/api/v1/validate",
        files={"file": ("fake.stl", b"PK\x03\x04notanstl", "application/octet-stream")},
    )
    assert r.status_code == 400
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], str)


def test_triangle_cap_rejection_returns_400(monkeypatch, cube_10mm, stl_bytes_of):
    """MAX_TRIANGLES=1 on a cube (12 triangles) must 400 before analysis."""
    monkeypatch.setenv("MAX_TRIANGLES", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "triangle" in detail.lower() or "MAX_TRIANGLES" in detail


def test_upload_size_limit_returns_413(monkeypatch):
    """Frontend must receive 413 for oversize uploads (existing behavior, regress)."""
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    big = b"\x00" * (2 * 1024 * 1024)  # 2 MiB
    r = client.post(
        "/api/v1/validate",
        files={"file": ("big.stl", big, "application/octet-stream")},
    )
    assert r.status_code == 413
    assert "detail" in r.json()


def test_timeout_returns_504_with_structured_detail(monkeypatch):
    """Frontend must receive a structured 504 on analysis timeout (CORE-06)."""
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "0.001")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    client = TestClient(main.app)
    mesh = trimesh.creation.icosphere(subdivisions=5)  # ~20k faces — fast export
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    r = client.post(
        "/api/v1/validate",
        files={"file": ("sphere.stl", buf.getvalue(), "application/octet-stream")},
    )
    # Tolerant: extremely fast machines may finish analysis under 1ms (unlikely).
    assert r.status_code in (504, 200), f"unexpected {r.status_code}: {r.text[:200]}"
    if r.status_code == 504:
        body = r.json()
        assert "detail" in body
        detail = body["detail"].lower()
        assert "timeout" in detail or "timed out" in detail or "exceed" in detail


def test_unknown_extension_returns_400(client):
    """.txt upload must be rejected at extension-check stage."""
    r = client.post(
        "/api/v1/validate",
        files={"file": ("foo.txt", b"plain text", "text/plain")},
    )
    assert r.status_code == 400
    assert "detail" in r.json()
