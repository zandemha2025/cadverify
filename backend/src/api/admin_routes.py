"""Admin API routes -- user management, role assignment, and audit log export.

GET   /api/v1/admin/users              -- List org members (paginated)
GET   /api/v1/admin/users/{user_id}    -- User detail
PATCH /api/v1/admin/users/{user_id}/role -- Assign role
GET   /api/v1/admin/audit-log          -- Query/export audit log

W1 step 2 — this router is the FIRST real consumer of org-scoped RBAC and of
``resolve_org``-style membership resolution. Access is gated by
``require_org_role(OrgRole.admin)`` (not the old platform ``require_role``), and
every read/write here is bounded to the caller's org:

  * a platform **superadmin** (``OrgAuthContext.is_superadmin``) sees/edits every
    user, every org's audit log — the old unfiltered behavior, now an explicit
    privileged path rather than the default;
  * an **org-admin** sees/edits only the members of their own org
    (``ctx.org_id``) and only their org's audit entries; cross-org reads 404 so
    existence never leaks across the tenant boundary.

The ~43 data routes are still on flat ``require_role`` — threading org filters
through them is W1 step 3, deliberately out of scope here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import (
    OrgAuthContext,
    OrgRole,
    Role,
    require_org_role,
    require_role,
)
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.db.models import (
    Analysis,
    Batch,
    CostDecision,
    Membership,
    UsageEvent,
    User,
    WebhookDelivery,
)
from src.services import org_service
from src.services.audit_service import export_audit_csv, query_audit_log
from src.services.ops_health_service import summarize_queue_health

logger = logging.getLogger("cadverify.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Shared dependency instance (not a fresh closure per route) so the org-admin
# gate resolves once per request and can be targeted by dependency overrides in
# tests. Every endpoint below requires org-admin (superadmin bypasses).
require_admin = require_org_role(OrgRole.admin)

# Platform roles assignable through this self-service endpoint. ``superadmin`` is
# intentionally excluded: platform staff are provisioned out-of-band, never
# granted via an org-admin PATCH (that would be privilege escalation).
_ASSIGNABLE_ROLES = frozenset({"viewer", "analyst", "admin"})


class RoleUpdate(BaseModel):
    role: str


async def _primary_membership(
    session: AsyncSession, user_id: int
) -> tuple[str, str] | None:
    """(org_id, org_role) for a user's oldest membership, else None."""
    row = (
        await session.execute(
            select(Membership.org_id, Membership.org_role)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at.asc(), Membership.id.asc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


# ---------------------------------------------------------------------------
# GET /users -- list org members (cursor-paginated)
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    cursor: int | None = Query(None, description="User ID cursor for pagination"),
    limit: int = Query(20, ge=1, le=100),
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """List users the caller may administer, each with their org role.

    Superadmin: every user platform-wide. Org-admin: only members of
    ``ctx.org_id`` (the org boundary is enforced with an INNER JOIN on
    ``memberships`` so no cross-org row can appear).
    """
    stmt = select(User).order_by(User.id.asc())
    if ctx.is_superadmin:
        # All users; org_role is enriched below from each user's primary org.
        if cursor is not None:
            stmt = stmt.where(User.id > cursor)
    else:
        # Bounded to the caller's org via the membership join.
        stmt = stmt.join(Membership, Membership.user_id == User.id).where(
            Membership.org_id == ctx.org_id
        )
        if cursor is not None:
            stmt = stmt.where(User.id > cursor)
    stmt = stmt.limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]

    # Enrich each row with its org_id/org_role. For an org-admin the boundary is
    # fixed to ctx.org_id; for a superadmin we surface each user's *primary*
    # membership (oldest), deduping defensively if a user has more than one.
    ids = [u.id for u in items]
    membership_by_user: dict[int, tuple[str, str]] = {}
    if ids:
        if ctx.is_superadmin:
            mrows = (
                await session.execute(
                    select(
                        Membership.user_id,
                        Membership.org_id,
                        Membership.org_role,
                    )
                    .where(Membership.user_id.in_(ids))
                    .order_by(
                        Membership.user_id.asc(),
                        Membership.created_at.asc(),
                        Membership.id.asc(),
                    )
                )
            ).all()
            for uid, oid, orole in mrows:
                # First row per user == oldest == primary; keep it.
                membership_by_user.setdefault(uid, (oid, orole))
        else:
            mrows = (
                await session.execute(
                    select(
                        Membership.user_id,
                        Membership.org_id,
                        Membership.org_role,
                    ).where(
                        Membership.user_id.in_(ids),
                        Membership.org_id == ctx.org_id,
                    )
                )
            ).all()
            for uid, oid, orole in mrows:
                membership_by_user[uid] = (oid, orole)

    def _org(uid: int) -> tuple[str | None, str | None]:
        m = membership_by_user.get(uid)
        return (m[0], m[1]) if m else (None, None)

    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "org_id": _org(u.id)[0],
                "org_role": _org(u.id)[1],
                "auth_provider": u.auth_provider,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in items
        ],
        "next_cursor": items[-1].id if items and has_more else None,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# GET /users/{user_id} -- user detail
