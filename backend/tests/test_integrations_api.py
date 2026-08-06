"""Route tests for offline integration connector apparatus."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import integrations
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session


def _build_app(session):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(integrations.router, prefix="/api/v1/integrations")

    async def _fake_user():
        return AuthedUser(
            user_id=11,
            api_key_id=0,
            key_prefix="session",
            role="analyst",
        )

    async def _fake_session():
        yield session

    async def _fake_org_admin():
        return OrgAuthContext(
            user_id=11,
            api_key_id=0,
            key_prefix="session",
            role="analyst",
            is_superadmin=False,
            org_id="org_1",
            org_role="admin",
        )

    app.dependency_overrides[require_api_key] = _fake_user
    app.dependency_overrides[integrations.require_integration_admin] = _fake_org_admin
    app.dependency_overrides[get_db_session] = _fake_session
    return app


@pytest.mark.asyncio
async def test_connector_registry_and_dry_run_route(monkeypatch):
    session = AsyncMock()
    session.add = lambda obj: None
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    monkeypatch.setattr(integrations, "_require_org", AsyncMock(return_value="org_1"))

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        registry = await client.get("/api/v1/integrations/connectors")
        assert registry.status_code == 200
        assert any(
            c["id"] == "sap_manifest_csv"
            for c in registry.json()["connectors"]
        )

        csv = (
            "part_id,description,material_class\n"
            "P-100,Valve body,steel\n"
            ",Missing part,steel\n"
        )
        run = await client.post(
            "/api/v1/integrations/runs",
            data={"connector_id": "sap_manifest_csv", "mode": "dry_run"},
            files={"file": ("sap.csv", csv, "text/csv")},
        )
        assert run.status_code == 200, run.text
        body = run.json()["run"]
        assert body["connector_id"] == "sap_manifest_csv"
        assert body["connector_mode"] == "offline_csv"
        assert body["boundary_label"] == "exported_fixture"
        assert body["mode"] == "dry_run"
        assert body["status"] == "partial"
        assert body["source_record_count"] == 2
        assert body["normalized_record_count"] == 1
        assert body["rows_total"] == 2
        assert body["rows_valid"] == 1
        assert body["raw_stored"] is False
        assert body["file_sha256"]

    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_credential_profile_routes_are_org_scoped_and_redacted(monkeypatch):
    session = AsyncMock()
    session.commit = AsyncMock()
    seen = {}
    profile = object()

    async def _create(session_arg, **kwargs):
        seen.update(kwargs)
        assert session_arg is session
        return profile

    def _serialize(row):
        assert row is profile
        return {
            "id": "01CRED",
            "connector_id": "sap_s4hana_product_bom_readonly",
            "label": "SAP sandbox",
            "base_url": "https://sap.example",
            "auth_type": "bearer",
            "secret_fingerprint": "abc123",
            "configured": True,
        }

    monkeypatch.setattr(integrations.creds, "create_profile", _create)
    monkeypatch.setattr(integrations.creds, "serialize_profile", _serialize)

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/integrations/credential-profiles",
            json={
                "connector_id": "sap_s4hana_product_bom_readonly",
                "label": "SAP sandbox",
                "base_url": "https://sap.example",
                "auth_type": "bearer",
                "secret": {"token": "secret-token"},
            },
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()["profile"]
    assert body["id"] == "01CRED"
    assert body["secret_fingerprint"] == "abc123"
    assert "secret-token" not in resp.text
    assert seen["org_id"] == "org_1"
    assert seen["user_id"] == 11
    assert seen["secret"] == {"token": "secret-token"}
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_credential_profile_probe_route_redacts_secret(monkeypatch):
    session = AsyncMock()
    profile = object()

    async def _get(session_arg, *, org_id, profile_id):
        assert session_arg is session
        assert org_id == "org_1"
        assert profile_id == "01CRED"
        return profile

    monkeypatch.setattr(integrations.creds, "get_profile", _get)
    monkeypatch.setattr(
        integrations.creds,
        "probe_profile",
        lambda row: {
            "credential_profile_id": "01CRED",
            "connector_id": "sap_s4hana_product_bom_readonly",
            "configured": True,
            "read_only": True,
            "boundary_label": "sandbox",
            "secret_fingerprint": "abc123",
        },
    )

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/v1/integrations/credential-profiles/01CRED/probe")

    assert resp.status_code == 200, resp.text
    assert resp.json()["probe"]["configured"] is True
    assert resp.json()["probe"]["read_only"] is True
    assert "secret-token" not in resp.text
