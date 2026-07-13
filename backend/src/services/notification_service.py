"""Durable notification inbox service.

Notifications are workflow state, not audit history. Producers emit idempotent
rows beside domain mutations; readers mark rows read per user. Source-of-truth
records remain the domain tables.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import Notification, NotificationRead

VALID_DESTS = {"records", "calibration", "verify"}
VALID_SEVERITIES = {"pass", "cond", "info"}
VALID_STATUSES = {"open", "resolved"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_dest(dest: str) -> str:
    return dest if dest in VALID_DESTS else "verify"


def _clean_severity(severity: str) -> str:
    return severity if severity in VALID_SEVERITIES else "info"


def _source(source_type: Optional[str], source_id: Optional[str]) -> tuple[str, str]:
    st = (source_type or "manual").strip() or "manual"
    sid = (source_id or st).strip() or st
    return st[:120], sid[:240]


async def emit_notification(
    session: AsyncSession,
    *,
    org_id: str,
    kind: str,
    title: str,
    body: str = "",
    dest: str = "verify",
    severity: str = "info",
    source_type: Optional[str] = None,
    source_id: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    audience_role: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Notification:
    """Create or reopen/update an idempotent notification row."""
    st, sid = _source(source_type, source_id)
    existing = (
        await session.execute(
            select(Notification).where(
                Notification.org_id == org_id,
                Notification.kind == kind,
                Notification.source_type == st,
                Notification.source_id == sid,
            )
        )
    ).scalars().first()
    if existing is None:
        row = Notification(
            ulid=str(ULID()),
            org_id=org_id,
            actor_user_id=actor_user_id,
            kind=kind,
            severity=_clean_severity(severity),
            status="open",
            audience_role=audience_role,
            title=title,
            body=body or "",
            dest=_clean_dest(dest),
            source_type=st,
            source_id=sid,
            metadata_json=metadata or None,
        )
        session.add(row)
        await session.flush()
        return row

    existing.actor_user_id = actor_user_id
    existing.severity = _clean_severity(severity)
    existing.status = "open"
    existing.audience_role = audience_role
    existing.title = title
    existing.body = body or ""
    existing.dest = _clean_dest(dest)
    existing.metadata_json = metadata or None
    existing.resolved_at = None
    await session.flush()
    return existing


async def resolve_by_source(
    session: AsyncSession,
    *,
    org_id: str,
    source_type: str,
    source_id: str,
    kind: Optional[str] = None,
) -> int:
    """Mark open notifications for a source resolved."""
    st, sid = _source(source_type, source_id)
    stmt = select(Notification).where(
        Notification.org_id == org_id,
        Notification.source_type == st,
        Notification.source_id == sid,
        Notification.status == "open",
    )
    if kind:
        stmt = stmt.where(Notification.kind == kind)
    rows = list((await session.execute(stmt)).scalars().all())
    when = _now()
    for row in rows:
        row.status = "resolved"
        row.resolved_at = when
    if rows:
        await session.flush()
    return len(rows)


async def list_notifications(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: int,
    status: str = "open",
    unread: bool = True,
    limit: int = 50,
    cursor: Optional[int] = None,
) -> tuple[list[tuple[Notification, Optional[datetime]]], bool]:
    """Return newest notifications plus per-user read state."""
    stmt = (
        select(Notification, NotificationRead.read_at)
        .outerjoin(
            NotificationRead,
            and_(
                NotificationRead.notification_id == Notification.id,
                NotificationRead.user_id == user_id,
            ),
        )
        .where(Notification.org_id == org_id)
    )
    if status != "all":
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="invalid notification status")
        stmt = stmt.where(Notification.status == status)
    if unread:
        stmt = stmt.where(NotificationRead.id.is_(None))
    if cursor is not None:
        stmt = stmt.where(Notification.id < cursor)
    stmt = stmt.order_by(Notification.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).all())
    return rows[:limit], len(rows) > limit


async def mark_read(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: int,
    notification_id: str,
) -> tuple[Notification, datetime]:
    row = (
        await session.execute(
            select(Notification).where(
                Notification.org_id == org_id,
                Notification.ulid == notification_id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="notification not found")
    existing = (
        await session.execute(
            select(NotificationRead).where(
                NotificationRead.notification_id == row.id,
                NotificationRead.user_id == user_id,
            )
        )
    ).scalars().first()
    if existing is None:
        existing = NotificationRead(
            notification_id=row.id,
            user_id=user_id,
            read_at=_now(),
        )
        session.add(existing)
        await session.flush()
    return row, existing.read_at


async def mark_all_read(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: int,
) -> int:
    rows = (
        await session.execute(
            select(Notification)
            .outerjoin(
                NotificationRead,
                and_(
                    NotificationRead.notification_id == Notification.id,
                    NotificationRead.user_id == user_id,
                ),
            )
            .where(
                Notification.org_id == org_id,
                Notification.status == "open",
                NotificationRead.id.is_(None),
            )
        )
    ).scalars().all()
    for row in rows:
        session.add(NotificationRead(notification_id=row.id, user_id=user_id))
    if rows:
        await session.flush()
    return len(rows)


def serialize_notification(
    row: Notification,
    *,
    read_at: Optional[datetime] = None,
) -> dict:
    return {
        "id": row.ulid,
        "kind": row.kind,
        "severity": row.severity,
        "status": row.status,
        "audience_role": row.audience_role,
        "title": row.title,
        "body": row.body,
        "dest": row.dest,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "metadata": row.metadata_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "read_at": read_at.isoformat() if read_at else None,
        "is_read": read_at is not None,
    }
