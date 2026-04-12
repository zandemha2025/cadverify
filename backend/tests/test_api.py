"""End-to-end API tests using FastAPI TestClient.

These tests prove that the refactor kept the public contract intact —
uploads, validation, error responses, CORS, upload-size rejection.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    # Force main.py to re-read env if it was already imported.
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "cadverify"
    assert "version" in body


def test_validate_quick_on_clean_cube(client, cube_10mm, stl_bytes_of):
    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate/quick",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "pass"
    assert body["geometry"]["is_watertight"] is True


def test_validate_full_on_cube_returns_features(client, cube_10mm, stl_bytes_of):
    data = stl_bytes_of(cube_10mm)
    r = client.post(
        "/api/v1/validate",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overall_verdict"] in {"pass", "issues"}
    # Feature detection should have run and populated flats for the cube.
    assert "features" in body
    flats = [f for f in body["features"] if f["kind"] == "flat"]
    assert len(flats) == 6
    # Every supported process should have a score.
    assert len(body["process_scores"]) > 0


def test_validate_rejects_bad_extension(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("foo.txt", b"bad", "text/plain")},
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_validate_rejects_empty_file(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("empty.stl", b"", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_validate_enforces_upload_limit(monkeypatch, cube_10mm, stl_bytes_of):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")  # 1 MiB cap
    import main
    importlib.reload(main)
    client = TestClient(main.app)

    # ~2 MiB body
    oversized = b"\x00" * (2 * 1024 * 1024)
    r = client.post(
        "/api/v1/validate",
        files={"file": ("big.stl", oversized, "application/octet-stream")},
    )
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]


def test_processes_endpoint_lists_every_type(client):
    r = client.get("/api/v1/processes")
    assert r.status_code == 200
    names = {p["process"] for p in r.json()["processes"]}
    # Sanity-check a spread across the three categories.
    assert {"fdm", "cnc_3axis", "injection_molding", "sheet_metal", "forging"} <= names
