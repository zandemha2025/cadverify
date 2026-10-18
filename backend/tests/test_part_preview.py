"""GET /api/v1/parts/{mesh_hash}/preview.glb and /source-status.

The stored source CAD is the org's own: these prove the 3D view of it is
org-scoped (own org 200; another org's hash, a missing artifact and a malformed
hash are the same 404), needs a signed-in member (401 otherwise), returns a GLB in
the analysis face space (so highlights line up with the saved analysis), never
the raw CAD bytes, and never counts as a check.
"""
from __future__ import annotations

import hashlib
import struct

import pytest
import trimesh
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORG_A = "01JORGAAAAAAAAAAAAAAAAAAAA"
ORG_B = "01JORGBBBBBBBBBBBBBBBBBBBB"
USERS = {1: (ORG_A, "viewer"), 2: (ORG_B, "admin")}


@pytest.fixture
def stored_cube(tmp_path, monkeypatch):
    """Org A keeps the exact bytes of a 10 mm cube STL; returns (digest, bytes)."""
    import asyncio

    from src.api import part_preview
    from src.services.source_artifact_service import save_source_artifact

    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    part_preview._cache.clear()
    raw = trimesh.creation.box(extents=[10, 10, 10]).export(file_type="stl")
    digest = hashlib.sha256(raw).hexdigest()
    asyncio.run(save_source_artifact(ORG_A, digest, "cube.stl", raw))
    yield digest, raw
    part_preview._cache.clear()


def _app(user_id: int | None) -> FastAPI:
    from src.api.part_preview import router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/parts")
    if user_id is not None:
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="viewer"
        )
    return app


@pytest.fixture(autouse=True)
def _memberships(monkeypatch):
    async def lookup(user_id: int):
        return USERS.get(user_id)

    monkeypatch.setattr("src.auth.rbac.lookup_org_membership", lookup)


def _glb_magic(body: bytes) -> tuple[bytes, int]:
    return struct.unpack_from("<4sI", body, 0)


def test_own_org_gets_a_glb_in_the_analysis_face_space(stored_cube):
    import asyncio

    from src.api.routes import _build_preview_glb, _parse_mesh_async

    digest, raw = stored_cube
    client = TestClient(_app(1))
    r = client.get(f"/api/v1/parts/{digest}/preview.glb")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("model/gltf-binary")
    assert _glb_magic(r.content) == (b"glTF", 2)
    assert r.content != raw, "the raw CAD bytes must never be returned"
    assert r.headers["x-mesh-face-space"] == "analysis"
    assert r.headers["x-mesh-source"] == "stl"
    assert "no-store" in r.headers["cache-control"]

    # Same tessellation as POST /validate/preview-mesh?purpose=analysis.
    mesh, _ = asyncio.run(_parse_mesh_async(raw, "cube.stl"))
    *_, face_hash = _build_preview_glb(mesh, "cube.stl", for_analysis=True)
    assert r.headers["x-mesh-face-hash"] == face_hash

    # A second read is served from the in-process cache with the same bytes.
    again = client.get(f"/api/v1/parts/{digest.upper()}/preview.glb")
    assert again.status_code == 200
    assert again.content == r.content

    status = client.get(f"/api/v1/parts/{digest}/source-status")
    assert status.status_code == 200, status.text
    assert status.json() == {"mesh_hash": digest, "kept": True, "format": "stl"}


def test_another_orgs_hash_is_a_plain_404(stored_cube):
    digest, _ = stored_cube
    client = TestClient(_app(2))
    missing = TestClient(_app(1)).get(f"/api/v1/parts/{'0' * 64}/preview.glb")
    for path in (f"/api/v1/parts/{digest}/preview.glb", f"/api/v1/parts/{digest}/source-status"):
        r = client.get(path)
        assert r.status_code == 404
        # Indistinguishable from a part that was never stored.
        assert r.json() == missing.json()


def test_missing_or_malformed_hash_is_404(stored_cube):
    client = TestClient(_app(1))
    for h in ("0" * 64, "not-a-hash", "../" + "a" * 61):
        assert client.get(f"/api/v1/parts/{h}/preview.glb").status_code == 404
        assert client.get(f"/api/v1/parts/{h}/source-status").status_code == 404


def test_a_user_without_a_membership_gets_403_and_no_bytes(stored_cube):
    digest, _ = stored_cube
    r = TestClient(_app(99)).get(f"/api/v1/parts/{digest}/preview.glb")
    assert r.status_code == 403
    assert not r.content.startswith(b"glTF")


def test_unauthenticated_is_401(stored_cube):
    digest, _ = stored_cube
    client = TestClient(_app(None))
    assert client.get(f"/api/v1/parts/{digest}/preview.glb").status_code == 401
    assert client.get(f"/api/v1/parts/{digest}/source-status").status_code == 401


def test_viewing_a_stored_part_never_counts_as_a_check():
    """No validation-cap or org-limit dependency anywhere on these routes."""
    from src.api.part_preview import router
    from src.auth.org_limits import enforce_org_limits
    from src.auth.validation_caps import enforce_validation_caps

    def calls(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    for route in router.routes:
        found = set(calls(route.dependant))
        assert enforce_validation_caps not in found, route.path
        assert enforce_org_limits not in found, route.path