# ---------------------------------------------------------------------------


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: int,
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """User detail with org role, created_at, analysis_count, batch_count.

    An org-admin may only view a user who is a member of their org; a user
    outside the boundary returns 404 (never leak cross-org existence).
    """
    target = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if ctx.is_superadmin:
        membership = await _primary_membership(session, user_id)
        org_id = membership[0] if membership else None
        org_role = membership[1] if membership else None
    else:
        row = (
            await session.execute(
                select(Membership.org_role).where(
                    Membership.user_id == user_id,
                    Membership.org_id == ctx.org_id,
                )
            )
        ).first()
        if row is None:
            # Target exists but is not in the caller's org -> hide it.
            raise HTTPException(status_code=404, detail="User not found")
        org_id = ctx.org_id
        org_role = row[0]

    analysis_count = (
        await session.execute(
            select(func.count()).select_from(Analysis).where(Analysis.user_id == user_id)
        )
    ).scalar_one()

    batch_count = (
        await session.execute(
            select(func.count()).select_from(Batch).where(Batch.user_id == user_id)
        )
    ).scalar_one()

    return {
        "id": target.id,
        "email": target.email,
        "role": target.role,
        "org_id": org_id,
        "org_role": org_role,
        "auth_provider": target.auth_provider,
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "analysis_count": analysis_count,
        "batch_count": batch_count,
    }


