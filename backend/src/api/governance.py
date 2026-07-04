"""Governance change-request API (W4 governance zone, MVP).

The management + review surface for the "change request -> review -> publish"
flow over the governed rate-card and shop-profile libraries. A member PROPOSES a
DRAFT version for review; an org admin APPROVES it (which publishes the draft via
the library's existing publish path) or REJECTS it (the draft stays a draft).

Tenancy: ORG-SCOPED. Reads resolve the caller's org (``resolve_org``); every row
is filtered by ``org_id`` so a caller never sees or decides another org's change
request. Proposing requires ORG member+ (``require_org_role(OrgRole.member)``);
approving/rejecting requires ORG admin (``require_org_role(OrgRole.admin)``) —
review is an org-admin authority, distinct from the platform product-tier role.

Honesty: approval only triggers the existing, tested publish path; it never
flips a decision to ``validated``. Mirrors ``rate_library.py``'s auth + limiter
decorators exactly.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import (
    OrgAuthContext,
    OrgRole,
    Role,
    require_org_role,
    require_role,
)
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import governance_service as svc

logger = logging.getLogger("cadverify.governance")

router = APIRouter(tags=["governance"])


class ProposeBody(BaseModel):
    asset_type: str
    target_version_id: int
    title: str = ""
    note: str = ""


class RejectBody(BaseModel):
    note: str = ""


async def _write_org(ctx: OrgAuthContext, session: AsyncSession) -> str:
    """The org a governance action writes to: the membership org (or, for a
    superadmin with no membership, their resolved org). 400 if none."""
    org_id = ctx.org_id or await resolve_org(session, ctx.user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")
    return org_id


@router.post("/change-requests")
@limiter.limit("60/hour;300/day")
async def propose_change_request(
    request: Request,
    response: Response,
    body: ProposeBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    session: AsyncSession = Depends(get_db_session),
):
    """Propose a DRAFT version for review (member+)."""
    org_id = await _write_org(ctx, session)
    row = await svc.propose(
        session,
        org_id,
        body.asset_type,
        body.target_version_id,
        title=body.title,
        note=body.note,
        proposed_by=ctx.user_id,
    )
    await session.commit()
    return svc.serialize_request(row)


@router.get("/change-requests")
@limiter.limit("120/hour;1000/day")
async def list_change_requests(
    request: Request,
    response: Response,
    status: Optional[str] = None,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """All change requests for the caller's org, newest first; optional ?status."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        return {"change_requests": []}
    rows = await svc.list_requests(session, org_id, status=status)
    return {"change_requests": [svc.serialize_request(r) for r in rows]}


@router.get("/change-requests/{request_id}")
@limiter.limit("120/hour;1000/day")
async def get_change_request(
    request: Request,
    response: Response,
    request_id: int,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await resolve_org(session, user.user_id)
    row = await svc.get_request(session, org_id, request_id) if org_id else None
    if row is None:
        raise HTTPException(status_code=404, detail="change request not found")
    return svc.serialize_request(row)


@router.post("/change-requests/{request_id}/approve")
@limiter.limit("60/hour;300/day")
async def approve_change_request(
    request: Request,
    response: Response,
    request_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Approve a PROPOSED request — PUBLISHES the target draft (admin)."""
    org_id = await _write_org(ctx, session)
    row, published = await svc.approve(session, org_id, request_id, ctx.user_id)
    lib = svc._library_for(row.asset_type)
    await session.commit()
    return {
        "change_request": svc.serialize_request(row),
        "published_version": lib.serialize_version(published, include_payload=True),
    }


@router.post("/change-requests/{request_id}/reject")
@limiter.limit("60/hour;300/day")
async def reject_change_request(
    request: Request,
    response: Response,
    request_id: int,
    body: RejectBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Reject a PROPOSED request — the draft stays a draft (admin)."""
    org_id = await _write_org(ctx, session)
    row = await svc.reject(session, org_id, request_id, ctx.user_id, note=body.note)
    await session.commit()
    return svc.serialize_request(row)
