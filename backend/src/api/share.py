"""Share API — share/unshare endpoints + public share view.

Routes:
  POST   /analyses/{analysis_id}/share   — create share link (authenticated)
  DELETE /analyses/{analysis_id}/share   — revoke share link (authenticated)
  GET    /s/{short_id}                   — public share view (unauthenticated, IP rate limited)
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import share_service

logger = logging.getLogger("cadverify.share")

# Authenticated endpoints mounted under /api/v1/analyses
share_router = APIRouter(tags=["share"])

# Public endpoint mounted at root level /s
public_share_router = APIRouter(tags=["share"])


@share_router.post("/{analysis_id}/share")
@limiter.limit("60/hour;500/day")
async def create_share(
    analysis_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Share an analysis — generates a public short URL."""
    result = await share_service.create_share(analysis_id, user.user_id, session)
    return result


@share_router.delete("/{analysis_id}/share")
@limiter.limit("60/hour;500/day")
async def revoke_share(
    analysis_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Revoke sharing — the public link will 404 immediately."""
    await share_service.revoke_share(analysis_id, user.user_id, session)
    return {"message": "Share revoked"}


@public_share_router.get("/{short_id}")
@limiter.limit("120/hour")
async def get_shared_analysis(
    short_id: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
):
    """Public share view — returns sanitized analysis data (no auth required)."""
    data = await share_service.get_shared_analysis(short_id, session)
    if data is None:
        raise HTTPException(status_code=404, detail="Shared analysis not found")

    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Cache-Control"] = "private, no-store"
    return data
