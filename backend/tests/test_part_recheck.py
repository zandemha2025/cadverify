"""POST /api/v1/parts/{mesh_hash}/recheck: price a saved part again from its kept file.

The same decision as ``POST /validate/cost`` on the bytes the organization
kept, so a saved part is priced in another material, at other quantities or
against the org's machines without anyone picking the file again. Org-scoped
like the other stored-source routes; no check used; a free account has its own
ceiling; the kept bytes are never returned.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
import trimesh
from fastapi import FastAPI
from fastapi.testclient import TestClient

ORG_A = "01JORGAAAAAAAAAAAAAAAAAAAA"
ORG_B = "01JORGBBBBBBBBBBBBBBBBBBBB"
USERS = {1: (ORG_A, "member"), 2: (ORG_B, "admin"), 3: (ORG_A, "viewer")}


def _cube_stl(size: float = 20.0) -> bytes:
    buf = io.BytesIO()
    trimesh.creation.box(extents=[size] * 3).export(buf, file_type="stl")
    return buf.getvalue()


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "objects"))
    monkeypatch.setenv("ADMISSION_DISABLED", "1")
    return tmp_path


@pytest.fixture(autouse=True)
def _memberships(monkeypatch):
    async def lookup(user_id: int):
        return USERS.get(user_id)

    monkeypatch.setattr("src.auth.rbac.lookup_org_membership", lookup)


def _save(org: str, name: str, raw: bytes) -> str:
    from src.services.source_artifact_service import save_source_artifact

    digest = hashlib.sha256(raw).hexdigest()
    asyncio.run(save_source_artifact(org, digest, name, raw))
    return digest


def _fake_session():
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    return session


def _app(user_id: int | None, *, free_limits: bool = False) -> FastAPI:
    from src.api.part_recheck import router
    from src.auth import free_tool_limits
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/parts")
    if user_id is not None:
        app.dependency_overrides[require_api_key] = lambda: AuthedUser(
            user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")
    if not free_limits:
        for dependency in free_tool_limits.ALL:
            app.dependency_overrides[dependency] = lambda: None

    async def _session():
        yield _fake_session()

    app.dependency_overrides[get_db_session] = _session
    return app


def test_recheck_prices_the_kept_file_without_it_being_uploaded(store):
    raw = _cube_stl()
    digest = _save(ORG_A, "bracket.stl", raw)
    r = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/recheck?qty=10,1000&material_class=aluminum")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quantities"] == [10, 1000]
    assert body["material_class"] == "aluminum"
    assert any(e.get("unit_cost_usd") for e in body["estimates"]), "a 20 mm cube can be priced"
    meta = body["recheck"]
    assert meta["source"] == "kept" and meta["mesh_hash"] == digest and meta["checks_used"] == 0
    assert meta["basis"] == {"quantities": "request", "material_class": "request"}
    assert meta["bytes"] == len(raw) and meta["format"] == "stl"
    # The kept bytes never travel back.
    assert raw[:80].decode(errors="ignore") not in r.text


def test_recheck_defaults_to_the_parts_last_cost_check_else_the_ladder(store, monkeypatch):
    from src.services import cad_fix_service

    digest = _save(ORG_A, "bracket.stl", _cube_stl())
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/recheck").json()
    assert body["recheck"]["basis"] == {"quantities": "default_ladder", "material_class": "default"}
    assert body["quantities"] == list(cad_fix_service.DEFAULT_QUANTITIES)
    assert body["material_class"] == "polymer"

    async def saved(session, org_id, mesh_hash):
        return [50, 500], "steel", "saved_cost_check"

    monkeypatch.setattr(cad_fix_service, "_saved_cost_inputs", saved)
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/recheck").json()
    assert body["quantities"] == [50, 500] and body["material_class"] == "steel"
    assert body["recheck"]["basis"] == {"quantities": "saved_cost_check", "material_class": "saved_cost_check"}


def test_recheck_with_the_orgs_machines_and_a_bad_option(store):
    digest = _save(ORG_A, "bracket.stl", _cube_stl())
    client = TestClient(_app(1))
    r = client.post(f"/api/v1/parts/{digest}/recheck?qty=10&owned_processes=cnc_3axis")
    assert r.status_code == 200, r.text
    assert client.post(f"/api/v1/parts/{digest}/recheck?material_class=unobtainium").status_code == 400
    assert client.post(f"/api/v1/parts/{digest}/recheck?complexity=baroque").status_code == 400


def test_an_open_kept_file_is_refused_like_an_upload(store):
    box = trimesh.creation.box(extents=[10.0] * 3)
    buf = io.BytesIO()
    trimesh.Trimesh(box.vertices, box.faces[:-2], process=False).export(buf, file_type="stl")
    digest = _save(ORG_A, "open.stl", buf.getvalue())
    r = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/recheck")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "GEOMETRY_INVALID"


def test_recheck_auth_and_org_scoping(store, monkeypatch):
    digest = _save(ORG_A, "bracket.stl", _cube_stl())
    path = f"/api/v1/parts/{digest}/recheck?qty=10"
    assert TestClient(_app(None)).post(path).status_code == 401
    assert TestClient(_app(99)).post(path).status_code == 403
    assert TestClient(_app(2)).post(path).status_code == 404, "another org's part is not found"
    assert TestClient(_app(1)).post(path.replace(digest, "0" * 64)).status_code == 404
    assert TestClient(_app(1)).post("/api/v1/parts/not-a-hash/recheck").status_code == 404
    assert TestClient(_app(3)).post(path).status_code == 403, "a viewer can't save a decision"
    from src.api import routes

    monkeypatch.setattr(routes, "_max_upload_bytes", lambda: 100)
    r = TestClient(_app(1)).post(path)
    assert r.status_code == 413 and "limit" in r.json()["detail"]


def test_recheck_uses_no_check_and_has_the_free_ceiling(store, monkeypatch):
    from slowapi import Limiter

    from src.api.part_recheck import router
    from src.auth import free_tool_limits, validation_caps
    from src.auth.org_limits import enforce_org_limits
    from src.auth.validation_caps import enforce_validation_caps, require_paid_access

    def calls(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    (route,) = [r for r in router.routes if r.path == "/{mesh_hash}/recheck"]
    found = set(calls(route.dependant))
    assert enforce_validation_caps not in found and enforce_org_limits not in found
    assert require_paid_access not in found
    assert free_tool_limits.limit_free_recheck in found

    monkeypatch.setattr(free_tool_limits, "limiter", Limiter(key_func=lambda: "t", storage_uri="memory://", enabled=True))
    monkeypatch.setenv("FREE_RECHECK_LIMIT", "1/hour")

    async def trial(user_id):
        return "trial"

    monkeypatch.setattr(validation_caps, "effective_plan", trial)
    digest = _save(ORG_A, "bracket.stl", _cube_stl())
    client = TestClient(_app(1, free_limits=True))
    assert client.post(f"/api/v1/parts/{digest}/recheck?qty=10").status_code == 200
    second = client.post(f"/api/v1/parts/{digest}/recheck?qty=10")
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "free_tool_limit" and second.json()["detail"]["tool"] == "recheck"
