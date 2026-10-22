"""RFQ package API: what a buyer sends a supplier to quote.

Local package generation only: no supplier send, no marketplace, no live RFQ
network. A package is built from saved records; by default it carries what a
supplier quotes from (part, material, quantity, specs, note, CAD) and none of
our cost. ``include_cost_estimate`` adds the should-cost for that one package
(``src.services.rfq_package_service``).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_org_writer, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import rfq_package_service as svc

router = APIRouter(tags=["rfq-packages"])


class RequestedBy(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    company: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=200)


class CreateRfqPackageBody(BaseModel):
    decision_ids: list[str]
    title: str | None = None
    supplier_name: str | None = None
    note: str | None = None
    include_raw_cad: bool = False
    # Off unless the buyer deliberately sends our should-cost with this package.
    include_cost_estimate: bool = False
    reply_by: Optional[date] = None
    # Omitted: the requester's name and email and the organization's name.
    requested_by: Optional[RequestedBy] = None
    # decision id → quantity to ask for (the builder prefills it, the buyer edits it).
    quantities: dict[str, int] = Field(default_factory=dict)


class PreviewBody(BaseModel):
    decision_ids: list[str] = Field(default_factory=list, max_length=100)


def _safe_zip_name(title: str | None, package_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", (title or "rfq-package")).strip("._")
    if not stem:
        stem = "rfq-package"
    return f"{stem}-{package_id}.zip"


@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def create_rfq_package(
    request: Request,
    response: Response,
    body: CreateRfqPackageBody,
    user: AuthedUser = Depends(require_org_writer),
    session: AsyncSession = Depends(get_db_session),
):
    package = await svc.create_package(
        session,
        user,
        body.decision_ids,
        svc.RfqPackageOptions(
            title=body.title,
            supplier_name=body.supplier_name,
            note=body.note,
            include_raw_cad=body.include_raw_cad,
            include_cost_estimate=body.include_cost_estimate,
            reply_by=body.reply_by,
            requested_by=body.requested_by.model_dump() if body.requested_by else None,
            quantities=body.quantities,
        ),
    )
    await session.commit()
    response.status_code = 201
    return {"package": svc.serialize_package(package, include_items=True)}


@router.post("/preview")
@limiter.limit("600/hour;5000/day")
async def preview_rfq_package(
    request: Request,
    response: Response,
    body: PreviewBody,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Each picked record as the supplier would be asked to quote it, before the
    package is built: name, part number, material, the quantity (prefilled from
    the part, editable) and where it came from, yearly volume, specs, and
    whether ScaleCAD holds its CAD. Nothing is saved."""
    return {"items": await svc.preview_items(session, user, body.decision_ids)}


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_rfq_packages(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    rows = await svc.list_packages(session, user.user_id, limit=limit)
    return {"packages": [svc.serialize_package(row) for row in rows]}


@router.get("/{package_id}")
@limiter.limit("120/hour;1000/day")
async def get_rfq_package(
    package_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    package = await svc.get_package(session, package_id, user.user_id)
    return {"package": svc.serialize_package(package, include_items=True)}


@router.get("/{package_id}/download.zip")
@limiter.limit("60/hour;300/day")
async def download_rfq_package(
    package_id: str,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    package = await svc.get_package(session, package_id, user.user_id)
    zip_bytes = await svc.build_zip(session, package)
    filename = _safe_zip_name(package.title, package.ulid)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
