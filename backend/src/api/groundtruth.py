"""Ground-truth ingest API (W5) — the durable, org-scoped home for real quotes.

Retires the Python-REPL requirement: real cost/quote data lands via
``POST /api/v1/ground-truth`` (org-stamped), lists/reads back, and a
``POST /api/v1/ground-truth/recalibrate`` trigger re-runs the tested ground-truth
loop over THIS org's records — refreshing the served Calibration / ResidualModel
so ``/validate/cost`` returns MEASURED confidence intervals.

Tenancy: ORG-SCOPED via the ``resolve_org`` boundary. Every read/write is scoped
to the caller's org; one org's ground truth never enters another's calibration
(cross-tenant test asserts this by name). Ingest requires ``analyst``; reads
require ``viewer``; recalibration requires ``analyst``.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import groundtruth_service as svc

logger = logging.getLogger("cadverify.groundtruth")

router = APIRouter(tags=["ground-truth"])


class GroundTruthIn(BaseModel):
    """One real cost/quote datum to persist as org-scoped ground truth."""

    part_id: str = Field(
        ..., min_length=1,
        description="Stable part identity = the STL filename (the split key).",
    )
    process: str = Field(
        ..., min_length=1,
        description="Engine ProcessType id, e.g. cnc_3axis, sls, injection_molding.",
    )
    quantity: int = Field(..., ge=1, description="Order quantity for this quote.")
    actual_unit_cost_usd: float = Field(
        ..., gt=0, description="The KNOWN real per-unit cost / quote."
    )
    material_class: str = Field(
        "polymer", description="polymer|aluminum|steel|stainless|titanium"
    )
    shop: Optional[str] = Field(
        None, description="Shop-profile id this quote is bound to (None = DEFAULT card)."
    )
    region: Optional[str] = Field(None, description="Explicit region override.")
    currency: str = "USD"
    source: str = Field(
        "", description="Provenance of the number (quote #, PO, vendor) — audit trail."
    )
    stand_in: bool = Field(
        False,
        description=(
            "False (default) = REAL ground truth. True = synthetic stand-in — it "
            "can shape a band's spread but can NEVER flip validated=True."
        ),
    )
    part_path: Optional[str] = Field(
        None, description="Explicit STL path; else resolved from part_id under parts_dir."
    )
    notes: str = ""


async def _require_org(session: AsyncSession, user: AuthedUser) -> str:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;1000/day")
async def create_ground_truth(
    request: Request,
    response: Response,
    payload: GroundTruthIn,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Persist one real ground-truth record for the caller's organization.

    Org-stamped and validated through the costing ``GroundTruthRecord`` (a
    non-positive cost / empty part_id is a clean 400). Dedup: last write wins on
    ``(part_id, process, quantity, shop)`` within the org.
    """
    org_id = await _require_org(session, user)
    try:
        row = await svc.ingest_record(
            session, org_id, user.user_id, payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    return svc.row_to_public(row)


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_ground_truth(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller org's ground-truth records (newest first)."""
    org_id = await _require_org(session, user)
    rows = await svc.list_records(session, org_id)
    return {"records": [svc.row_to_public(r) for r in rows], "total": len(rows)}


@router.get("/{record_id}")
@limiter.limit("120/hour;1000/day")
async def get_ground_truth(
    request: Request,
    response: Response,
    record_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Fetch one record by its public id — 404 if it is not in the caller's org."""
    org_id = await _require_org(session, user)
    row = await svc.get_record(session, org_id, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ground-truth record not found.")
    return svc.row_to_public(row)


@router.post("/recalibrate", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("10/hour;50/day")
async def recalibrate_ground_truth(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Re-run the ground-truth loop over THIS org's records and refresh the
    served Calibration / ResidualModel. The manual recalibration trigger; the
    returned summary carries the measured claim and whether the band is now
    ``validated`` (True only from REAL held-out residuals).

    HONESTLY GATED: with fewer than ``MIN_REAL_RECORDS`` real (non-stand-in)
    records the request is REFUSED with a 422 that names the shortfall, rather
    than emitting a calibration from insufficient / synthetic data.
    """
    org_id = await _require_org(session, user)
    try:
        return await svc.recalibrate_org(session, org_id)
    except svc.InsufficientGroundTruth as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": str(exc),
                "n_real": exc.n_real,
                "n_records": exc.n_records,
                "min_real": exc.min_real,
            },
        )
