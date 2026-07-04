"""Governed shop-library API (W4 libraries, slice 2).

The management + read surface for the versioned, effective-dated, PER-SLUG
shop-profile asset that replaces the read-only ``data/shop_profiles/*.json`` flat
files. Org admins draft → edit → PUBLISH a shop profile with an effective date;
the costing engine then binds the version in effect at estimate time for the
requested slug as that shop's SHOP-provenance overrides (gated by
``SHOP_LIBRARY_ENABLED`` + a published profile for the caller's org + slug).

Tenancy: ORG-SCOPED. Reads resolve the caller's org (``resolve_org``); every row
is filtered by ``org_id`` so a caller never sees or mutates another org's profile.
Mutations require ORG admin (``require_org_role(OrgRole.admin)``) — governance is
an org-admin authority, distinct from the platform product-tier role.

Honesty: a governed shop profile is the org's DECLARED shop calibration, bound as
SHOP provenance — never measured/validated. The UI must not badge it as certified.
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
from src.services import shop_library_service as svc

logger = logging.getLogger("cadverify.shop_library")

router = APIRouter(tags=["shop-library"])


class CreateDraftBody(BaseModel):
    slug: str = ""
    name: str = ""
    change_note: str = ""
    payload: Optional[dict] = None
    from_version_id: Optional[int] = None


class UpdateDraftBody(BaseModel):
    name: Optional[str] = None
    change_note: Optional[str] = None
    payload: Optional[dict] = None
    slug: Optional[str] = None


class PublishBody(BaseModel):
    effective_from: Optional[datetime] = None


async def _write_org(ctx: OrgAuthContext, session: AsyncSession) -> str:
    """The org a mutation writes to: the membership org (or, for a superadmin
    with no membership, their resolved org). 400 if none — a governed shop
    profile must belong to a concrete org."""
    org_id = ctx.org_id or await resolve_org(session, ctx.user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")
    return org_id


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_shop_profiles(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """All shop-profile versions for the caller's org, newest first."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        return {"versions": [], "flag_enabled": svc.shop_library_enabled()}
    rows = await svc.list_versions(session, org_id)
    return {
        "versions": [svc.serialize_version(r) for r in rows],
        "flag_enabled": svc.shop_library_enabled(),
    }


@router.get("/{version_id}")
@limiter.limit("120/hour;1000/day")
async def get_shop_profile(
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
async def create_shop_profile_draft(
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
            slug=body.slug,
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
async def update_shop_profile_draft(
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
            slug=body.slug,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    return svc.serialize_version(row, include_payload=True)


@router.delete("/{version_id}")
@limiter.limit("60/hour;300/day")
async def discard_shop_profile_draft(
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
async def archive_shop_profile(
    request: Request,
    response: Response,
    version_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Archive a PUBLISHED version. Guarded: the version currently in effect for
    its slug cannot be archived (409) — that would strand the cost path."""
    org_id = await _write_org(ctx, session)
    row = await svc.archive_version(session, org_id, version_id)
    await session.commit()
    return svc.serialize_version(row, include_payload=True)


@router.post("/{version_id}/publish")
@limiter.limit("60/hour;300/day")
async def publish_shop_profile(
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
