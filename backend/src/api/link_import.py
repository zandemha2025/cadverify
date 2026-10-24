"""Import a part from a share link: the worker fetches the file and checks it.

    GET  /api/v1/uploads/from-link   whether it's on here, and the providers taken
    POST /api/v1/uploads/from-link   {url, filename?, material_class?, qty?, units?, orientation?}
                                     -> 202, the check's status (``GET /api/v1/checks/{id}``)

The request reads only the link (``src.services.link_import``: the URL rules,
the provider's download address); the worker fetches the bytes under the
outbound rules and the check runs as a big file's does. Admitted like a
direct upload (the organization's uploads at once and their bytes), with a
per-user rate limit, the kill switch and the same role gates as the other
routes that check a new part. Off when ``LINK_IMPORT_ENABLED`` is off and on
the regulated plane.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, Role, require_org_checker, require_org_role, require_role
from src.auth.require_api_key import AuthedUser
from src.auth.validation_caps import effective_plan
from src.config.public_urls import error_doc_url
from src.db.engine import get_db_session
from src.services import direct_upload_service as uploads
from src.services import link_import
from src.services import stored_check_service as checks

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


class FromLinkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: StrictStr = Field(max_length=link_import.MAX_URL_LENGTH)
    filename: Optional[StrictStr] = Field(default=None, max_length=255)
    material_class: Optional[StrictStr] = None
    qty: Optional[StrictStr] = None
    units: Optional[StrictStr] = None
    orientation: Optional[StrictStr] = None


def _refused(code: str, message: str, status_code: int = 422, headers: Optional[dict] = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "doc_url": error_doc_url(code)},
        headers=headers,
    )


@router.get("/from-link")
async def link_import_capability(user: AuthedUser = Depends(require_role(Role.viewer))):
    """Whether link import is on here, the providers it takes, and the size cap."""
    return {
        "enabled": link_import.link_import_enabled(),
        "providers": list(link_import.PROVIDER_LABELS.values()),
        "max_size_bytes": uploads.part_max_size_bytes(),
    }


@router.post("/from-link", status_code=202, dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("20/hour;100/day")
async def start_link_import(
    request: Request,
    response: Response,
    body: FromLinkBody,
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    # Analyst and org member, as the other routes that check a new part.
    user: AuthedUser = Depends(require_org_checker),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    session: AsyncSession = Depends(get_db_session),
):
    if not link_import.link_import_enabled():
        raise _refused("LINK_IMPORT_OFF", "Import from a link is off on this server. Download the file and upload it.", 403)
    if not ctx.org_id:
        raise _refused("ORG_REQUIRED", "An active organization is required.", 403)
    try:
        plan = link_import.plan_link(body.url)
    except link_import.LinkRefused as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from None
    filename = None
    if body.filename is not None and body.filename.strip():
        filename = link_import.safe_filename(body.filename)
        if not filename or not uploads.part_suffix(filename):
            raise _refused(
                "LINK_FILENAME",
                "Name the file as a STEP, IGES or STL file (or a .zip or .gz of one), for example bracket.step.",
            )
    try:
        sealed = link_import.seal_url(body.url.strip())
    except RuntimeError:
        raise _refused("LINK_IMPORT_UNAVAILABLE", "Import from a link isn't set up on this server yet.", 503) from None
    plan_name = await effective_plan(user.user_id)
    try:
        job, upload, created = await checks.start_link_check(
            session,
            user_id=user.user_id,
            org_id=ctx.org_id,
            link=plan,
            sealed_url=sealed,
            filename=filename,
            options=body.model_dump(exclude={"url", "filename"}),
            idempotency_key=idempotency_key,
            plan=plan_name,
        )
    except uploads.DirectUploadError as exc:
        headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds is not None else None
        raise _refused(exc.code, exc.message, exc.status_code, headers) from None
    except checks.StoredCheckError as exc:
        raise _refused(exc.code, exc.message, exc.status_code) from None
    if job.status == "queued":
        try:
            await checks.enqueue(job)
        except Exception:
            # The committed row is the durable intent; the worker's reconcile
            # cron offers it again (src.jobs.arq_backend.reconcile_queued_jobs).
            pass
    if not created:
        response.status_code = 200
    response.headers["Cache-Control"] = "no-store"
    return {**checks.public_status(job), "direct_upload_id": upload.ulid}