# ---------------------------------------------------------------------------
# PATCH /users/{user_id}/role -- assign role
# ---------------------------------------------------------------------------


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: RoleUpdate,
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a user's platform role. Org-admin cannot change own role, cannot
    grant ``superadmin``, and cannot touch a user outside their org (404)."""
    if ctx.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot change own role")

    if body.role not in _ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid role '{body.role}'. Must be one of: "
                f"{', '.join(sorted(_ASSIGNABLE_ROLES))}"
            ),
        )

    target = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    if not ctx.is_superadmin:
        row = (
            await session.execute(
                select(Membership.id).where(
                    Membership.user_id == user_id,
                    Membership.org_id == ctx.org_id,
                )
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")

    old_role = target.role
    target.role = body.role
    await session.commit()

    # Audit: user.role_changed
    import asyncio
    from src.services.audit_service import fire_and_forget_audit, _lookup_email
    _admin_email = await _lookup_email(ctx.user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=ctx.user_id, user_email=_admin_email,
        action="user.role_changed", resource_type="user",
        resource_id=str(user_id),
        detail={"old_role": old_role, "new_role": body.role, "changed_by": ctx.user_id},
    ))

    return {
        "id": target.id,
        "email": target.email,
        "role": target.role,
    }


# ---------------------------------------------------------------------------
# POST /users/{user_id}/deactivate | /reactivate -- account-level (superadmin)
# ---------------------------------------------------------------------------
#
# DESIGN CHOICE (documented): deactivation is ACCOUNT-LEVEL, not org-level. A
# user may belong to several orgs; flipping ``is_active`` blocks EVERY auth path
# (login, Google/SAML/magic re-provision, existing sessions, and the user's API
# keys), so it is a platform-staff (superadmin) action — an org admin must not be
# able to lock a shared account out of every other org. Org admins instead REMOVE
# a member from THEIR org (DELETE /api/v1/orgs/members/{id}), which is org-scoped
# and takes effect immediately via membership re-validation. This split keeps
# authority proportional to blast radius.

require_superadmin = require_role(Role.superadmin)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    user: AuthedUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db_session),
):
    """Deactivate an account (superadmin). Blocks every auth path; the user's
    existing sessions and API keys stop working immediately."""
    if user.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
    result = await org_service.set_user_active(session, user_id, active=False)
    await session.commit()

    import asyncio
    from src.services.audit_service import _lookup_email, fire_and_forget_audit
    _actor_email = await _lookup_email(user.user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user.user_id, user_email=_actor_email,
        action="user.deactivated", resource_type="user",
        resource_id=str(user_id), detail={"deactivated_by": user.user_id},
    ))
    return result


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(
    user_id: int,
    user: AuthedUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db_session),
):
    """Reactivate a deactivated account (superadmin)."""
    result = await org_service.set_user_active(session, user_id, active=True)
    await session.commit()

    import asyncio
    from src.services.audit_service import _lookup_email, fire_and_forget_audit
    _actor_email = await _lookup_email(user.user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user.user_id, user_email=_actor_email,
        action="user.reactivated", resource_type="user",
        resource_id=str(user_id), detail={"reactivated_by": user.user_id},
    ))
    return result


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    user_id: int,
    user: AuthedUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db_session),
):
    """Invalidate every dashboard session for an account (superadmin)."""
    result = await org_service.revoke_user_sessions(session, user_id)
    await session.commit()

    import asyncio
    from src.services.audit_service import _lookup_email, fire_and_forget_audit
    _actor_email = await _lookup_email(user.user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user.user_id, user_email=_actor_email,
        action="user.sessions_revoked", resource_type="user",
        resource_id=str(user_id), detail={"revoked_by": user.user_id},
    ))
    return result


# ---------------------------------------------------------------------------
# GET /usage-summary -- real org usage counters for the product settings panel
# ---------------------------------------------------------------------------


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/usage-summary")
async def get_usage_summary(
    days: int = Query(30, ge=1, le=90, description="Trailing window in days"),
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Org-scoped usage counters from persisted tables, never design fixtures.

    These are deliberately separate real counts because the product has multiple
    durable streams: DFM analyses, saved should-cost decisions, usage-event rows,
    and webhook deliveries. The UI can label each precisely instead of laundering
    them into one invented "verifications" number.
    """
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    org_filter = None if ctx.is_superadmin else ctx.org_id

    async def _count(model, created_col):
        stmt = select(func.count()).select_from(model).where(created_col >= since)
        if org_filter is not None:
            stmt = stmt.where(model.org_id == org_filter)
        return int((await session.execute(stmt)).scalar_one())

    analyses = await _count(Analysis, Analysis.created_at)
    cost_decisions = await _count(CostDecision, CostDecision.created_at)
    usage_events = await _count(UsageEvent, UsageEvent.created_at)
    webhook_deliveries = await _count(WebhookDelivery, WebhookDelivery.created_at)

    event_stmt = (
        select(UsageEvent.event_type, func.count())
        .where(UsageEvent.created_at >= since)
        .group_by(UsageEvent.event_type)
        .order_by(UsageEvent.event_type.asc())
    )
    if org_filter is not None:
        event_stmt = event_stmt.where(UsageEvent.org_id == org_filter)
    event_counts = {
        str(event_type): int(count)
        for event_type, count in (await session.execute(event_stmt)).all()
    }

    delivery_stmt = (
        select(WebhookDelivery.status, func.count())
        .where(WebhookDelivery.created_at >= since)
        .group_by(WebhookDelivery.status)
        .order_by(WebhookDelivery.status.asc())
    )
    if org_filter is not None:
        delivery_stmt = delivery_stmt.where(WebhookDelivery.org_id == org_filter)
    delivery_counts = {
        str(status): int(count)
        for status, count in (await session.execute(delivery_stmt)).all()
    }

    return {
        "window_days": days,
        "since": _iso(since),
        "until": _iso(now),
        "org_id": org_filter,
        "counts": {
            "analyses": analyses,
            "cost_decisions": cost_decisions,
            "usage_events": usage_events,
            "webhook_deliveries": webhook_deliveries,
        },
        "event_counts": event_counts,
        "webhook_status_counts": delivery_counts,
    }


