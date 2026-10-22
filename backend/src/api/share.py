"""Share API — share/unshare endpoints + public share view.

Routes:
  POST   /analyses/{analysis_id}/share   — create a share link that ends (authenticated)
  DELETE /analyses/{analysis_id}/share   — switch the link off (its maker or an org admin)
  GET    /s/{short_id}                   — public share view (unauthenticated, IP rate limited);
                                           410 once the link ended or was switched off
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.rbac import require_org_writer
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import share_service
from src.services.share_links import ShareOptions

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
    body: Optional[ShareOptions] = None,
    user: AuthedUser = Depends(require_org_writer),
    session: AsyncSession = Depends(get_db_session),
):
    """Share an analysis — a public short URL that ends.

    Body (optional): ``{"expires_in_days": 1 | 7 | 30 | 90 | 365 | null}`` or
    ``{"expires_on": "YYYY-MM-DD"}``; omitted is 7 days, ``null`` is the
    explicit "no end date" choice kept for API callers.
    """
    opts = body or ShareOptions()
    # ``expires_on`` (validated by ShareOptions: today up to a year ahead) wins,
    # as on the record and package share routes.
    return await share_service.create_share(
        analysis_id, user.user_id, session, opts.expires_in_days, ends_at=opts.ends_at()
    )


@share_router.delete("/{analysis_id}/share")
@limiter.limit("60/hour;500/day")
async def revoke_share(
    analysis_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_org_writer),
    session: AsyncSession = Depends(get_db_session),
):
    """Switch the link off now (its maker or an org admin). It then says so (410)."""
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
