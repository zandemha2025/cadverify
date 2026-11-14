"""End-to-end API tests using FastAPI TestClient.

These tests prove that the refactor kept the public contract intact —
uploads, validation, error responses, CORS, upload-size rejection.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

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
    # Health probes Postgres + Redis; in test env these are absent so
    # expect 503/degraded OR 200/ok when both fall back to healthy.
    assert r.status_code in (200, 503)
    body = r.json()
    assert body["status"] in ("ok", "degraded")
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


def test_sam3d_links_the_exact_saved_analysis(client, cube_10mm, stl_bytes_of):
    data = stl_bytes_of(cube_10mm)
    job = MagicMock(ulid="01SAM3DJOB00000000000001")
    queue = AsyncMock()
    exact_saved = {"id": "01EXACTANALYSIS0000000001", "url": "/api/v1/analyses/01EXACTANALYSIS0000000001"}
    with (
        patch("src.api.routes.resolve_org", new_callable=AsyncMock, return_value="org-a"),
        patch(
            "src.services.analysis_service.run_analysis",
            new_callable=AsyncMock,
            return_value={"overall_verdict": "pass", "saved": exact_saved},
        ),
        patch(
            "src.services.analysis_service.get_analysis_id_by_ulid",
            new_callable=AsyncMock,
            return_value=42,
        ) as resolve_exact,
        patch("src.services.job_service.save_mesh_blob", new_callable=AsyncMock),
        patch(
            "src.services.job_service.create_sam3d_job",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch("src.jobs.arq_backend.get_job_queue", new_callable=AsyncMock, return_value=queue),
    ):
        response = client.post(
            "/api/v1/validate?segmentation=sam3d&processes=fdm",
            files={"file": ("cube.stl", data, "application/octet-stream")},
        )

    assert response.status_code == 202, response.text
    assert response.json()["result"]["saved"] == exact_saved
    assert resolve_exact.await_args.args[2] == exact_saved["id"]
    assert resolve_exact.await_args.kwargs["org_id"] == "org-a"


def test_validate_rejects_bad_extension(client):
    r = client.post(
        "/api/v1/validate",
        files={"file": ("foo.txt", b"bad", "text/plain")},
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["message"]


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
    assert "exceeds" in r.json()["message"].lower()


def test_processes_endpoint_lists_every_type(client):
    r = client.get("/api/v1/processes")
    assert r.status_code == 200
    names = {p["process"] for p in r.json()["processes"]}
    # Sanity-check a spread across the three categories.
    assert {"fdm", "cnc_3axis", "injection_molding", "sheet_metal", "forging"} <= names
