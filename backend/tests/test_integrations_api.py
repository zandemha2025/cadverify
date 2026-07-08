"""Route tests for offline integration connector apparatus."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import integrations
from src.auth.rate_limit import limiter
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

    app.dependency_overrides[require_api_key] = _fake_user
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
        assert body["mode"] == "dry_run"
        assert body["status"] == "partial"
        assert body["rows_total"] == 2
        assert body["rows_valid"] == 1
        assert body["raw_stored"] is False
        assert body["file_sha256"]

    session.commit.assert_awaited_once()
