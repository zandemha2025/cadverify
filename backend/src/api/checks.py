"""Checks of stored uploads (big files): start one, follow it, list your recent ones.

    POST /api/v1/checks            {direct_upload_id, material_class?, qty?, units?, orientation?} -> 202
    GET  /api/v1/checks/{id}       stage, progress, and the part's page once done
                                   (a big kept part's re-price or repair: its response, ``result``)
    GET  /api/v1/checks            the caller's checks of the last day (the work bar)

The file was uploaded with ``POST /api/v1/uploads/multipart`` (purpose ``part``,
up to 2 GiB, every plan). The check itself runs on the worker
(``src.jobs.stored_check_tasks``); the web request never reads the file. It
uses a check from the account's allowance as an upload of the same file
would, taken on the worker once the bytes are known (``error.code`` says when
the allowance or the phone gate stopped it). Org-scoped like every part route;
the kill switch, the analyst role and a per-user rate limit apply.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, Role, require_org_role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import stored_check_service as svc

router = APIRouter(prefix="/api/v1/checks", tags=["checks"])


class StartCheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direct_upload_id: StrictStr
    material_class: Optional[StrictStr] = None
    qty: Optional[StrictStr] = None
    units: Optional[StrictStr] = None
    orientation: Optional[StrictStr] = None


def _http(exc: svc.StoredCheckError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("", status_code=202, dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;300/day")
async def start_stored_check(
    request: Request,
    response: Response,
    body: StartCheckBody,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    if not ctx.org_id:
        raise HTTPException(status_code=403, detail={"code": "ORG_REQUIRED", "message": "An active organization is required."})
    try:
        job, created = await svc.start_check(
            session, user_id=user.user_id, org_id=ctx.org_id, upload_ulid=body.direct_upload_id,
            options=body.model_dump(exclude={"direct_upload_id"}),
        )
    except svc.StoredCheckError as exc:
        raise _http(exc) from exc
    if job.status == "queued":
        try:
            await svc.enqueue(job)
        except Exception:
            # The committed row is the durable intent; the worker's reconcile
            # cron offers it again (src.jobs.arq_backend.reconcile_queued_jobs).
            pass
    if not created:
        response.status_code = 200
    response.headers["Cache-Control"] = "no-store"
    return svc.public_status(job)


@router.get("/{check_id}")
async def get_stored_check(
    check_id: str,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        job = await svc.get_check(session, user_id=user.user_id, check_ulid=check_id)
    except svc.StoredCheckError as exc:
        raise _http(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    # A big kept part's re-price or repair, once done, carries its route's response.
    return svc.public_status(job, with_result=True)


@router.get("")
async def list_stored_checks(
    response: Response,
    limit: int = 10,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    jobs = await svc.recent_checks(session, user_id=user.user_id, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return {"checks": [svc.public_status(j) for j in jobs]}
