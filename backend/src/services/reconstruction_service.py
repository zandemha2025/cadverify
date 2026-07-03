"""Reconstruction service -- job creation, engine factory, blob storage.

Zero-egress by default (HONESTY / data-locality invariant)
----------------------------------------------------------
Image->mesh reconstruction can run either on a *local* TripoSR model (no
customer data leaves the deployment) or via a *remote* Replicate-hosted model
(which EGRESSES customer-derived imagery to a third-party cloud -- an ITAR /
data-residency landmine).

The default backend is ``local`` so **no customer data ever leaves the
deployment without explicit, informed operator opt-in**.  Remote egress is only
honored when the operator deliberately opts in, either by setting
``RECONSTRUCTION_BACKEND=remote`` or ``RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1``,
and every egress path logs a loud data-egress acknowledgment.

When no local model is installed (torch/tsr absent) and remote egress has NOT
been opted in, reconstruction announces itself as *unavailable* honestly
(``ReconstructionUnavailableError`` -> HTTP 501 ``RECONSTRUCTION_UNAVAILABLE``)
instead of silently egressing or throwing a confusing 500.
"""
from __future__ import annotations

import importlib.util
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

# HONESTY default: local-only. Never default-on to third-party egress.
DEFAULT_RECONSTRUCTION_BACKEND = "local"

_TRUTHY = {"1", "true", "yes", "on"}

# ULID validation: 26 alphanumeric characters (Crockford Base32)
_ULID_RE = re.compile(r"^[0-9A-Za-z]{26}$")


class ReconstructionUnavailableError(RuntimeError):
    """Reconstruction cannot run without violating the no-silent-egress rule.

    Raised when there is no local model available and remote (third-party)
    egress has not been explicitly opted in.  Callers surface this as a stable,
    structured ``501 RECONSTRUCTION_UNAVAILABLE`` response -- an honest
    "not available in this deployment" announcement, never a silent egress.
    """

    code = "RECONSTRUCTION_UNAVAILABLE"


def _validate_ulid(ulid: str) -> None:
    """Validate ULID format to prevent path traversal (threat model)."""
    if not _ULID_RE.match(ulid):
        raise ValueError(f"Invalid ULID format: {ulid}")


def configured_backend() -> str:
    """Return the operator-configured backend name (default: local)."""
    return os.getenv(
        "RECONSTRUCTION_BACKEND", DEFAULT_RECONSTRUCTION_BACKEND
    ).strip().lower()


def remote_egress_allowed() -> bool:
    """True if the operator has explicitly opted in to third-party data egress.

    Remote reconstruction sends customer-derived imagery to Replicate's hosted
    cloud.  It must be an explicit, informed choice -- never default-on.
    """
    return os.getenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", "").strip().lower() in _TRUTHY


def local_backend_available() -> bool:
    """True if the local TripoSR inference stack (torch + tsr) is importable.

    Cheap probe -- does not load the heavy model weights.
    """
    return (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("tsr") is not None
    )


def resolve_reconstruction_backend() -> tuple[str, bool]:
    """Resolve the effective backend, enforcing zero-egress-by-default.

    Returns ``(effective_backend, egresses_off_box)`` where ``effective_backend``
    is ``"local"`` or ``"remote"``.

    Raises:
        ReconstructionUnavailableError: reconstruction cannot run without a
            silent egress (no local model + remote egress not opted in), or the
            operator disabled it (``RECONSTRUCTION_BACKEND=none``).
        ValueError: unknown backend name configured.
    """
    backend = configured_backend()

    # Explicitly choosing remote IS an informed opt-in to third-party egress.
    if backend == "remote":
        return "remote", True

    if backend == "none":
        raise ReconstructionUnavailableError(
            "Reconstruction is disabled in this deployment "
            "(RECONSTRUCTION_BACKEND=none)."
        )

    if backend == "local":
        if local_backend_available():
            return "local", False
        # No local model. Only egress if the operator explicitly opted in.
        if remote_egress_allowed():
            return "remote", True
        raise ReconstructionUnavailableError(
            "Reconstruction is not available in this deployment: no local model "
            "(torch/tsr not installed) and remote egress is not enabled. "
            "To enable remote reconstruction via Replicate -- which sends "
            "customer-derived imagery to a third-party cloud -- set "
            "RECONSTRUCTION_ALLOW_REMOTE_EGRESS=1 (or RECONSTRUCTION_BACKEND=remote). "
            "Ensure this complies with your data-residency / ITAR obligations."
        )

    raise ValueError(f"Unknown reconstruction backend: {backend}")


def check_reconstruction_availability() -> dict:
    """Honest, non-raising availability report for endpoints / health probes.

    Returns a structured dict describing whether reconstruction can run in this
    deployment and whether the effective path egresses customer data off-box.
    """
    backend = configured_backend()
    try:
        effective, egress = resolve_reconstruction_backend()
    except ReconstructionUnavailableError as exc:
        return {
            "available": False,
            "configured_backend": backend,
            "effective_backend": "none",
            "egress": False,
            "reason": str(exc),
        }
    return {
        "available": True,
        "configured_backend": backend,
        "effective_backend": effective,
        "egress": egress,
        "reason": (
            "remote reconstruction (Replicate) enabled -- customer-derived "
            "imagery egresses to a third-party cloud"
            if egress
            else "local reconstruction -- no customer data leaves the deployment"
        ),
    }


def get_reconstruction_engine():
    """Factory: return the effective ReconstructionEngine.

    Enforces zero-egress-by-default. Logs a loud data-egress acknowledgment
    whenever the effective backend sends customer data off-box.

    Raises:
        ReconstructionUnavailableError: reconstruction not available without a
            silent egress (surfaced as 501 RECONSTRUCTION_UNAVAILABLE).
    """
    from src.reconstruction.engine import ReconstructionEngine  # noqa: F401

    backend, egress = resolve_reconstruction_backend()

    if egress:
        logger.warning(
            "DATA EGRESS ACKNOWLEDGED: reconstruction backend=%s sends "
            "customer-derived imagery to a third-party cloud (Replicate). This "
            "is an explicit, opted-in configuration "
            "(RECONSTRUCTION_BACKEND=remote or RECONSTRUCTION_ALLOW_REMOTE_EGRESS). "
            "Verify data-residency / ITAR compliance.",
            backend,
        )

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
    from src.auth.org_context import resolve_org

    job = Job(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=await resolve_org(session, user.user_id),
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
