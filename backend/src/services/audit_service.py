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
# Refused writes
# ---------------------------------------------------------------------------

REFUSED_ACTION = "access.refused"

# (method or None for any write, path fragment, plain words). First match wins.
_ATTEMPTS: tuple[tuple[str | None, str, str], ...] = (
    (None, "/share", "share a part"),
    (None, "/api/v1/validate", "check a part"),
    (None, "/api/v1/uploads", "check a part"),
    (None, "/api/v1/checks", "check a part"),
    (None, "/reconstruct", "check a part"),
    (None, "/recheck", "re-check a part"),
    (None, "/orientation", "re-check a part"),
    (None, "/fixes/", "fix a part"),
    (None, "/repair", "fix a part"),
    (None, "/bodies", "split a part"),
    ("DELETE", "/api/v1/parts/", "delete a part"),
    (None, "/api/v1/part-context", "change a part's conditions or specs"),
    (None, "/api/v1/cost-decisions", "record a decision"),
    (None, "/api/v1/machine-inventory", "change the shop's machines"),
    (None, "/api/v1/rate-library", "change rates"),
    (None, "/api/v1/shop-library", "change the shop library"),
    (None, "/api/v1/material-library", "change materials"),
    (None, "/api/v1/orgs/invites", "invite a member"),
    (None, "/api/v1/orgs/members", "change a member"),
    (None, "/api/v1/orgs/current/delete", "delete the organization"),
    (None, "/api/v1/orgs", "change the organization"),
    (None, "/api/v1/batch", "start a batch"),
    (None, "/api/v1/catalog", "start a catalog run"),
    (None, "/api/v1/actuals", "import actuals"),
    (None, "/api/v1/bom", "import a parts list"),
    (None, "/api/v1/rfq-packages", "make a quote package"),
    (None, "/api/v1/integrations", "run an integration"),
    (None, "/scim/v2", "change a provisioned account"),
)


def attempted_action(method: str, path: str) -> str:
    """Plain words for what a refused request tried to do."""
    verb = (method or "").upper()
    for want, fragment, words in _ATTEMPTS:
        if (want is None or want == verb) and fragment in path:
            return words
    return f"{verb} {path}".strip()


async def record_refusal(
    *,
    user_id: int,
    org_id: str | None,
    method: str,
    path: str,
    org_role: str | None,
    reason: str,
    key_prefix: str | None = None,
) -> bool:
    """Log a refused write as ``access.refused`` ("Refused: <action>").

    Best effort and in its own transaction: the refusal stands whether or not
    this row is written. The same person refused on the same path for the same
    reason is logged once a minute, so a script retrying a refused write can't
    flood the log. Returns whether a row was written.
    """
    from sqlalchemy import text

    attempted = attempted_action(method, path)
    via = "session" if key_prefix in (None, "session") else "api_key"
    detail = {
        "attempted": attempted,
        "method": (method or "").upper(),
        "path": path[:300],
        "org_role": org_role,
        "reason": reason,
        "via": via,
    }
    if via == "api_key":
        detail["key_prefix"] = key_prefix
    async with get_session_factory()() as session:
        if org_id is None:
            from src.auth.org_context import resolve_org

            org_id = await resolve_org(session, user_id)
        recent = (
            await session.execute(
                text(
                    "SELECT 1 FROM audit_log WHERE user_id = :u AND action = :a "
                    "AND timestamp > now() - interval '1 minute' "
                    "AND detail_json->>'path' = :p AND detail_json->>'reason' = :r "
                    "LIMIT 1"
                ),
                {"u": user_id, "a": REFUSED_ACTION, "p": detail["path"], "r": reason},
            )
        ).first()
        if recent is not None:
            return False
        await append_audit_entry(
            session,
            user_id,
            REFUSED_ACTION,
            "request",
            None,
            detail,
            org_id=org_id,
            result_summary=f"Refused: {attempted}",
        )
        await session.commit()
    return True


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

    Entries are NEWEST first (``id`` DESC, the same keyset shape as the
    notification and integration-run lists): the first page is the most recent
    activity, and ``next_cursor`` (the last, oldest id on the page) fetches the
    next OLDER page. The CSV export below stays chronological for log files.
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
            .order_by(AuditLog.id.desc())
            .limit(limit + 1)
        )

        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if org_id is not None:
            stmt = stmt.where(AuditLog.org_id == org_id)
        if cursor is not None:
            stmt = stmt.where(AuditLog.id < int(cursor))

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

        # Same formula neutralising as every other CSV export.
        from src.services.cost_decision_service import spreadsheet_safe_cell

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "timestamp", "user_email", "action", "resource_type",
            "resource_id", "ip_address", "file_hash", "result_summary",
        ])
        for e in rows:
            writer.writerow([spreadsheet_safe_cell(cell) for cell in (
                e.timestamp.isoformat() if e.timestamp else "",
                e.user_email,
                e.action,
                e.resource_type,
                e.resource_id or "",
                e.ip_address or "",
                e.file_hash or "",
                e.result_summary or "",
            )])

        return output.getvalue()
    finally:
        if should_close:
            await session.close()
