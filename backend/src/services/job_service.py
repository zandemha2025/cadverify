"""Job service -- create, query, and manage async jobs."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery
from src.db.models import Job

logger = logging.getLogger("cadverify.job_service")

MESH_BLOB_DIR = os.getenv("MESH_BLOB_DIR", "/data/blobs/meshes")


async def save_mesh_blob(mesh_hash: str, file_bytes: bytes) -> str:
    """Save mesh bytes to blob storage. Returns a locator. Idempotent.

    Wired through the object-store abstraction (:mod:`src.storage`). With the
    default local backend this is byte-for-byte identical to the historical
    behavior: the blob lands at ``$MESH_BLOB_DIR/{hash}.bin`` and the returned
    value is that absolute filesystem path. With S3 selected, the worker reads
    the same key through the object-store interface and no shared volume is
    required.
    """
    from src.storage import LocalObjectStore, get_object_store

    blob_dir = os.getenv("MESH_BLOB_DIR", MESH_BLOB_DIR)
    store = get_object_store("meshes", default_root=blob_dir)
    key = f"{mesh_hash}.bin"
    if not await asyncio.to_thread(store.exists, key):
        await asyncio.to_thread(
            store.put,
            key,
            file_bytes,
            content_type="application/octet-stream",
        )
    # Preserve the historical contract: local backend returns the on-disk path.
    if isinstance(store, LocalObjectStore):
        return store.local_path(key)
    return store.url(key)


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
        # Releases before the durable-publication fix marked ambiguous queue
        # failures terminal.  Revive only that exact legacy state so a retry can
        # safely offer the same deterministic ARQ job ID again.
        if (
            existing.status == "failed"
            and isinstance(existing.result_json, dict)
            and existing.result_json.get("code") == "SAM3D_ENQUEUE_FAILED"
        ):
            existing.status = "queued"
            existing.result_json = None
            existing.completed_at = None
            await session.flush()
        logger.info(
            "Idempotent hit: job %s already exists for analysis %d",
            existing.ulid,
            analysis_id,
        )
        return existing

    # Create new job
    from src.auth.org_context import resolve_org

    job = Job(
        ulid=str(ULID()),
        user_id=user_id,
        org_id=await resolve_org(session, user_id),
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
    """Get a job by ULID, scoped to the caller's org.

    W1 step 3: the isolation predicate is ``org_id`` (resolved from ``user_id``
    via a correlated subquery). Returns None for a non-existent job or one in
    another org, so the route answers 404 (never 403 — existence never leaks).
    """
    job = (
        await session.execute(
            select(Job).where(
                Job.ulid == job_ulid,
                Job.org_id == caller_org_subquery(user_id),
            )
        )
    ).scalars().first()
    return job
