"""Reconstruct API endpoints -- image upload and mesh download.

POST /api/v1/reconstruct              -- upload 1-4 images, returns 202
GET  /api/v1/reconstructions/{id}/mesh.stl -- download reconstructed mesh
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import reconstruction_service

logger = logging.getLogger("cadverify.reconstruct_router")

router = APIRouter(prefix="/api/v1", tags=["reconstruct"])


@router.post("/reconstruct", status_code=202)
async def reconstruct(
    images: list[UploadFile] = File(...),
    process_types: Optional[str] = Query(None, description="Comma-separated process types for analysis after reconstruction."),
    rule_pack: Optional[str] = Query(None, description="Industry rule pack: aerospace, automotive, oil_gas, medical."),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload 1-4 images for 3D reconstruction. Returns 202 with job_id for polling."""
    # Validate image count
    if len(images) < 1 or len(images) > 4:
        raise HTTPException(status_code=400, detail="Upload 1-4 images")

    # Read all image bytes
    image_data: list[tuple[bytes, str]] = []
    for img in images:
        img_bytes = await img.read()
        content_type = img.content_type or "image/jpeg"
        image_data.append((img_bytes, content_type))

    # Create job (validates images, persists, enqueues)
    try:
        job = await reconstruction_service.create_reconstruction_job(
            session, user, image_data, process_types, rule_pack
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        status_code=202,
        content={
            "job_id": job.ulid,
            "status": "queued",
            "poll_url": f"/api/v1/jobs/{job.ulid}",
            "estimated_seconds": 30,
        },
    )


@router.get("/reconstructions/{job_id}/mesh.stl")
async def download_reconstruction_mesh(
    job_id: str,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Download the reconstructed mesh STL file. Requires authentication and job ownership."""
    mesh_path = await reconstruction_service.get_reconstruction_mesh_path(
        session, job_id, user.user_id
    )
    if mesh_path is None:
        raise HTTPException(status_code=404, detail="Mesh not found or job not complete")

    return FileResponse(
        mesh_path,
        media_type="application/sla",
        filename=f"reconstructed_{job_id}.stl",
    )
