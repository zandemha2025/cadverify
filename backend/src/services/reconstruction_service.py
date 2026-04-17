"""Reconstruction service -- job creation, engine factory, blob storage."""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.require_api_key import AuthedUser
from src.db.models import Job
from src.reconstruction.preprocessing import validate_image

logger = logging.getLogger("cadverify.reconstruction_service")

RECON_BLOB_DIR = os.getenv("RECON_BLOB_DIR", "/data/blobs/reconstruct")
RECONSTRUCTION_BACKEND = os.getenv("RECONSTRUCTION_BACKEND", "remote")

# ULID validation: 26 alphanumeric characters (Crockford Base32)
_ULID_RE = re.compile(r"^[0-9A-Za-z]{26}$")


def _validate_ulid(ulid: str) -> None:
    """Validate ULID format to prevent path traversal (threat model)."""
    if not _ULID_RE.match(ulid):
        raise ValueError(f"Invalid ULID format: {ulid}")


def get_reconstruction_engine():
    """Factory: return the configured ReconstructionEngine."""
    from src.reconstruction.engine import ReconstructionEngine  # noqa: F401

    backend = os.getenv("RECONSTRUCTION_BACKEND", RECONSTRUCTION_BACKEND)
    if backend == "local":
        from src.reconstruction.local_triposr import LocalTripoSR
        return LocalTripoSR.load()
    if backend == "remote":
        from src.reconstruction.remote_triposr import RemoteTripoSR
        return RemoteTripoSR()
    raise ValueError(f"Unknown reconstruction backend: {backend}")


async def save_reconstruction_images(
    job_ulid: str, images: list[tuple[bytes, str]]
) -> str:
    """Save uploaded images to blob storage. Returns input directory path."""
    _validate_ulid(job_ulid)
    input_dir = os.path.join(RECON_BLOB_DIR, job_ulid, "input")
    os.makedirs(input_dir, exist_ok=True)

    for i, (img_bytes, content_type) in enumerate(images):
        # Derive extension from content_type
        ext_map = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }
        ext = ext_map.get(content_type, "bin")
        filepath = os.path.join(input_dir, f"image_{i:03d}.{ext}")
        with open(filepath, "wb") as f:
            f.write(img_bytes)

    return input_dir


async def save_reconstruction_mesh(job_ulid: str, mesh_bytes: bytes) -> str:
    """Save reconstructed mesh to blob storage. Returns path to mesh.stl."""
    _validate_ulid(job_ulid)
    output_dir = os.path.join(RECON_BLOB_DIR, job_ulid, "output")
    os.makedirs(output_dir, exist_ok=True)
    mesh_path = os.path.join(output_dir, "mesh.stl")
    with open(mesh_path, "wb") as f:
        f.write(mesh_bytes)
    return mesh_path


async def create_reconstruction_job(
    session: AsyncSession,
    user: AuthedUser,
    images: list[tuple[bytes, str]],
    process_types: str | None,
    rule_pack: str | None,
) -> Job:
    """Create a reconstruction job: validate images, persist Job row, save blobs, enqueue.

    Args:
        session: DB session (caller commits).
        user: Authenticated user.
        images: List of (file_bytes, content_type) tuples.
        process_types: Comma-separated process types for auto-feed analysis.
        rule_pack: Industry rule pack for auto-feed analysis.

    Returns:
        The created Job ORM instance.
    """
    # Validate image count
    if len(images) < 1 or len(images) > 4:
        raise ValueError("Upload 1-4 images for reconstruction")

    # Validate each image
    for img_bytes, content_type in images:
        validate_image(img_bytes, content_type)

    # Create Job row
    job = Job(
        ulid=str(ULID()),
        user_id=user.user_id,
        job_type="reconstruction",
        status="queued",
        params_json={
            "image_count": len(images),
            "process_types": process_types,
            "rule_pack": rule_pack,
        },
    )
    session.add(job)
    await session.flush()

    # Save images to blob storage
    await save_reconstruction_images(job.ulid, images)

    # Enqueue arq task
    from src.jobs.arq_backend import get_arq_pool
    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_reconstruction_job",
        job.ulid,
        _job_id=f"recon_{job.ulid}",
    )

    logger.info(
        "Created reconstruction job %s with %d images for user %s",
        job.ulid,
        len(images),
        user.user_id,
    )
    return job


async def get_reconstruction_mesh_path(
    session: AsyncSession, job_ulid: str, user_id: int
) -> Optional[str]:
    """Return path to reconstructed mesh if job is complete and owned by user.

    Returns None if job not found, wrong user, or not yet complete.
    """
    _validate_ulid(job_ulid)

    job = (
        await session.execute(
            select(Job).where(Job.ulid == job_ulid, Job.user_id == user_id)
        )
    ).scalars().first()

    if job is None:
        return None

    if job.status not in ("done", "partial"):
        return None

    mesh_path = os.path.join(RECON_BLOB_DIR, job_ulid, "output", "mesh.stl")
    if not os.path.exists(mesh_path):
        return None

    return mesh_path
