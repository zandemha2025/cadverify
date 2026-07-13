"""Route tests for durable notification inbox API."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import notifications
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Notification


def _build_app(session):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(notifications.router, prefix="/api/v1/notifications")

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
async def test_notifications_routes_list_and_mark(monkeypatch):
    session = AsyncMock()
    session.commit = AsyncMock()
    monkeypatch.setattr(notifications, "_org", AsyncMock(return_value="org_1"))

    row = Notification(
        ulid="01NOTIFY",
        org_id="org_1",
        kind="decision.created",
        severity="pass",
        status="open",
        title="Verification recorded",
        body="make-now mjf",
        dest="records",
        source_type="cost_decision",
        source_id="dec_1",
        created_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )
    row.id = 42

    async def _fake_list(session_arg, **kwargs):
        assert session_arg is session
        assert kwargs["org_id"] == "org_1"
        assert kwargs["user_id"] == 11
        assert kwargs["limit"] == 25
        return [(row, None)], False

    async def _fake_mark_read(session_arg, **kwargs):
        assert session_arg is session
        assert kwargs["notification_id"] == "01NOTIFY"
        return row, datetime(2026, 7, 8, tzinfo=timezone.utc)

    async def _fake_mark_all(session_arg, **kwargs):
        assert session_arg is session
        assert kwargs["org_id"] == "org_1"
        return 3

    monkeypatch.setattr(notifications.svc, "list_notifications", _fake_list)
    monkeypatch.setattr(notifications.svc, "mark_read", _fake_mark_read)
    monkeypatch.setattr(notifications.svc, "mark_all_read", _fake_mark_all)

    app = _build_app(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/v1/notifications?limit=25")
        assert listed.status_code == 200
        body = listed.json()
        assert body["notifications"][0]["id"] == "01NOTIFY"
        assert body["notifications"][0]["dest"] == "records"
        assert body["has_more"] is False

        marked = await client.post("/api/v1/notifications/01NOTIFY/read")
        assert marked.status_code == 200
        marked_body = marked.json()["notification"]
        assert marked_body["id"] == "01NOTIFY"
        assert marked_body["is_read"] is True
        assert marked_body["read_at"] == "2026-07-08T00:00:00+00:00"

        read_all = await client.post("/api/v1/notifications/read-all")
        assert read_all.status_code == 200
        assert read_all.json() == {"ok": True, "count": 3}

    assert session.commit.await_count == 2
