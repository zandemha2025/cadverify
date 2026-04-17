"""Job status polling endpoints for async processing."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.services import job_service

logger = logging.getLogger("cadverify.jobs_router")

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job_status(
    job_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Get job status. Returns 404 for non-existent or other user's jobs (D-12)."""
    job = await job_service.get_job_for_user(session, job_id, user.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job.ulid,
        "status": job.status,
        "job_type": job.job_type,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result_url": None,
    }
    if job.status in ("done", "partial"):
        response["result_url"] = f"/api/v1/jobs/{job.ulid}/result"
    return response


@router.get("/{job_id}/result")
async def get_job_result(
    job_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Get job result. Returns 404 if job not complete or not found (D-11)."""
    job = await job_service.get_job_for_user(session, job_id, user.user_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("done", "partial"):
        raise HTTPException(status_code=404, detail="Job result not yet available")
    return {
        "job_id": job.ulid,
        "status": job.status,
        "result": job.result_json,
    }
