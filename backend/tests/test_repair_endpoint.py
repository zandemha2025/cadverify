"""Integration tests for POST /api/v1/validate/repair endpoint."""
from __future__ import annotations

import base64
import importlib
import io

import pytest
import trimesh
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def _non_watertight_stl() -> bytes:
    """Create a small non-watertight STL (box with faces removed)."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    broken = trimesh.Trimesh(
        vertices=mesh.vertices,
        faces=mesh.faces[:-2],
        process=False,
    )
    buf = io.BytesIO()
    broken.export(buf, file_type="stl")
    return buf.getvalue()


def _watertight_stl() -> bytes:
    """Create a clean watertight STL cube."""
    mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_repair_non_watertight_stl_returns_200(client):
    """POST a non-watertight STL; expect 200 with repair_applied field."""
    data = _non_watertight_stl()
    r = client.post(
        "/api/v1/validate/repair",
        files={"file": ("broken.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "repair_applied" in body


def test_repair_clean_mesh_returns_applied_true_or_false(client):
    """POST a watertight STL; repair may or may not change it but should return 200."""
    data = _watertight_stl()
    r = client.post(
        "/api/v1/validate/repair",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "repair_applied" in body
    # A watertight mesh -- tier1 repair makes it watertight so repair_applied may be True
    assert "original_analysis" in body


def test_repair_response_shape(client):
    """Response JSON must contain all expected top-level keys."""
    data = _non_watertight_stl()
    r = client.post(
        "/api/v1/validate/repair",
        files={"file": ("broken.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    expected_keys = {
        "original_analysis",
        "repair_applied",
        "repair_details",
        "repaired_analysis",
        "repaired_file_b64",
    }
    assert expected_keys.issubset(body.keys()), f"Missing keys: {expected_keys - body.keys()}"


def test_repair_base64_decodable(client):
    """If repair was applied, repaired_file_b64 should be valid base64 with STL header."""
    data = _non_watertight_stl()
    r = client.post(
        "/api/v1/validate/repair",
        files={"file": ("broken.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    if body["repair_applied"] and body.get("repaired_file_b64"):
        decoded = base64.b64decode(body["repaired_file_b64"])
        # Binary STL starts with 80-byte header then face count as uint32
        assert len(decoded) > 84, "Decoded STL too short"


def test_repair_cache_hit_on_reanalysis(client):
    """POST same STL twice; both should return 200 (cache hit on second)."""
    data = _non_watertight_stl()
    r1 = client.post(
        "/api/v1/validate/repair",
        files={"file": ("broken.stl", data, "application/octet-stream")},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/v1/validate/repair",
        files={"file": ("broken.stl", data, "application/octet-stream")},
    )
    assert r2.status_code == 200


def test_repair_requires_auth():
    """POST without auth bypass should require authentication."""
    import main
    importlib.reload(main)

    # Create a fresh app WITHOUT the auth bypass override
    from fastapi.testclient import TestClient as TC
    from src.auth.require_api_key import require_api_key
    from src.db.engine import get_db_session

    # Remove the overrides to test real auth
    main.app.dependency_overrides.pop(require_api_key, None)
    # Keep db session mock to avoid real DB
    try:
        client_no_auth = TC(main.app)
        data = _watertight_stl()
        r = client_no_auth.post(
            "/api/v1/validate/repair",
            files={"file": ("cube.stl", data, "application/octet-stream")},
        )
        assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"
    finally:
        # Restore override for other tests
        from tests.conftest import _apply_auth_bypass
        _apply_auth_bypass(main.app)


def test_repair_rejects_oversize_mesh(monkeypatch):
    """Mesh exceeding REPAIR_MAX_FACES should get 413."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    monkeypatch.setenv("REPAIR_MAX_FACES", "5")  # Very low cap

    import main
    importlib.reload(main)
    client = TestClient(main.app)

    data = _watertight_stl()  # Box has 12 faces, exceeds cap of 5
    r = client.post(
        "/api/v1/validate/repair",
        files={"file": ("cube.stl", data, "application/octet-stream")},
    )
    assert r.status_code == 413, f"Expected 413, got {r.status_code}: {r.text}"
    assert "REPAIR_MAX_FACES" in r.json()["message"]


def test_repair_rejects_bad_extension(client):
    """Non-STL/STEP files should be rejected with 400."""
    r = client.post(
        "/api/v1/validate/repair",
        files={"file": ("model.obj", b"bad data", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["message"]
