"""Tests for durable notification inbox service."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.models import Notification, NotificationRead
from src.services import notification_service as svc


def _result(*, first=None, all_rows=None):
    r = MagicMock()
    r.scalars.return_value.first.return_value = first
    r.scalars.return_value.all.return_value = all_rows or []
    r.all.return_value = all_rows or []
    return r


@pytest.mark.asyncio
async def test_emit_notification_creates_idempotent_source_row():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute.return_value = _result(first=None)

    row = await svc.emit_notification(
        session,
        org_id="org_1",
        actor_user_id=9,
        kind="decision.created",
        severity="pass",
        title="Verification recorded",
        body="make-now MJF",
        dest="records",
        source_type="cost_decision",
        source_id="dec_1",
        metadata={"filename": "cube.step"},
    )

    assert row.org_id == "org_1"
    assert row.kind == "decision.created"
    assert row.status == "open"
    assert row.dest == "records"
    assert row.metadata_json == {"filename": "cube.step"}
    session.add.assert_called_once_with(row)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_notification_reopens_existing_row():
    existing = Notification(
        ulid="01N",
        org_id="org_1",
        kind="governance.change_requested",
        severity="info",
        status="resolved",
        title="old",
        body="old",
        dest="verify",
        source_type="change_request",
        source_id="3",
        resolved_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute.return_value = _result(first=existing)

    row = await svc.emit_notification(
        session,
        org_id="org_1",
        kind="governance.change_requested",
        severity="cond",
        title="Governed change awaiting review",
        body="rates",
        dest="calibration",
        source_type="change_request",
        source_id="3",
    )

    assert row is existing
    assert row.status == "open"
    assert row.resolved_at is None
    assert row.severity == "cond"
    assert row.dest == "calibration"
    session.add.assert_not_called()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_by_source_marks_open_rows_resolved():
    row = Notification(
        ulid="01N",
        org_id="org_1",
        kind="governance.change_requested",
        severity="cond",
        status="open",
        title="review",
        body="rates",
        dest="calibration",
        source_type="change_request",
        source_id="3",
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    session.execute.return_value = _result(all_rows=[row])

    count = await svc.resolve_by_source(
        session,
        org_id="org_1",
        kind="governance.change_requested",
        source_type="change_request",
        source_id="3",
    )

    assert count == 1
    assert row.status == "resolved"
    assert row.resolved_at is not None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_read_adds_per_user_marker_once():
    row = Notification(
        ulid="01N",
        org_id="org_1",
        kind="decision.created",
        severity="pass",
        status="open",
        title="recorded",
        body="make-now",
        dest="records",
        source_type="cost_decision",
        source_id="dec_1",
    )
    row.id = 7
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute.side_effect = [_result(first=row), _result(first=None)]

    got = await svc.mark_read(
        session,
        org_id="org_1",
        user_id=11,
        notification_id="01N",
    )

    assert got is row
    marker = session.add.call_args.args[0]
    assert isinstance(marker, NotificationRead)
    assert marker.notification_id == 7
    assert marker.user_id == 11
    session.flush.assert_awaited_once()


def test_serialize_notification_maps_read_state():
    row = Notification(
        ulid="01N",
        org_id="org_1",
        kind="decision.created",
        severity="pass",
        status="open",
        title="Verification recorded",
        body="make-now mjf",
        dest="records",
        source_type="cost_decision",
        source_id="dec_1",
        metadata_json={"filename": "cube.step"},
        created_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )
    read_at = datetime(2026, 7, 8, tzinfo=timezone.utc)

    out = svc.serialize_notification(row, read_at=read_at)

    assert out["id"] == "01N"
    assert out["severity"] == "pass"
    assert out["metadata"] == {"filename": "cube.step"}
    assert out["is_read"] is True
    assert out["read_at"] == read_at.isoformat()
