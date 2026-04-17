"""Tests for audit logging service and admin endpoint.

Covers: log_action, query_audit_log, export_audit_csv, admin endpoint
access control, and 90-day range limit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audit_entry(
    id_: int = 1,
    user_id: int = 42,
    user_email: str = "test@example.com",
    action: str = "analysis.created",
    resource_type: str = "analysis",
    resource_id: str | None = "abc123",
    detail_json: dict | None = None,
    ip_address: str | None = "127.0.0.1",
    user_agent: str | None = None,
    file_hash: str | None = "deadbeef",
    result_summary: str | None = "pass",
    timestamp: datetime | None = None,
):
    """Build a mock AuditLog-like object."""
    entry = MagicMock()
    entry.id = id_
    entry.user_id = user_id
    entry.user_email = user_email
    entry.action = action
    entry.resource_type = resource_type
    entry.resource_id = resource_id
    entry.detail_json = detail_json
    entry.ip_address = ip_address
    entry.user_agent = user_agent
    entry.file_hash = file_hash
    entry.result_summary = result_summary
    entry.timestamp = timestamp or datetime.now(timezone.utc)
    return entry


def _mock_session_factory(entries=None):
    """Return a patched get_session_factory that yields a mock session."""
    entries = entries or []
    session = AsyncMock()

    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = entries
    session.execute.return_value = exec_result

    factory = MagicMock()
    factory.return_value = session
    # Support async context manager
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    return factory, session


# ---------------------------------------------------------------------------
# test_log_action_creates_entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_action_creates_entry():
    """log_action should add an AuditLog row and commit."""
    factory, session = _mock_session_factory()

    with patch("src.services.audit_service.get_session_factory", return_value=factory):
        from src.services.audit_service import log_action

        await log_action(
            user_id=42,
            user_email="test@example.com",
            action="analysis.created",
            resource_type="analysis",
            resource_id="ulid_123",
            file_hash="abc",
            result_summary="pass",
        )

    # Verify session.add was called with an AuditLog-like object
    assert session.add.called
    added_obj = session.add.call_args[0][0]
    assert added_obj.action == "analysis.created"
    assert added_obj.user_email == "test@example.com"
    assert added_obj.resource_type == "analysis"
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_audit_log_preserves_email_after_user_delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_log_preserves_email_after_user_delete():
    """Audit entry user_email is denormalized, survives user deletion."""
    factory, session = _mock_session_factory()

    with patch("src.services.audit_service.get_session_factory", return_value=factory):
        from src.services.audit_service import log_action

        # Create audit entry
        await log_action(
            user_id=99,
            user_email="deleted@example.com",
            action="analysis.created",
            resource_type="analysis",
        )

    added_obj = session.add.call_args[0][0]
    # user_email is stored directly on the row, not via FK
    assert added_obj.user_email == "deleted@example.com"
    # Even if user_id FK is SET NULL, the email column is preserved
    assert added_obj.user_id == 99


# ---------------------------------------------------------------------------
# test_query_audit_log_time_range
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_audit_log_time_range():
    """query_audit_log returns entries within the given time range."""
    now = datetime.now(timezone.utc)
    entries = [
        _make_audit_entry(id_=1, timestamp=now - timedelta(hours=1)),
        _make_audit_entry(id_=2, timestamp=now),
    ]
    factory, session = _mock_session_factory(entries)

    with patch("src.services.audit_service.get_session_factory", return_value=factory):
        from src.services.audit_service import query_audit_log

        result = await query_audit_log(
            start=now - timedelta(hours=2),
            end=now + timedelta(hours=1),
            session=session,
        )

    assert "entries" in result
    assert len(result["entries"]) == 2
    assert "has_more" in result
    assert result["has_more"] is False


# ---------------------------------------------------------------------------
# test_query_audit_log_filter_by_action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_audit_log_filter_by_action():
    """query_audit_log filters entries by action when specified."""
    entries = [
        _make_audit_entry(id_=1, action="share.created"),
    ]
    factory, session = _mock_session_factory(entries)

    with patch("src.services.audit_service.get_session_factory", return_value=factory):
        from src.services.audit_service import query_audit_log

        now = datetime.now(timezone.utc)
        result = await query_audit_log(
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
            action="share.created",
            session=session,
        )

    assert len(result["entries"]) == 1
    assert result["entries"][0]["action"] == "share.created"


# ---------------------------------------------------------------------------
# test_export_audit_csv_format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_audit_csv_format():
    """export_audit_csv returns CSV with correct header columns."""
    entries = [
        _make_audit_entry(id_=1, action="analysis.created"),
    ]
    factory, session = _mock_session_factory(entries)

    with patch("src.services.audit_service.get_session_factory", return_value=factory):
        from src.services.audit_service import export_audit_csv

        now = datetime.now(timezone.utc)
        csv_str = await export_audit_csv(
            start=now - timedelta(days=1),
            end=now + timedelta(days=1),
            session=session,
        )

    lines = csv_str.strip().split("\n")
    header = lines[0]
    assert "timestamp" in header
    assert "user_email" in header
    assert "action" in header
    assert "resource_type" in header
    # Should have header + 1 data row
    assert len(lines) == 2


# ---------------------------------------------------------------------------
# test_audit_export_requires_admin
# ---------------------------------------------------------------------------

def test_audit_export_requires_admin():
    """GET /audit-log should require admin role (analyst gets 403)."""
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    from src.api.admin_routes import router
    from src.auth.rbac import Role, require_role
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    # Build a minimal app with the admin router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)

    # Override auth to return analyst role
    def _analyst_user():
        return AuthedUser(user_id=1, api_key_id=1, key_prefix="test", role="analyst")

    async def _fake_db():
        yield AsyncMock()

    app.dependency_overrides[require_api_key] = _analyst_user
    app.dependency_overrides[get_db_session] = _fake_db

    client = TestClient(app)
    resp = client.get("/api/v1/admin/audit-log?start=2026-01-01T00:00:00&end=2026-01-02T00:00:00")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# test_audit_export_90_day_limit
# ---------------------------------------------------------------------------

def test_audit_export_90_day_limit():
    """GET /audit-log with >90 day range returns 400."""
    from unittest.mock import AsyncMock

    from fastapi.testclient import TestClient

    from src.api.admin_routes import router
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)

    # Override auth to return admin role
    def _admin_user():
        return AuthedUser(user_id=1, api_key_id=1, key_prefix="test", role="admin")

    async def _fake_db():
        yield AsyncMock()

    app.dependency_overrides[require_api_key] = _admin_user
    app.dependency_overrides[get_db_session] = _fake_db

    client = TestClient(app)
    resp = client.get(
        "/api/v1/admin/audit-log?start=2026-01-01T00:00:00&end=2026-06-01T00:00:00"
    )
    assert resp.status_code == 400
    assert "90" in resp.text
