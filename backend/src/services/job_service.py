"""Job service -- create, query, and manage async jobs."""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import Job

logger = logging.getLogger("cadverify.job_service")

MESH_BLOB_DIR = os.getenv("MESH_BLOB_DIR", "/data/blobs/meshes")


async def save_mesh_blob(mesh_hash: str, file_bytes: bytes) -> str:
    """Save mesh bytes to blob storage. Returns blob path. Idempotent."""
    blob_dir = os.getenv("MESH_BLOB_DIR", MESH_BLOB_DIR)
    os.makedirs(blob_dir, exist_ok=True)
    blob_path = os.path.join(blob_dir, f"{mesh_hash}.bin")
    if not os.path.exists(blob_path):
        with open(blob_path, "wb") as f:
            f.write(file_bytes)
    return blob_path


async def create_sam3d_job(
    session: AsyncSession,
    analysis_id: int,
    user_id: int,
    mesh_hash: str,
) -> Job:
    """Create a SAM-3D job for an analysis. Idempotent by (analysis_id, 'sam3d').

    If a job already exists for this analysis+type, returns existing job.
    Handles race condition via IntegrityError catch on the ULID unique constraint.
    """
    # Check for existing job (idempotency)
    existing = (
        await session.execute(
            select(Job).where(
                Job.analysis_id == analysis_id,
                Job.job_type == "sam3d",
            )
        )
    ).scalars().first()
    if existing is not None:
        logger.info(
            "Idempotent hit: job %s already exists for analysis %d",
            existing.ulid,
            analysis_id,
        )
        return existing

    # Create new job
    job = Job(
        ulid=str(ULID()),
        user_id=user_id,
        analysis_id=analysis_id,
        job_type="sam3d",
        status="queued",
        params_json={"mesh_hash": mesh_hash},
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        # Race condition: another request created the job. Re-query.
        existing = (
            await session.execute(
                select(Job).where(
                    Job.analysis_id == analysis_id,
                    Job.job_type == "sam3d",
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing
        raise  # Unexpected IntegrityError
    return job


async def get_job_for_user(
    session: AsyncSession,
    job_ulid: str,
    user_id: int,
) -> Optional[Job]:
    """Get a job by ULID, only if owned by user_id.

    Returns None for non-existent or other user's jobs (D-12: 404 not 403).
    """
    job = (
        await session.execute(
            select(Job).where(Job.ulid == job_ulid, Job.user_id == user_id)
        )
    ).scalars().first()
    return job
