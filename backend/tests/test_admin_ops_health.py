from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import admin_routes
from src.auth.rbac import OrgAuthContext
from src.db.engine import get_db_session


def _build_app(session, ctx: OrgAuthContext):
    app = FastAPI()
    app.include_router(admin_routes.router)

    async def _fake_admin():
        return ctx

    async def _fake_session():
        yield session

    app.dependency_overrides[admin_routes.require_admin] = _fake_admin
    app.dependency_overrides[get_db_session] = _fake_session
    return app


@pytest.mark.asyncio
async def test_ops_queue_health_is_org_scoped_for_org_admin(monkeypatch):
    session = AsyncMock()
    summary = {
        "generated_at": "2026-07-07T00:00:00+00:00",
        "org_id": "org_a",
        "async": {"redis": True, "worker": "ok"},
        "jobs": {"status_counts": {"queued": 2}, "active_count": 2},
        "batches": {"status_counts": {"processing": 1}, "active_count": 1},
        "batch_items": {"status_counts": {"queued": 3}, "active_count": 3},
        "webhooks": {"status_counts": {"pending": 1}, "retry_due_count": 0},
    }
    mocked = AsyncMock(return_value=summary)
    monkeypatch.setattr(admin_routes, "summarize_queue_health", mocked)

    ctx = OrgAuthContext(
        user_id=11,
        api_key_id=0,
        key_prefix="session",
        role="analyst",
        is_superadmin=False,
        org_id="org_a",
        org_role="admin",
    )
    app = _build_app(session, ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/ops/queue-health")

    assert resp.status_code == 200
    assert resp.json()["org_id"] == "org_a"
    mocked.assert_awaited_once_with(session, org_id="org_a")


@pytest.mark.asyncio
async def test_ops_queue_health_superadmin_is_global(monkeypatch):
    session = AsyncMock()
    mocked = AsyncMock(return_value={"org_id": None, "generated_at": "now"})
    monkeypatch.setattr(admin_routes, "summarize_queue_health", mocked)

    ctx = OrgAuthContext(
        user_id=1,
        api_key_id=0,
        key_prefix="session",
        role="superadmin",
        is_superadmin=True,
    )
    app = _build_app(session, ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/admin/ops/queue-health")

    assert resp.status_code == 200
    mocked.assert_awaited_once_with(session, org_id=None)
