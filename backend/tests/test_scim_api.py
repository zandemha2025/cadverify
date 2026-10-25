from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import scim
from src.auth.rbac import OrgAuthContext
from src.db.engine import get_db_session


@pytest.fixture(autouse=True)
def _org_1_owns_the_identity_provider(monkeypatch):
    """SCIM serves only the org named by SSO_ORG_ID; these tests' org is org_1."""
    monkeypatch.setenv("SSO_ORG_ID", "org_1")


def _ctx(org_id: str | None = "org_1") -> OrgAuthContext:
    return OrgAuthContext(
        user_id=11,
        api_key_id=22,
        key_prefix="test",
        role="analyst",
        is_superadmin=False,
        org_id=org_id,
        org_role="admin" if org_id else None,
    )


def _build_app(session, ctx: OrgAuthContext | None = None):
    app = FastAPI()
    app.include_router(scim.router)

    # The router's personal-org check reads the key's org: a shared team org.
    org_row = MagicMock()
    org_row.first.return_value = ("Acme Corp", "acme-corp-01abcdef")
    session.execute = AsyncMock(return_value=org_row)

    async def _fake_ctx():
        return ctx or _ctx()

    async def _fake_session():
        yield session

    app.dependency_overrides[scim.require_scim_admin] = _fake_ctx
    app.dependency_overrides[get_db_session] = _fake_session
    return app


@pytest.mark.asyncio
async def test_scim_service_provider_config_requires_org_and_reports_patch_support():
    session = AsyncMock()
    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.example") as client:
        resp = await client.get("/scim/v2/ServiceProviderConfig")

    assert resp.status_code == 200
    body = resp.json()
    assert body["patch"]["supported"] is True
    assert body["filter"]["supported"] is True
    assert body["authenticationSchemes"][0]["type"] == "oauthbearertoken"


@pytest.mark.asyncio
async def test_scim_rejects_admin_without_org_boundary():
    session = AsyncMock()
    app = _build_app(session, _ctx(org_id=None))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.example") as client:
        resp = await client.get("/scim/v2/ServiceProviderConfig")

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "scim_org_required"


@pytest.mark.asyncio
async def test_scim_create_user_delegates_to_org_scoped_lifecycle(monkeypatch):
    session = AsyncMock()
    session.commit = AsyncMock()
    seen = {}

    async def _fake_create(session_arg, *, org_id, payload, base_url):
        seen.update({
            "session": session_arg,
            "org_id": org_id,
            "payload": payload,
            "base_url": base_url,
        })
        return {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "id": "99",
            "userName": payload["userName"],
            "active": True,
        }

    monkeypatch.setattr(scim.svc, "create_or_update_user", _fake_create)

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.example") as client:
        resp = await client.post(
            "/scim/v2/Users",
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "userName": "engineer@example.com",
                "active": True,
            },
        )

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == "99"
    assert seen["session"] is session
    assert seen["org_id"] == "org_1"
    assert seen["payload"]["userName"] == "engineer@example.com"
    assert seen["base_url"] == "https://api.example"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_scim_delete_user_deprovisions_with_active_false_patch(monkeypatch):
    session = AsyncMock()
    session.commit = AsyncMock()
    seen = {}

    async def _fake_patch(session_arg, *, org_id, user_id, payload, base_url):
        seen.update({
            "session": session_arg,
            "org_id": org_id,
            "user_id": user_id,
            "payload": payload,
            "base_url": base_url,
        })
        return {"id": user_id, "active": False}

    monkeypatch.setattr(scim.svc, "patch_user", _fake_patch)

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.example") as client:
        resp = await client.delete("/scim/v2/Users/99")

    assert resp.status_code == 204
    assert seen["org_id"] == "org_1"
    assert seen["user_id"] == "99"
    assert seen["payload"]["Operations"][0]["path"] == "active"
    assert seen["payload"]["Operations"][0]["value"] is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_scim_refuses_a_shared_org_that_does_not_own_the_identity_provider(monkeypatch):
    """Only the SSO_ORG_ID org provisions: any other admin key gets a plain 403
    before a user is looked up or created."""
    created = []

    async def _fake_create(*_a, **_k):
        created.append(True)
        return {}

    monkeypatch.setattr(scim.svc, "create_or_update_user", _fake_create)
    for sso in ("org_other", "none", ""):
        monkeypatch.setenv("SSO_ORG_ID", sso)
        session = AsyncMock()
        session.commit = AsyncMock()
        app = _build_app(session)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.example") as client:
            for method, path in (("GET", "/scim/v2/ServiceProviderConfig"), ("POST", "/scim/v2/Users")):
                resp = await client.request(
                    method, path,
                    json={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                          "userName": "dana@othercorp.example"} if method == "POST" else None,
                )
                assert resp.status_code == 403, (sso, path, resp.text)
                detail = resp.json()["detail"]
                assert detail["code"] == "sso_org_required"
                assert "Single sign-on isn't set up for this organization" in detail["message"]
        session.commit.assert_not_awaited()
    assert created == []
