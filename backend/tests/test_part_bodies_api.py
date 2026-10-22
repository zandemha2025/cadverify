"""POST /api/v1/parts/{hash}/bodies and /bodies/{n}/part: a multi-body file, body by body.

From the file the organization kept, like a re-check: no upload, no check used,
org-scoped, with the free ceilings. A body opened as its own part is an STL copy
recorded as derived from the file, so checking it uses no check either.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests import part_type_cases as cases

ORG_A = "01JORGAAAAAAAAAAAAAAAAAAAA"
ORG_B = "01JORGBBBBBBBBBBBBBBBBBBBB"
USERS = {1: (ORG_A, "member"), 2: (ORG_B, "admin"), 3: (ORG_A, "viewer")}


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


def _app(user_id: int | None) -> FastAPI:
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
    for dependency in free_tool_limits.ALL:
        app.dependency_overrides[dependency] = lambda: None

    async def _session():
        yield _fake_session()

    app.dependency_overrides[get_db_session] = _session
    return app


def test_bodies_of_a_kept_file_are_checked_one_by_one(store):
    digest = _save(ORG_A, "two cubes.stl", cases.two_cubes())
    r = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies?qty=1,100&material_class=aluminum")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["part_type"]["kind"] == "separate_bodies" and body["checks_used"] == 0
    assert body["quantities"] == [1, 100] and body["material_class"] == "aluminum"
    (design,) = body["designs"]
    assert design["bodies"] == [1, 2] and design["status"] == "ok"
    assert body["total"]["per_file_usd"]["1"] == pytest.approx(design["by_quantity"]["1"]["per_file_usd"], abs=0.01)
    assert body["source"]["mesh_hash"] == digest and body["source"]["basis"] == {"quantities": "request", "material_class": "request"}
    assert r.headers["cache-control"] == "no-store"


def test_a_weldment_kept_file_reads_as_members(store):
    digest = _save(ORG_A, "frame.stl", cases.welded_frame())
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies?qty=1").json()
    assert body["part_type"]["kind"] == "weldment"
    assert body["material_class"] == "steel" and body["material_basis"] == "weldment_default"
    assert body["weldment"]["joints"] == 4 and "welding" in body["weldment"]["not_priced"]
    assert body["source"]["basis"]["material_class"] == "default"


def test_one_solid_answers_without_body_checks(store):
    digest = _save(ORG_A, "cube.stl", cases.cube())
    body = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies?qty=1").json()
    assert body["part_type"]["kind"] == "single_solid" and body["designs"] == []


def test_a_body_opens_as_its_own_part_without_a_check(store, monkeypatch):
    from src.api import part_recheck
    from src.services.cad_fix_service import read_lineage

    # the name the part was checked under (its saved analysis, here stubbed)
    monkeypatch.setattr(part_recheck, "_kept_name", AsyncMock(return_value="frame.stl"))
    digest = _save(ORG_A, "frame.stl", cases.welded_frame())
    r = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies/3/part")
    assert r.status_code == 200, r.text
    out = r.json()
    data = base64.b64decode(out["file_b64"])
    assert hashlib.sha256(data).hexdigest() == out["mesh_hash"] and out["bytes"] == len(data)
    assert out["filename"] == "frame - body 3.stl" and out["checks_used"] == 0
    assert out["body"]["id"] == 3 and out["body"]["of"] == 4
    link = asyncio.run(read_lineage(ORG_A, out["mesh_hash"]))
    assert link["parent_mesh_hash"] == digest and link["fix"] == "body" and link["params"]["body"] == 3
    # another try gives the same bytes: the same body is the same part
    again = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies/3/part").json()
    assert again["mesh_hash"] == out["mesh_hash"]
    assert TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies/9/part").status_code == 404


def test_a_body_copy_is_recognised_as_a_copy_scalecad_made(store, monkeypatch):
    """The check of a body copy finds its parent: no new check slot (validation_caps)."""
    from src.auth import validation_caps
    from src.auth.require_api_key import AuthedUser

    digest = _save(ORG_A, "frame.stl", cases.welded_frame())
    out = TestClient(_app(1)).post(f"/api/v1/parts/{digest}/bodies/1/part").json()

    async def org_of(user):
        return ORG_A

    class _Row:
        def first(self):
            return (1,)

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            return _Row()

    monkeypatch.setattr(validation_caps, "_org_of", org_of)
    monkeypatch.setattr(validation_caps, "get_session_factory", lambda: (lambda: _Session()))
    user = AuthedUser(user_id=1, api_key_id=0, key_prefix="session", role="analyst")
    assert asyncio.run(validation_caps.derived_copy_parent(user, out["mesh_hash"])) == digest


def test_bodies_auth_scoping_and_bad_options(store):
    digest = _save(ORG_A, "two.stl", cases.two_cubes())
    path = f"/api/v1/parts/{digest}/bodies?qty=1"
    assert TestClient(_app(None)).post(path).status_code == 401
    assert TestClient(_app(2)).post(path).status_code == 404, "another org's part is not found"
    assert TestClient(_app(3)).post(path).status_code == 403, "a viewer can't run checks"
    assert TestClient(_app(1)).post(path.replace(digest, "0" * 64)).status_code == 404
    assert TestClient(_app(1)).post(f"{path}&material_class=unobtainium").status_code == 400
    assert TestClient(_app(1)).post(f"{path}&owned_processes=teleport").status_code == 400
    assert TestClient(_app(2)).post(f"/api/v1/parts/{digest}/bodies/1/part").status_code == 404


def test_bodies_routes_use_no_check_and_have_free_ceilings():
    from src.api.part_recheck import router
    from src.auth import free_tool_limits
    from src.auth.org_limits import enforce_org_limits
    from src.auth.validation_caps import enforce_validation_caps, require_paid_access

    def calls(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    for path, ceiling in (("/{mesh_hash}/bodies", free_tool_limits.limit_free_recheck),
                          ("/{mesh_hash}/bodies/{body_id}/part", free_tool_limits.limit_free_fixes)):
        (route,) = [r for r in router.routes if r.path == path]
        found = set(calls(route.dependant))
        assert enforce_validation_caps not in found and enforce_org_limits not in found
        assert require_paid_access not in found, "every plan: one file is one check"
        assert ceiling in found
