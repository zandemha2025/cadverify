"""Org-scoped direct-upload capability and multipart lifecycle API.

Two purposes (``src.services.direct_upload_service``):

* ``part``: one CAD file of up to 2 GiB, on every plan. Checked on the worker
  from the stored object (``POST /api/v1/checks``).
* ``batch_zip``: a batch's ZIP. Pilot, or a work-email account's free catalog
  run (``POST /api/v1/catalog-runs``); every other batch stays pilot-only.

Resumable: ``GET /{id}/parts`` lists the parts storage has, and re-initiating
with the same Idempotency-Key returns the same upload with fresh part URLs. On
the local backend each part is PUT to ``/{id}/parts/{n}`` here (``transport:
"relay"``); on S3 to its presigned URL (``transport: "s3"``).
"""
from __future__ import annotations

import asyncio
import tempfile
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.validation_caps import effective_plan, paid_access_required
from src.auth.rbac import Role, require_org_checker, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import direct_upload_service as service

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


async def require_upload_access(
    request: Request,
    user: AuthedUser = Depends(require_role(Role.analyst)),
) -> str | None:
    """Who may start an upload, by its purpose (read from the JSON body); returns the plan.

    A single part uploads on every plan. A batch ZIP needs pilot or the free
    catalog run of a work-email account. The plan sets the organization's
    upload admission limits (free accounts: fewer at once).
    """
    plan = await effective_plan(user.user_id)
    try:
        body = await request.json()
    except Exception:
        return plan  # the body model answers 422
    purpose = body.get("purpose") if isinstance(body, dict) else None
    if purpose != service.PURPOSE_BATCH_ZIP or plan == "pilot":
        return plan
    from src.auth.catalog_allowance import require_catalog_access

    try:
        await require_catalog_access(user)
    except HTTPException as exc:
        # A personal-email account (or any account without the free catalog
        # run) gets the same answer POST /batch gives.
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") == "phone_verification_required":
            raise
        raise paid_access_required() from exc
    return plan


class InitiateMultipartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: StrictStr
    filename: StrictStr
    content_type: StrictStr
    size_bytes: StrictInt
    checksum_sha256: StrictStr | None = None


class RefreshPartURLsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_numbers: list[StrictInt]


class CompletedPartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: StrictInt
    etag: StrictStr


class CompleteMultipartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[CompletedPartBody]


def _http_error(exc: service.DirectUploadError) -> HTTPException:
    headers = (
        {"Retry-After": str(exc.retry_after_seconds)}
        if exc.retry_after_seconds is not None
        else None
    )
    return HTTPException(
        status_code=exc.status_code,
        detail=exc.detail,
        headers=headers,
    )


@router.get("/capabilities")
async def get_upload_capabilities(
    purpose: Annotated[str, Query()] = service.PURPOSE_BATCH_ZIP,
    user: AuthedUser = Depends(require_role(Role.analyst)),
):
    """Describe the fixed direct-upload contract without exposing S3 coordinates."""
    try:
        plan = await effective_plan(user.user_id)
    except Exception:
        plan = None  # the limits shown are then the standard ones; initiation decides
    try:
        return service.capability(purpose, plan=plan)
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc


@router.post("/multipart", status_code=201)
@limiter.limit("120/hour;600/day")
async def initiate_multipart_upload(
    request: Request,
    response: Response,
    body: InitiateMultipartBody,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
    user: AuthedUser = Depends(require_org_checker),
    session: AsyncSession = Depends(get_db_session),
    plan: str | None = Depends(require_upload_access),
):
    try:
        upload, parts, urls_complete, replayed = await service.initiate(
            session,
            user_id=user.user_id,
            purpose=body.purpose,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
            checksum_sha256=body.checksum_sha256,
            idempotency_key=idempotency_key,
            plan=plan,
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    store_transport = None
    try:
        store_transport = getattr(service._require_s3_store(), "transport", "s3")
    except service.DirectUploadError:
        store_transport = None
    payload = service.serialize(upload)
    payload.update(
        {
            "upload_id": upload.ulid,
            "transport": store_transport,
            "parts": parts,
            "part_urls_complete": urls_complete,
            "idempotent_replay": replayed,
            "refresh_parts_url": f"/api/v1/uploads/{upload.ulid}/parts",
            "complete_url": f"/api/v1/uploads/{upload.ulid}/complete",
            "abort_url": f"/api/v1/uploads/{upload.ulid}/abort",
            "status_url": f"/api/v1/uploads/{upload.ulid}",
            "list_parts_url": f"/api/v1/uploads/{upload.ulid}/parts",
        }
    )
    return payload


@router.get("/{direct_upload_id}/parts")
async def list_received_parts(
    direct_upload_id: str,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """The parts storage already has, so an interrupted upload sends only the rest."""
    try:
        parts = await service.list_uploaded_parts(session, user_id=user.user_id, upload_ulid=direct_upload_id)
        upload = await service.get_status(session, user_id=user.user_id, upload_ulid=direct_upload_id)
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    return {
        "direct_upload_id": direct_upload_id,
        "status": upload.status,
        "part_count": upload.part_count,
        "part_size_bytes": upload.part_size_bytes,
        "parts": parts,
    }


# Bounded memory per relayed part: spill to disk past 1 MiB.
_RELAY_SPOOL_BYTES = 1024 * 1024


@router.put("/{direct_upload_id}/parts/{part_number}")
@limiter.limit("4000/hour")
async def put_relayed_part(
    request: Request,
    response: Response,
    direct_upload_id: str,
    part_number: int,
    user: AuthedUser = Depends(require_org_checker),
    session: AsyncSession = Depends(get_db_session),
):
    """One part of an upload, through the API (local backend only; S3 takes parts directly).

    The body must be exactly the part's size. Answers like S3: the part's
    ETag in the ``ETag`` header (and the JSON body).
    """
    try:
        upload, store, expected = await service.lock_part_for_relay(
            session, user_id=user.user_id, upload_ulid=direct_upload_id, part_number=part_number,
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    key, provider_id = upload.object_key, upload.multipart_upload_id
    await session.commit()  # release the row lock; parts upload in parallel
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) != expected:
        raise _http_error(service.DirectUploadError(
            422, "DIRECT_UPLOAD_PART_SIZE", f"Part {part_number} must be exactly {expected} bytes."))
    spool = tempfile.SpooledTemporaryFile(max_size=_RELAY_SPOOL_BYTES)
    try:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > expected:
                raise _http_error(service.DirectUploadError(
                    413, "DIRECT_UPLOAD_PART_SIZE", f"Part {part_number} must be exactly {expected} bytes."))
            spool.write(chunk)
        if size != expected:
            raise _http_error(service.DirectUploadError(
                422, "DIRECT_UPLOAD_PART_SIZE", f"Part {part_number} must be exactly {expected} bytes; {size} arrived."))
        spool.seek(0)
        try:
            etag, _ = await asyncio.to_thread(store.put_part, key, provider_id, part_number, spool, max_bytes=expected)
        except Exception as exc:
            raise _http_error(service._storage_error("store a part of")) from exc
    finally:
        spool.close()
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-store"
    return {"direct_upload_id": direct_upload_id, "part_number": part_number, "etag": etag, "size_bytes": expected}


@router.post("/{direct_upload_id}/parts")
async def refresh_multipart_part_urls(
    direct_upload_id: str,
    body: RefreshPartURLsBody,
    user: AuthedUser = Depends(require_org_checker),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        parts = await service.refresh_part_urls(
            session,
            user_id=user.user_id,
            upload_ulid=direct_upload_id,
            part_numbers=list(body.part_numbers),
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    return {"direct_upload_id": direct_upload_id, "parts": parts}


@router.post("/multipart/{direct_upload_id}/complete", include_in_schema=False)
@router.post("/{direct_upload_id}/complete")
async def complete_multipart_upload(
    direct_upload_id: str,
    body: CompleteMultipartBody,
    user: AuthedUser = Depends(require_org_checker),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        upload = await service.complete(
            session,
            user_id=user.user_id,
            upload_ulid=direct_upload_id,
            parts=[part.model_dump() for part in body.parts],
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    return service.serialize(upload)


@router.delete("/multipart/{direct_upload_id}", include_in_schema=False)
@router.post("/{direct_upload_id}/abort")
async def abort_multipart_upload(
    direct_upload_id: str,
    user: AuthedUser = Depends(require_org_checker),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        upload = await service.abort(
            session,
            user_id=user.user_id,
            upload_ulid=direct_upload_id,
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    return service.serialize(upload)


@router.get("/{direct_upload_id}")
async def get_direct_upload_status(
    direct_upload_id: str,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        upload = await service.get_status(
            session,
            user_id=user.user_id,
            upload_ulid=direct_upload_id,
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    batch_ulid = await service.attached_batch_ulid(session, upload)
    return service.serialize(upload, attached_batch_ulid=batch_ulid)