# ---------------------------------------------------------------------------
# GET /webhook-deliveries -- latest org-scoped delivery attempts
# ---------------------------------------------------------------------------


@router.get("/webhook-deliveries")
async def list_webhook_deliveries(
    limit: int = Query(20, ge=1, le=100),
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Latest webhook deliveries from the durable delivery table.

    The payload is intentionally not returned here; the settings surface needs
    delivery status and retry timing, not customer payload bodies.
    """
    stmt = (
        select(WebhookDelivery, Batch.ulid)
        .join(Batch, Batch.id == WebhookDelivery.batch_id)
        .order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
        .limit(limit)
    )
    if not ctx.is_superadmin:
        stmt = stmt.where(WebhookDelivery.org_id == ctx.org_id)

    rows = (await session.execute(stmt)).all()
    return {
        "deliveries": [
            {
                "id": delivery.id,
                "batch_id": delivery.batch_id,
                "batch_ulid": batch_ulid,
                "event_type": delivery.event_type,
                "status": delivery.status,
                "attempts": delivery.attempts,
                "response_code": delivery.response_code,
                "created_at": _iso(delivery.created_at),
                "last_attempt_at": _iso(delivery.last_attempt_at),
                "next_retry_at": _iso(delivery.next_retry_at),
            }
            for delivery, batch_ulid in rows
        ]
    }


# ---------------------------------------------------------------------------
# GET /ops/queue-health -- org-scoped async/batch/worker posture
# ---------------------------------------------------------------------------


@router.get("/ops/queue-health")
async def get_ops_queue_health(
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """PII-free queue, batch, webhook, and worker posture for operators."""
    org_filter = None if ctx.is_superadmin else ctx.org_id
    return await summarize_queue_health(session, org_id=org_filter)


# ---------------------------------------------------------------------------
# GET /audit-log -- query / export audit log
# ---------------------------------------------------------------------------

_MAX_AUDIT_RANGE_DAYS = 90


@router.get("/audit-log")
async def get_audit_log(
    start: str = Query(..., description="ISO datetime start (inclusive)"),
    end: str = Query(..., description="ISO datetime end (inclusive)"),
    user_id: int | None = Query(None, description="Filter by user ID"),
    action: str | None = Query(None, description="Filter by action string"),
    format: str = Query("json", description="Output format: json or csv"),
    cursor: str | None = Query(None, description="Pagination cursor (entry ID)"),
    limit: int = Query(50, ge=1, le=200, description="Page size (max 200)"),
    ctx: OrgAuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
):
    """Query or export the audit log. Org-admin sees only their org's entries;
    superadmin sees every org's (org filter = None)."""
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO datetime for start or end")

    # Enforce 90-day max range
    if (end_dt - start_dt) > timedelta(days=_MAX_AUDIT_RANGE_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"Time range exceeds maximum of {_MAX_AUDIT_RANGE_DAYS} days",
        )

    # Org boundary: superadmin unfiltered; org-admin bounded to their org.
    org_filter = None if ctx.is_superadmin else ctx.org_id

    if format == "csv":
        csv_content = await export_audit_csv(
            start=start_dt, end=end_dt, user_id=user_id, action=action,
            org_id=org_filter, session=session,
        )
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
        )

    # Default: JSON with pagination
    result = await query_audit_log(
        start=start_dt, end=end_dt, user_id=user_id, action=action,
        org_id=org_filter, cursor=cursor, limit=limit, session=session,
    )
    return result
