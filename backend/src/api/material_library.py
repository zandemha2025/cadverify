"""Governed materials-library API (W4 libraries, slice 3).

The management + read surface for the versioned, effective-dated materials
catalog that overrides the base rate card's ``material_prices`` for an org. Org
admins draft → edit → PUBLISH a catalog with an effective date; the costing
engine then overlays the version in effect at estimate time onto the base
table's material prices (gated by ``MATERIAL_LIBRARY_ENABLED`` + a published
catalog for the caller's org).

Tenancy: ORG-SCOPED. Reads resolve the caller's org (``resolve_org``); every row
is filtered by ``org_id`` so a caller never sees or mutates another org's
catalog. Mutations require ORG admin (``require_org_role(OrgRole.admin)``).

Honesty: a governed catalog is DECLARED default prices, never validated. ``GET
/effective`` states plainly whether the engine is actually overlaying a governed
catalog (flag + published-in-effect) vs. still using the base table's own prices.
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
from src.services import cost_decision_service
from src.services import material_library_service as svc

logger = logging.getLogger("cadverify.material_library")

router = APIRouter(tags=["material-library"])


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
    with no membership, their resolved org). 400 if none — a governed catalog
    must belong to a concrete org."""
    org_id = ctx.org_id or await resolve_org(session, ctx.user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")
    return org_id


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_material_catalogs(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """All materials-catalog versions for the caller's org, newest first."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        return {"versions": [], "flag_enabled": svc.material_library_enabled()}
    rows = await svc.list_versions(session, org_id)
    return {
        "versions": [svc.serialize_version(r) for r in rows],
        "flag_enabled": svc.material_library_enabled(),
    }


@router.get("/effective")
@limiter.limit("120/hour;1000/day")
async def effective_material_catalog(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """What the engine actually overlays right now for this org.

    ``using_governed`` is true ONLY when the flag is on AND a published catalog
    is in effect — otherwise the engine uses the base rate table's own
    ``material_prices`` and we say so, so nobody mistakes an authored-but-unused
    catalog for a live one.
    """
    org_id = await resolve_org(session, user.user_id)
    flag = svc.material_library_enabled()
    payload = None
    if org_id and flag:
        payload = await svc.resolve_material_overrides_for(session, org_id)
    return {
        "flag_enabled": flag,
        "using_governed": payload is not None,
        "source": "governed_material_catalog"
        if payload is not None
        else "base_rate_table_material_prices",
        "provenance": "default",
        "validated": False,
        "payload": payload,
    }


@router.get("/{version_id}")
@limiter.limit("120/hour;1000/day")
async def get_material_catalog(
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
async def create_material_catalog_draft(
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
async def update_material_catalog_draft(
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
async def discard_material_catalog_draft(
    request: Request,
    response: Response,
    version_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Discard a DRAFT version. Published/archived versions are the audit trail
    and can never be deleted (409)."""
    org_id = await _write_org(ctx, session)
    row = await svc.discard_draft(session, org_id, version_id)
    await session.commit()
    return svc.serialize_version(row)


@router.post("/{version_id}/archive")
@limiter.limit("60/hour;300/day")
async def archive_material_catalog(
    request: Request,
    response: Response,
    version_id: int,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.admin)),
    session: AsyncSession = Depends(get_db_session),
):
    """Archive a PUBLISHED version. Guarded: the version currently in effect
    cannot be archived (409) — that would strand the overlay."""
    org_id = await _write_org(ctx, session)
    row = await svc.archive_version(session, org_id, version_id)
    await session.commit()
    return svc.serialize_version(row, include_payload=True)


@router.post("/{version_id}/publish")
@limiter.limit("60/hour;300/day")
async def publish_material_catalog(
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
    await cost_decision_service.mark_org_decisions_stale(
        session,
        org_id,
        reason=f"material_library_published:v{row.version}",
        stale_at=row.effective_from,
    )
    from src.services.audit_service import emit_event

    await emit_event(
        session, ctx.user_id, "library.version_published", "material_catalog",
        str(row.id),
        {"org_id": org_id, "library": "material", "version": row.version},
        org_id=org_id,
    )
    await session.commit()
    return svc.serialize_version(row, include_payload=True)
