"""Audit logging service -- append-only audit trail for compliance.

Provides:
  - append_audit_entry() -- append inside a caller-owned transaction
  - log_action()         -- append and commit a standalone required event
  - emit_event()         -- concise transactional product-event wrapper
  - query_audit_log()    -- cursor-paginated query with filters
  - export_audit_csv()   -- CSV export of filtered audit entries

Audit writes are deliberately load-bearing. Security and product mutations add
their audit row to the SAME ``AsyncSession`` before commit, so the mutation and
its evidence either commit together or roll back together. Authentication flows
without an existing mutation transaction await ``log_action`` before issuing a
session. There is no background-task path that can lose an event on process exit.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session_factory
from src.db.models import AuditLog, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _lookup_email(session: AsyncSession, user_id: int | None) -> str:
    """Resolve the denormalized actor identity in the current transaction."""
    if user_id is None:
        return "system"
    row = (
        await session.execute(select(User.email).where(User.id == user_id))
    ).scalar_one_or_none()
    return row or f"user:{user_id}"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


async def append_audit_entry(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict | None = None,
    *,
    user_email: str | None = None,
    org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    file_hash: str | None = None,
    result_summary: str | None = None,
) -> None:
    """Add an audit row without committing the caller-owned transaction.

    Any lookup or insert failure propagates. The caller's subsequent commit is
    the durability boundary for both the protected mutation and this row.
    """
    if org_id is None and user_id is not None:
        from src.auth.org_context import resolve_org

        org_id = await resolve_org(session, user_id)
    if not user_email:
        user_email = await _lookup_email(session, user_id)
    session.add(
        AuditLog(
            user_id=user_id,
            org_id=org_id,
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
    )


async def log_action(
    user_id: int | None,
    user_email: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict | None = None,
    *,
    org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    file_hash: str | None = None,
    result_summary: str | None = None,
) -> None:
    """Commit one standalone required event, propagating any failure.

    Auth flows await this before returning a signed session. It is intentionally
    strict: an unavailable audit ledger makes the protected action unavailable.
    """
    async with get_session_factory()() as session:
        await append_audit_entry(
            session,
            user_id,
            action,
            resource_type,
            resource_id,
            detail,
            user_email=user_email,
            org_id=org_id,
            ip_address=ip_address,
            user_agent=user_agent,
            file_hash=file_hash,
            result_summary=result_summary,
        )
        await session.commit()


async def emit_event(
    session: AsyncSession,
    actor_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: dict | None = None,
    *,
    user_email: str | None = None,
    org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    file_hash: str | None = None,
    result_summary: str | None = None,
) -> None:
    """Append a product event to ``session``; caller commits it with mutation."""
    await append_audit_entry(
        session,
        actor_id,
        action,
        resource_type,
        resource_id,
        detail,
        user_email=user_email,
        org_id=org_id,
        ip_address=ip_address,
        user_agent=user_agent,
        file_hash=file_hash,
        result_summary=result_summary,
    )


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
    org_id: str | None = None,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    session: AsyncSession | None = None,
) -> dict:
    """Query audit_log with time range, optional filters, cursor pagination.

    ``org_id`` bounds the result to a single organization (W1 step 2 — an
    org-admin passes their org; a superadmin passes None for the unfiltered,
    platform-wide view). Returns
    {"entries": [...], "next_cursor": ..., "has_more": ...}.
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
        if org_id is not None:
            stmt = stmt.where(AuditLog.org_id == org_id)
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
    org_id: str | None = None,
    session: AsyncSession | None = None,
) -> str:
    """Return CSV string of audit entries matching filters.

    ``org_id`` bounds the export to a single organization (None = platform-wide,
    superadmin only). Columns: timestamp, user_email, action, resource_type,
    resource_id, ip_address, file_hash, result_summary.
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
        if org_id is not None:
            stmt = stmt.where(AuditLog.org_id == org_id)

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
