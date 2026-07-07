from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import rfq_packages
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import RfqPackage


def _package() -> RfqPackage:
    return RfqPackage(
        ulid="01RFQPACKAGE",
        org_id="org_1",
        user_id=11,
        title="Pump RFQ",
        supplier_name="Supplier A",
        item_count=1,
        approved_count=1,
        stale_count=0,
        unvalidated_count=1,
        raw_cad_included=False,
        live_supplier_send=False,
        items_json=[{"decision": {"id": "01DECISION", "filename": "part.step"}}],
        warnings_json=[],
        metadata_json={"contract": "should_cost_evidence_not_supplier_quote"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _build_app(session):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rfq_packages.router, prefix="/api/v1/rfq-packages")

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
async def test_create_list_detail_and_download_rfq_package(monkeypatch):
    session = AsyncMock()
    session.commit = AsyncMock()
    package = _package()
    monkeypatch.setattr(rfq_packages.svc, "create_package", AsyncMock(return_value=package))
    monkeypatch.setattr(rfq_packages.svc, "list_packages", AsyncMock(return_value=[package]))
    monkeypatch.setattr(rfq_packages.svc, "get_package", AsyncMock(return_value=package))
    monkeypatch.setattr(rfq_packages.svc, "build_zip", AsyncMock(return_value=b"PKZIP"))

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/v1/rfq-packages",
            json={
                "decision_ids": ["01DECISION"],
                "title": "Pump RFQ",
                "supplier_name": "Supplier A",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()["package"]
        assert body["id"] == "01RFQPACKAGE"
        assert body["live_supplier_send"] is False

        listed = await client.get("/api/v1/rfq-packages")
        assert listed.status_code == 200
        assert listed.json()["packages"][0]["title"] == "Pump RFQ"

        detail = await client.get("/api/v1/rfq-packages/01RFQPACKAGE")
        assert detail.status_code == 200
        assert detail.json()["package"]["items"][0]["decision"]["id"] == "01DECISION"

        download = await client.get("/api/v1/rfq-packages/01RFQPACKAGE/download.zip")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        assert "Pump_RFQ-01RFQPACKAGE.zip" in download.headers["content-disposition"]
        assert download.content == b"PKZIP"

    rfq_packages.svc.create_package.assert_awaited_once()
    session.commit.assert_awaited_once()
