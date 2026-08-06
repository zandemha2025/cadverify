"""Tests for durable notification inbox service."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

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

    got, read_at, dismissed_at = await svc.mark_read(
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
    assert marker.read_at == read_at
    assert read_at.tzinfo is not None
    assert dismissed_at is None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_read_returns_existing_persisted_timestamp():
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
    persisted_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    marker = NotificationRead(notification_id=7, user_id=11, read_at=persisted_at)
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute.side_effect = [_result(first=row), _result(first=marker)]

    got, read_at, dismissed_at = await svc.mark_read(
        session,
        org_id="org_1",
        user_id=11,
        notification_id="01N",
    )

    assert got is row
    assert read_at == persisted_at
    assert dismissed_at is None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_dismiss_notification_creates_personal_read_marker():
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

    got, read_at, dismissed_at = await svc.dismiss_notification(
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
    assert marker.read_at == read_at
    assert marker.dismissed_at == dismissed_at
    assert dismissed_at is not None
    assert dismissed_at.tzinfo is not None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_notification_preserves_existing_read_timestamp():
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
    persisted_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    marker = NotificationRead(notification_id=7, user_id=11, read_at=persisted_at)
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute.side_effect = [_result(first=row), _result(first=marker)]

    _, read_at, dismissed_at = await svc.dismiss_notification(
        session,
        org_id="org_1",
        user_id=11,
        notification_id="01N",
    )

    assert read_at == persisted_at
    assert dismissed_at is not None
    assert marker.dismissed_at == dismissed_at
    session.add.assert_not_called()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_notification_clears_only_dismissal_state():
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
    read_at = datetime(2026, 7, 8, tzinfo=timezone.utc)
    marker = NotificationRead(
        notification_id=7,
        user_id=11,
        read_at=read_at,
        dismissed_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )
    session = AsyncMock()
    session.flush = AsyncMock()
    session.execute.side_effect = [_result(first=row), _result(first=marker)]

    got, restored_read_at, dismissed_at = await svc.restore_notification(
        session,
        org_id="org_1",
        user_id=11,
        notification_id="01N",
    )

    assert got is row
    assert restored_read_at == read_at
    assert dismissed_at is None
    assert marker.dismissed_at is None
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_all_read_returns_the_exact_shared_timestamp():
    first = Notification(
        ulid="01A",
        org_id="org_1",
        kind="decision.created",
        severity="pass",
        status="open",
        title="first",
        body="",
        dest="records",
        source_type="cost_decision",
        source_id="dec_1",
    )
    second = Notification(
        ulid="01B",
        org_id="org_1",
        kind="decision.created",
        severity="pass",
        status="open",
        title="second",
        body="",
        dest="records",
        source_type="cost_decision",
        source_id="dec_2",
    )
    first.id = 7
    second.id = 8
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute.return_value = _result(all_rows=[first, second])

    count, read_at = await svc.mark_all_read(
        session,
        org_id="org_1",
        user_id=11,
    )

    assert count == 2
    assert read_at is not None
    markers = [call.args[0] for call in session.add.call_args_list]
    assert [marker.notification_id for marker in markers] == [7, 8]
    assert all(marker.user_id == 11 for marker in markers)
    assert all(marker.read_at == read_at for marker in markers)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_notification_hides_foreign_org_as_not_found():
    session = AsyncMock()
    session.execute.return_value = _result(first=None)

    with pytest.raises(HTTPException) as exc:
        await svc.dismiss_notification(
            session,
            org_id="org_b",
            user_id=12,
            notification_id="01ORG_A",
        )

    assert getattr(exc.value, "status_code", None) == 404
    assert getattr(exc.value, "detail", None) == "notification not found"


def test_serialize_notification_maps_read_and_dismissal_state():
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
    dismissed_at = datetime(2026, 7, 9, tzinfo=timezone.utc)

    out = svc.serialize_notification(
        row,
        read_at=read_at,
        dismissed_at=dismissed_at,
    )

    assert out["id"] == "01N"
    assert out["severity"] == "pass"
    assert out["metadata"] == {"filename": "cube.step"}
    assert out["is_read"] is True
    assert out["read_at"] == read_at.isoformat()
    assert out["is_dismissed"] is True
    assert out["dismissed_at"] == dismissed_at.isoformat()
