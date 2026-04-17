"""Audit logging service -- append-only audit trail for compliance.

Provides:
  - log_action()           -- insert a single audit_log row
  - fire_and_forget_audit() -- background wrapper for log_action
  - query_audit_log()      -- cursor-paginated query with filters
  - export_audit_csv()     -- CSV export of filtered audit entries
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session_factory
from src.db.models import AuditLog

logger = logging.getLogger("cadverify.audit")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _lookup_email(user_id: int | None) -> str:
    """Best-effort email lookup for audit. Returns 'system' if not found."""
    if user_id is None:
        return "system"
    try:
        from src.db.models import User

        async with get_session_factory()() as session:
            from sqlalchemy import select as _sel
            row = (await session.execute(
                _sel(User.email).where(User.id == user_id)
            )).scalar_one_or_none()
            return row or f"user:{user_id}"
    except Exception:
        return f"user:{user_id}"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def log_action(
    user_id: int | None,
    user_email: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    file_hash: str | None = None,
    result_summary: str | None = None,
) -> None:
    """Insert an audit_log row. Swallows DB errors to avoid breaking requests."""
    try:
        async with get_session_factory()() as session:
            entry = AuditLog(
                user_id=user_id,
                user_email=user_email,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail_json=detail,
                ip_address=ip_address,
                user_agent=user_agent,
                file_hash=file_hash,
                result_summary=result_summary,
            )
            session.add(entry)
            await session.commit()
    except Exception:
        logger.exception("Failed to write audit log entry action=%s", action)


async def fire_and_forget_audit(**kwargs) -> None:
    """Wrapper that calls log_action in a background task.

    Usage from routes: asyncio.create_task(fire_and_forget_audit(...))
    """
    await log_action(**kwargs)


# ---------------------------------------------------------------------------
# Read / Query
# ---------------------------------------------------------------------------

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


async def query_audit_log(
    start: datetime,
    end: datetime,
    user_id: int | None = None,
    action: str | None = None,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    session: AsyncSession | None = None,
) -> dict:
    """Query audit_log with time range, optional filters, cursor pagination.

    Returns {"entries": [...], "next_cursor": ..., "has_more": ...}.
    """
    limit = max(1, min(limit, _MAX_LIMIT))

    should_close = False
    if session is None:
        session = get_session_factory()()
        should_close = True

    try:
        stmt = (
            select(AuditLog)
            .where(AuditLog.timestamp >= start, AuditLog.timestamp <= end)
            .order_by(AuditLog.id.asc())
            .limit(limit + 1)
        )

        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if cursor is not None:
            stmt = stmt.where(AuditLog.id > int(cursor))

        rows = (await session.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        items = list(rows[:limit])

        entries = [
            {
                "id": e.id,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "user_id": e.user_id,
                "user_email": e.user_email,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "detail": e.detail_json,
                "ip_address": e.ip_address,
                "file_hash": e.file_hash,
                "result_summary": e.result_summary,
            }
            for e in items
        ]

        next_cursor = str(items[-1].id) if items and has_more else None

        return {"entries": entries, "next_cursor": next_cursor, "has_more": has_more}
    finally:
        if should_close:
            await session.close()


async def export_audit_csv(
    start: datetime,
    end: datetime,
    user_id: int | None = None,
    action: str | None = None,
    session: AsyncSession | None = None,
) -> str:
    """Return CSV string of audit entries matching filters.

    Columns: timestamp, user_email, action, resource_type, resource_id,
    ip_address, file_hash, result_summary.
    """
    should_close = False
    if session is None:
        session = get_session_factory()()
        should_close = True

    try:
        stmt = (
            select(AuditLog)
            .where(AuditLog.timestamp >= start, AuditLog.timestamp <= end)
            .order_by(AuditLog.id.asc())
        )

        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)

        rows = (await session.execute(stmt)).scalars().all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "timestamp", "user_email", "action", "resource_type",
            "resource_id", "ip_address", "file_hash", "result_summary",
        ])
        for e in rows:
            writer.writerow([
                e.timestamp.isoformat() if e.timestamp else "",
                e.user_email,
                e.action,
                e.resource_type,
                e.resource_id or "",
                e.ip_address or "",
                e.file_hash or "",
                e.result_summary or "",
            ])

        return output.getvalue()
    finally:
        if should_close:
            await session.close()
