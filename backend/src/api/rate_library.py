"""Governed rate-library API (W4 libraries, slice 1).

The management + read surface for the versioned, effective-dated rate-card asset
that replaces the hardcoded ``RATE_CARD_V0`` dict. Org admins draft → edit →
PUBLISH a card with an effective date; the costing engine then reads the version
in effect at estimate time as its base DEFAULT table (gated by
``RATE_LIBRARY_ENABLED`` + a published card for the caller's org).

Tenancy: ORG-SCOPED. Reads resolve the caller's org (``resolve_org``); every row
is filtered by ``org_id`` so a caller never sees or mutates another org's card.
Mutations require ORG admin (``require_org_role(OrgRole.admin)``) — governance is
an org-admin authority, distinct from the platform product-tier role.

Honesty: a governed card is DEFAULT assumptions, never validated. ``GET
/effective`` states plainly whether the engine is actually consuming a governed
card (flag + published-in-effect) vs. still using the hardcoded default.
"""
from __future__ import annotations

import logging
from datetime import datetime
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
from src.services import rate_library_service as svc

logger = logging.getLogger("cadverify.rate_library")

router = APIRouter(tags=["rate-library"])


class CreateDraftBody(BaseModel):
    name: str = ""
    change_note: str = ""
    payload: Optional[dict] = None
    from_version_id: Optional[int] = None


class UpdateDraftBody(BaseModel):
    name: Optional[str] = None
    change_note: Optional[str] = None
    payload: Optional[dict] = None


class PublishBody(BaseModel):
    effective_from: Optional[datetime] = None


async def _write_org(ctx: OrgAuthContext, session: AsyncSession) -> str:
    """The org a mutation writes to: the membership org (or, for a superadmin
    with no membership, their resolved org). 400 if none — a governed card must
    belong to a concrete org."""
    org_id = ctx.org_id or await resolve_org(session, ctx.user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")
    return org_id


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_rate_cards(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """All rate-card versions for the caller's org, newest first."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        return {"versions": [], "flag_enabled": svc.rate_library_enabled()}
    rows = await svc.list_versions(session, org_id)
    return {
        "versions": [svc.serialize_version(r) for r in rows],
        "flag_enabled": svc.rate_library_enabled(),
    }


@router.get("/effective")
@limiter.limit("120/hour;1000/day")
async def effective_rate_card(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """What the engine actually uses right now for this org.

    ``using_governed`` is true ONLY when the flag is on AND a published card is
    in effect — otherwise the engine uses the hardcoded ``RATE_CARD_V0`` and we
    say so, so nobody mistakes an authored-but-unused card for a live one.
    """
    org_id = await resolve_org(session, user.user_id)
    flag = svc.rate_library_enabled()
    payload = None
    if org_id and flag:
        payload = await svc.resolve_rate_table_for_org(session, org_id)
    return {
        "flag_enabled": flag,
        "using_governed": payload is not None,
        "source": "governed_rate_card" if payload is not None else "default_rate_card_v0",
        "provenance": "default",
        "validated": False,
        "payload": payload,
    }


@router.get("/{version_id}")
@limiter.limit("120/hour;1000/day")
async def get_rate_card(
    request: Request,
    response: Response,
    version_id: int,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await resolve_org(session, user.user_id)
    row = await svc.get_version(session, org_id, version_id) if org_id else None
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")
    return svc.serialize_version(row, include_payload=True)


@router.post("")
@limiter.limit("60/hour;300/day")
async def create_rate_card_draft(
    request: Request,
    response: Response,
    body: CreateDraftBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _write_org(ctx, session)
    try:
        row = await svc.create_draft(
            session,
            org_id,
            name=body.name,
            change_note=body.change_note,
            payload=body.payload,
            from_version_id=body.from_version_id,
            created_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    return svc.serialize_version(row, include_payload=True)


@router.patch("/{version_id}")
@limiter.limit("120/hour;600/day")
async def update_rate_card_draft(
    request: Request,
    response: Response,
    version_id: int,
    body: UpdateDraftBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _write_org(ctx, session)
    try:
        row = await svc.update_draft(
            session,
            org_id,
            version_id,
            name=body.name,
            change_note=body.change_note,
            payload=body.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    return svc.serialize_version(row, include_payload=True)


@router.delete("/{version_id}")
@limiter.limit("60/hour;300/day")
async def discard_rate_card_draft(
    request: Request,
    response: Response,
    version_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Discard a DRAFT version. Published/archived versions are the audit
    trail and can never be deleted (409)."""
    org_id = await _write_org(ctx, session)
    row = await svc.discard_draft(session, org_id, version_id)
    await session.commit()
    return svc.serialize_version(row)


@router.post("/{version_id}/archive")
@limiter.limit("60/hour;300/day")
async def archive_rate_card(
    request: Request,
    response: Response,
    version_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Archive a PUBLISHED version. Guarded: the version currently in effect
    cannot be archived (409) — that would strand the costing engine."""
    org_id = await _write_org(ctx, session)
    row = await svc.archive_version(session, org_id, version_id)
    await session.commit()
    return svc.serialize_version(row, include_payload=True)


@router.get("/{version_id}/diff/{other_id}")
@limiter.limit("120/hour;600/day")
async def diff_rate_cards(
    request: Request,
    response: Response,
    version_id: int,
    other_id: int,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Structural diff between two of the caller's org's rate-card versions.

    404 if either version does not exist in the caller's org (never a
    cross-tenant read). Only real changed leaf keys are reported (path,
    from, to); an unchanged key is never listed.
    """
    org_id = await resolve_org(session, user.user_id)
    row_a = await svc.get_version(session, org_id, version_id) if org_id else None
    row_b = await svc.get_version(session, org_id, other_id) if org_id else None
    if row_a is None or row_b is None:
        raise HTTPException(status_code=404, detail="version not found")
    diff = svc.diff_payloads(row_a.payload, row_b.payload)
    return {
        "from": svc.serialize_version(row_a),
        "to": svc.serialize_version(row_b),
        "diff": diff,
    }


@router.post("/{version_id}/publish")
@limiter.limit("60/hour;300/day")
async def publish_rate_card(
    request: Request,
    response: Response,
    version_id: int,
    body: PublishBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _write_org(ctx, session)
    row = await svc.publish_version(
        session, org_id, version_id, effective_from=body.effective_from
    )
    await session.commit()
    return svc.serialize_version(row, include_payload=True)
