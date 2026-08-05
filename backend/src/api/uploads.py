"""Org-scoped direct-upload capability and multipart lifecycle API."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import direct_upload_service as service

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])


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
    _user: AuthedUser = Depends(require_role(Role.analyst)),
):
    """Describe the fixed direct-upload contract without exposing S3 coordinates."""
    try:
        return service.capability(purpose)
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc


@router.post("/multipart", status_code=201)
async def initiate_multipart_upload(
    body: InitiateMultipartBody,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
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
        )
    except service.DirectUploadError as exc:
        raise _http_error(exc) from exc
    response = service.serialize(upload)
    response.update(
        {
            "upload_id": upload.ulid,
            "parts": parts,
            "part_urls_complete": urls_complete,
            "idempotent_replay": replayed,
            "refresh_parts_url": f"/api/v1/uploads/{upload.ulid}/parts",
            "complete_url": f"/api/v1/uploads/{upload.ulid}/complete",
            "abort_url": f"/api/v1/uploads/{upload.ulid}/abort",
            "status_url": f"/api/v1/uploads/{upload.ulid}",
        }
    )
    return response


@router.post("/{direct_upload_id}/parts")
async def refresh_multipart_part_urls(
    direct_upload_id: str,
    body: RefreshPartURLsBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
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
    user: AuthedUser = Depends(require_role(Role.analyst)),
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
    user: AuthedUser = Depends(require_role(Role.analyst)),
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
