"""RFQ / supplier evidence package API.

Local package generation only: no supplier send, no marketplace, no live RFQ
network. The package is an exportable evidence bundle built from saved
cost-decision artifacts plus declared manifest/context data where available.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import rfq_package_service as svc

router = APIRouter(tags=["rfq-packages"])


class CreateRfqPackageBody(BaseModel):
    decision_ids: list[str]
    title: str | None = None
    supplier_name: str | None = None
    note: str | None = None
    include_raw_cad: bool = False


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
    user: AuthedUser = Depends(require_role(Role.analyst)),
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
        ),
    )
    await session.commit()
    response.status_code = 201
    return {"package": svc.serialize_package(package, include_items=True)}


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
