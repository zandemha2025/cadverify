"""Durable notifications API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import notification_service as svc

router = APIRouter(tags=["notifications"])


async def _org(session: AsyncSession, user: AuthedUser) -> str | None:
    return await resolve_org(session, user.user_id)


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_notifications(
    request: Request,
    response: Response,
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    unread: bool = Query(True),
    limit: int = Query(50, ge=1, le=100),
    cursor: int | None = Query(None, ge=1),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    if not org_id:
        return {"notifications": [], "next_cursor": None, "has_more": False}
    rows, has_more = await svc.list_notifications(
        session,
        org_id=org_id,
        user_id=user.user_id,
        status=status,
        unread=unread,
        limit=limit,
        cursor=cursor,
    )
    items = [
        svc.serialize_notification(row, read_at=read_at)
        for row, read_at in rows
    ]
    next_cursor = str(rows[-1][0].id) if has_more and rows else None
    return {"notifications": items, "next_cursor": next_cursor, "has_more": has_more}


@router.post("/{notification_id}/read")
@limiter.limit("120/hour;1000/day")
async def mark_notification_read(
    notification_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    if not org_id:
        return {"ok": True}
    row, read_at = await svc.mark_read(
        session,
        org_id=org_id,
        user_id=user.user_id,
        notification_id=notification_id,
    )
    await session.commit()
    return {
        "ok": True,
        "notification": svc.serialize_notification(row, read_at=read_at),
    }


@router.post("/read-all")
@limiter.limit("60/hour;300/day")
async def mark_all_notifications_read(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    count = 0
    if org_id:
        count = await svc.mark_all_read(session, org_id=org_id, user_id=user.user_id)
        await session.commit()
    return {"ok": True, "count": count}
