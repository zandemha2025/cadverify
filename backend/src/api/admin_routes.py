"""Admin API routes -- user management, role assignment, and audit log export.

GET   /api/v1/admin/users              -- List all users (paginated)
GET   /api/v1/admin/users/{user_id}    -- User detail
PATCH /api/v1/admin/users/{user_id}/role -- Assign role
GET   /api/v1/admin/audit-log          -- Query/export audit log
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.db.models import Analysis, Batch, User
from src.services.audit_service import export_audit_csv, query_audit_log

logger = logging.getLogger("cadverify.admin")

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

_VALID_ROLES = frozenset(r.value for r in Role)


class RoleUpdate(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# GET /users -- list all users (cursor-paginated)
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    cursor: int | None = Query(None, description="User ID cursor for pagination"),
    limit: int = Query(20, ge=1, le=100),
    user: AuthedUser = Depends(require_role(Role.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """List all users with id, email, role, auth_provider, created_at."""
    stmt = select(User).order_by(User.id.asc()).limit(limit + 1)
    if cursor is not None:
        stmt = stmt.where(User.id > cursor)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]

    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
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
    user: AuthedUser = Depends(require_role(Role.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """User detail with role, created_at, analysis_count, batch_count."""
    target = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Count analyses and batches
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
    user: AuthedUser = Depends(require_role(Role.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a user's role. Admin cannot change own role."""
    if user.user_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot change own role")

    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{body.role}'. Must be one of: {', '.join(sorted(_VALID_ROLES))}",
        )

    target = (
        await session.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = target.role
    target.role = body.role
    await session.commit()

    # Audit: user.role_changed
    import asyncio
    from src.services.audit_service import fire_and_forget_audit, _lookup_email
    _admin_email = await _lookup_email(user.user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user.user_id, user_email=_admin_email,
        action="user.role_changed", resource_type="user",
        resource_id=str(user_id),
        detail={"old_role": old_role, "new_role": body.role, "changed_by": user.user_id},
    ))

    return {
        "id": target.id,
        "email": target.email,
        "role": target.role,
    }


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
    user: AuthedUser = Depends(require_role(Role.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Query or export the audit log. Requires admin role."""
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

    if format == "csv":
        csv_content = await export_audit_csv(
            start=start_dt, end=end_dt, user_id=user_id, action=action, session=session,
        )
        return PlainTextResponse(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
        )

    # Default: JSON with pagination
    result = await query_audit_log(
        start=start_dt, end=end_dt, user_id=user_id, action=action,
        cursor=cursor, limit=limit, session=session,
    )
    return result
