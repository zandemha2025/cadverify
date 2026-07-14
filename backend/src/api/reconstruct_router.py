"""Reconstruct API endpoints -- image upload and mesh download.

POST /api/v1/reconstruct              -- upload 1-4 images, returns 202
GET  /api/v1/reconstructions/{id}/mesh.stl -- download reconstructed mesh
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.public_urls import error_doc_url
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import reconstruction_service

logger = logging.getLogger("cadverify.reconstruct_router")

router = APIRouter(prefix="/api/v1", tags=["reconstruct"])


@router.get("/reconstruct/capability")
async def reconstruction_capability(
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """Return the real deployment capability before a browser accepts images."""
    availability = reconstruction_service.check_reconstruction_availability()
    available = bool(availability["available"])
    try:
        can_submit = Role(user.role).rank >= Role.analyst.rank
    except ValueError:
        can_submit = False
    egress = bool(availability.get("egress")) if available else False
    if not available:
        message = (
            "Image-to-3D is not enabled for this workspace. Upload STEP/STP, "
            "IGES/IGS, or STL in Verify, or ask an administrator to approve and "
            "configure a reconstruction backend."
        )
    elif egress:
        message = (
            "Image-to-3D uses an approved third-party provider. Uploaded and "
            "derived imagery leaves this ProofShape deployment."
        )
    else:
        message = (
            "Image-to-3D runs inside this deployment; uploaded imagery does not "
            "leave the workspace boundary."
        )
    return {
        "available": available,
        "can_submit": can_submit,
        "effective_backend": availability.get("effective_backend", "none"),
        "customer_data_egress": egress,
        "requires_egress_acknowledgement": egress,
        "message": message,
        "accuracy_notice": (
            "A reconstructed mesh is an estimate from photographs, not "
            "dimensionally authoritative CAD. Verify critical dimensions against "
            "measurements before manufacturing or quoting."
        ),
        "verify_path": "/verify",
    }


@router.post("/reconstruct", status_code=202)
async def reconstruct(
    images: list[UploadFile] = File(...),
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=26,
        max_length=26,
        pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$",
    ),
    reconstruction_egress_acknowledged: bool = Header(
        False,
        alias="X-Reconstruction-Egress-Acknowledged",
    ),
    process_types: Optional[str] = Query(None, description="Comma-separated process types for analysis after reconstruction."),
    rule_pack: Optional[str] = Query(None, description="Industry rule pack: aerospace, automotive, oil_gas, medical."),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload 1-4 images for 3D reconstruction. Returns 202 with job_id for polling."""
    # Validate image count (cheap request-shape check, no egress).
    if len(images) < 1 or len(images) > 4:
        raise HTTPException(status_code=400, detail="Upload 1-4 images")

    # HONESTY / zero-egress gate: refuse to accept work we cannot run without a
    # silent third-party egress. If no local model is available and remote
    # egress has not been explicitly opted in, announce unavailability up front
    # with a stable error code -- never silently egress, never a confusing 500.
    availability = reconstruction_service.check_reconstruction_availability()
    if not availability["available"]:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "RECONSTRUCTION_UNAVAILABLE",
                "message": availability["reason"],
                "doc_url": error_doc_url("RECONSTRUCTION_UNAVAILABLE"),
            },
        )
    egress = bool(availability.get("egress"))
    if egress and not reconstruction_egress_acknowledged:
        raise HTTPException(
            status_code=428,
            detail={
                "code": "RECONSTRUCTION_EGRESS_ACKNOWLEDGEMENT_REQUIRED",
                "message": (
                    "This reconstruction backend sends customer-derived imagery "
                    "to an approved third-party provider. Explicit acknowledgement "
                    "is required before upload."
                ),
                "doc_url": error_doc_url(
                    "RECONSTRUCTION_EGRESS_ACKNOWLEDGEMENT_REQUIRED"
                ),
            },
        )

    # Read all image bytes
    image_data: list[tuple[bytes, str]] = []
    for img in images:
        img_bytes = await img.read()
        content_type = img.content_type or "image/jpeg"
        image_data.append((img_bytes, content_type))

    # Create job (validates images, persists, enqueues)
    try:
        job = await reconstruction_service.create_reconstruction_job(
            session,
            user,
            image_data,
            process_types,
            rule_pack,
            idempotency_key,
            egress_acknowledged=(
                reconstruction_egress_acknowledged if egress else False
            ),
        )
    except reconstruction_service.ReconstructionIdempotencyConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except reconstruction_service.ReconstructionQueueUnavailableError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "RECONSTRUCTION_ENQUEUE_FAILED",
                "job_id": e.job_id,
                "retryable": True,
                "message": (
                    "Reconstruction publication could not be confirmed. The "
                    "request is retained and can be retried safely."
                ),
                "doc_url": error_doc_url("RECONSTRUCTION_ENQUEUE_FAILED"),
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.ulid,
            "status": job.status,
            "poll_url": f"/api/v1/jobs/{job.ulid}",
            "estimated_seconds": 30,
        },
    )


@router.get("/reconstructions/{job_id}/mesh.stl")
async def download_reconstruction_mesh(
    job_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Download the reconstructed mesh STL file. Requires authentication and job ownership."""
    mesh_stream = await reconstruction_service.open_reconstruction_mesh(
        session, job_id, user.user_id
    )
    if mesh_stream is None:
        raise HTTPException(status_code=404, detail="Mesh not found or job not complete")

    def body():
        try:
            while chunk := mesh_stream.read(256 * 1024):
                yield chunk
        finally:
            mesh_stream.close()

    return StreamingResponse(
        body(),
        media_type="application/sla",
        headers={
            "Content-Disposition": f'attachment; filename="reconstructed_{job_id}.stl"'
        },
    )
