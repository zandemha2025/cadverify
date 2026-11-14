"""Authenticated, org-scoped portfolio intelligence reads."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import portfolio_intelligence_service as service

router = APIRouter()


@router.get("/blocker-clusters")
@limiter.limit("60/hour;500/day")
async def get_blocker_clusters(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Recurring blockers across distinct latest parts in the active org."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="Organization membership required")
    return await service.build_blocker_clusters(session, org_id)
