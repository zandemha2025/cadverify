"""A fixed file uploaded from a problem card is the part's next revision.

The link is two JSON records in the object store; parts are looked up in the
caller's organization. Here the store is in memory and the part lookup is a
table, so the route's rules (org scope, roles, idempotence, a deleted side not
reported) are what's under test.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.services import part_revision_service as svc

OLD = "a" * 64
NEW = "b" * 64
OTHER_ORG_PART = "c" * 64
PARTS = {
    ("org_1", OLD): {"mesh_hash": OLD, "filename": "enclosure-revA.step", "record_id": "01REVA"},
    ("org_1", NEW): {"mesh_hash": NEW, "filename": "enclosure-revB-3deg-draft.step", "record_id": "01REVB"},
    ("org_2", OTHER_ORG_PART): {"mesh_hash": OTHER_ORG_PART, "filename": "theirs.step", "record_id": "01THEIRS"},
}
USERS = {1: ("org_1", "member"), 2: ("org_1", "viewer"), 3: ("org_2", "admin")}


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    store: dict[str, dict] = {}

    async def put(key, payload):
        store[key] = payload

    async def get(key):
        return store.get(key)

    async def part(session, org_id, mesh_hash):
        return PARTS.get((org_id, mesh_hash))

    async def lookup(user_id: int):
        return USERS.get(user_id)

    monkeypatch.setattr(svc, "_put_json", put)
    monkeypatch.setattr(svc, "_get_json", get)
    monkeypatch.setattr(svc, "_part", part)
    monkeypatch.setattr(svc, "_record_key", lambda org, digest, name: f"{org}/{digest}/{name}")
    monkeypatch.setattr("src.auth.rbac.lookup_org_membership", lookup)
    yield store


def _client(user_id: int, role: str = "analyst") -> httpx.AsyncClient:
    from src.api.part_revisions import router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/parts")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=user_id, api_key_id=0, key_prefix="session", role=role)

    async def _session():
        yield None

    app.dependency_overrides[get_db_session] = _session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_the_uploaded_fix_becomes_the_next_revision_both_ways():
    async with _client(1) as c:
        assert (await c.get(f"/api/v1/parts/{NEW}/revisions")).json() == {"mesh_hash": NEW, "revision_of": None, "next": None}
        linked = await c.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD, "problem": "draft"})
        assert linked.status_code == 200, linked.text
        back = linked.json()["revision_of"]
        assert back["mesh_hash"] == OLD and back["filename"] == "enclosure-revA.step" and back["record_id"] == "01REVA" and back["problem"] == "draft"
        forward = (await c.get(f"/api/v1/parts/{OLD}/revisions")).json()["next"]
        assert forward["mesh_hash"] == NEW and forward["record_id"] == "01REVB"
        # Again: same answer, no duplicate.
        again = await c.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD, "problem": "draft"})
        assert again.json()["revision_of"]["mesh_hash"] == OLD


@pytest.mark.asyncio
async def test_only_this_orgs_parts_and_only_members_link():
    async with _client(1) as c:
        cross = await c.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OTHER_ORG_PART})
        assert cross.status_code == 404
        same = await c.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": NEW})
        assert same.status_code == 409
        bad = await c.get("/api/v1/parts/not-a-hash/revisions")
        assert bad.status_code == 404
    async with _client(2) as viewer:
        assert (await viewer.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD})).status_code == 403
        assert (await viewer.get(f"/api/v1/parts/{NEW}/revisions")).status_code == 200
    async with _client(3) as outsider:
        assert (await outsider.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD})).status_code == 404


@pytest.mark.asyncio
async def test_a_platform_viewer_cant_link_even_as_an_org_member(_world):
    """The same writer check as the other parts writes (R2 minor): a platform
    viewer is refused, whatever their org role; reading stays open."""
    async with _client(1, role="viewer") as c:
        r = await c.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "insufficient_role", r.text
        assert (await c.get(f"/api/v1/parts/{NEW}/revisions")).status_code == 200
    assert _world == {}  # nothing recorded
    async with _client(2) as viewer:
        r = await viewer.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "org_member_required", r.text


@pytest.mark.asyncio
async def test_a_deleted_side_is_not_reported():
    async with _client(1) as c:
        assert (await c.put(f"/api/v1/parts/{NEW}/revision-of", json={"from_mesh_hash": OLD})).status_code == 200
        gone = PARTS.pop(("org_1", NEW))
        try:
            assert (await c.get(f"/api/v1/parts/{OLD}/revisions")).json()["next"] is None
        finally:
            PARTS[("org_1", NEW)] = gone
