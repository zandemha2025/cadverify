"""Declared part-context API (W3.5 rung-1).

The read + declare surface for a part's optional, USER-DECLARED business context
(program / parent assembly / units-per-parent / annual volume). One row per
``(org_id, mesh_hash)``; it is what lets the portfolio roll-up state an honest
``$/year`` instead of only a per-unit price.

Tenancy: ORG-SCOPED. Both routes resolve the caller's org (``resolve_org``) and
filter by ``org_id`` so a caller never reads or writes another org's context
(cross-tenant test asserts a 404). Reads require the platform ``viewer`` role;
declaring a context requires ``analyst`` (the same role that authors decisions).

Honesty: a declared context is a USER assertion (``provenance: "user"``), never
inferred from the mesh. Nothing here fabricates a demand quantity or flips a cost
band to validated.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import part_context_service as svc

logger = logging.getLogger("cadverify.part_context")

router = APIRouter(tags=["part-context"])


class DeclareContextBody(BaseModel):
    program: Optional[str] = None
    parent_assembly: Optional[str] = None
    units_per_parent: Optional[int] = None
    annual_volume: Optional[int] = None
    # The declared service environment (machine-inventory §6) rides this existing
    # PUT: {max_temp_c, min_temp_c, pressure_bar, corrosive, sour_service, medium,
    # standard}. USER-declared, never inferred; validated in the service.
    service_environment: Optional[dict] = None
    # BOM-rollup linkage (Slice 3): name a persisted bom_edges tree + this part's
    # child_ref + vehicles/year, so the annual volume rolls up from the real
    # hierarchy. All optional — unset → the flat declared annual_volume, unchanged.
    bom_assembly_key: Optional[str] = None
    bom_child_ref: Optional[str] = None
    bom_roots_per_year: Optional[int] = None


async def _require_org(session: AsyncSession, user_id: int) -> str:
    """The caller's org, or 400 — a declared context must belong to a concrete
    org (matches ``rate_library``'s ``_write_org`` boundary)."""
    org_id = await resolve_org(session, user_id)
    if not org_id:
        raise HTTPException(status_code=400, detail="no organization for caller")
    return org_id


@router.get("/{mesh_hash}")
@limiter.limit("120/hour;1000/day")
async def get_part_context(
    request: Request,
    response: Response,
    mesh_hash: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The declared context for a part in the caller's org, or 404 when none."""
    org_id = await resolve_org(session, user.user_id)
    row = await svc.get_context(session, org_id, mesh_hash) if org_id else None
    if row is None:
        raise HTTPException(status_code=404, detail="no declared context for part")
    return svc.serialize_context(row)


@router.put("/{mesh_hash}")
@limiter.limit("120/hour;600/day")
async def declare_part_context(
    request: Request,
    response: Response,
    mesh_hash: str,
    body: DeclareContextBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Declare (upsert) a part's context. Idempotent on ``(org, mesh_hash)``.

    A non-positive ``units_per_parent`` / ``annual_volume`` is a 400 — those are
    physical counts and a value ``<= 0`` is nonsense. The response is always
    ``provenance: "user"`` (a declared assertion, never inferred).
    """
    org_id = await _require_org(session, user.user_id)
    try:
        row = await svc.upsert_context(
            session,
            org_id,
            mesh_hash,
            body.model_dump(exclude_unset=True),
            created_by=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    return svc.serialize_context(row)
