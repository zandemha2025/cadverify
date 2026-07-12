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

import asyncio
import importlib.util
import logging
import os
import re
from datetime import datetime, timezone
from typing import BinaryIO, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery
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


def _reconstruction_store():
    from src.storage import get_object_store

    return get_object_store(
        "reconstruct",
        default_root=os.getenv("RECON_BLOB_DIR", RECON_BLOB_DIR),
    )


def _reconstruction_key(job_ulid: str, relative: str) -> str:
    _validate_ulid(job_ulid)
    if not relative or relative.startswith("/") or ".." in relative.split("/"):
        raise ValueError("invalid reconstruction object key")
    return f"{job_ulid}/{relative}"


async def _cleanup_reconstruction_prefix(prefix: str) -> None:
    try:
        await asyncio.to_thread(_reconstruction_store().delete_prefix, prefix)
    except Exception:
        logger.exception("Failed to clean reconstruction objects under %s", prefix)


class ReconstructionUnavailableError(RuntimeError):
    """Reconstruction cannot run without violating the no-silent-egress rule.

    Raised when there is no local model available and remote (third-party)
    egress has not been explicitly opted in.  Callers surface this as a stable,
    structured ``501 RECONSTRUCTION_UNAVAILABLE`` response -- an honest
    "not available in this deployment" announcement, never a silent egress.
    """

    code = "RECONSTRUCTION_UNAVAILABLE"


class ReconstructionQueueUnavailableError(RuntimeError):
    """A persisted reconstruction job could not be scheduled."""

    code = "RECONSTRUCTION_ENQUEUE_FAILED"


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
    """Save uploaded images to the configured durable object store."""
    _validate_ulid(job_ulid)
    store = _reconstruction_store()

    try:
        for i, (img_bytes, content_type) in enumerate(images):
            # Derive extension from content_type
            ext_map = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
            }
            ext = ext_map.get(content_type, "bin")
            key = _reconstruction_key(job_ulid, f"input/image_{i:03d}.{ext}")
            await asyncio.to_thread(
                store.put,
                key,
                img_bytes,
                content_type=content_type,
            )
    except BaseException:
        await _cleanup_reconstruction_prefix(f"{job_ulid}/input")
        raise

    return store.url(_reconstruction_key(job_ulid, "input"))


def load_reconstruction_images(job_ulid: str) -> list[tuple[bytes, str]]:
    """Load deterministic input objects for a reconstruction worker."""
    store = _reconstruction_store()
    prefix = _reconstruction_key(job_ulid, "input")
    ext_to_ct = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    images: list[tuple[bytes, str]] = []
    for key in store.list_keys(prefix):
        ext = key.rsplit(".", 1)[-1].lower()
        images.append((store.get(key), ext_to_ct.get(ext, "application/octet-stream")))
    return images


async def save_reconstruction_mesh(job_ulid: str, mesh_bytes: bytes) -> str:
    """Save reconstructed mesh to durable storage and return its locator."""
    store = _reconstruction_store()
    key = _reconstruction_key(job_ulid, "output/mesh.stl")
    return await asyncio.to_thread(
        store.put,
        key,
        mesh_bytes,
        content_type="application/sla",
    )


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

    # Persist blobs and the DB row before enqueue. This closes the historical
    # race where a fast worker could consume the job before the request-scoped
    # transaction committed and report job_not_found.
    try:
        await save_reconstruction_images(job.ulid, images)
        await session.commit()
    except BaseException:
        await _cleanup_reconstruction_prefix(job.ulid)
        raise

    # Enqueue arq task. A queue outage leaves an honest terminal row and no
    # orphaned customer blobs instead of a forever-queued record.
    from src.jobs.arq_backend import get_arq_pool

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_reconstruction_job",
            job.ulid,
            _job_id=f"recon_{job.ulid}",
        )
    except Exception as exc:
        job.status = "failed"
        job.result_json = {"code": "RECONSTRUCTION_ENQUEUE_FAILED"}
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()
        await _cleanup_reconstruction_prefix(job.ulid)
        raise ReconstructionQueueUnavailableError(
            "Reconstruction was accepted but could not be scheduled"
        ) from exc

    logger.info(
        "Created reconstruction job %s with %d images for user %s",
        job.ulid,
        len(images),
        user.user_id,
    )
    return job


async def open_reconstruction_mesh(
    session: AsyncSession, job_ulid: str, user_id: int
) -> Optional[BinaryIO]:
    """Open a completed mesh stream when the job is in the caller's org.

    Returns None if the job does not exist, belongs to another org, or is not
    yet complete (W1 step 3: org-scoped — ``user_id`` resolves the org boundary).
    The caller owns and must close the returned stream.
    """
    _validate_ulid(job_ulid)

    job = (
        await session.execute(
            select(Job).where(
                Job.ulid == job_ulid,
                Job.org_id == caller_org_subquery(user_id),
            )
        )
    ).scalars().first()

    if job is None:
        return None

    if job.status not in ("done", "partial"):
        return None

    from src.storage import ObjectNotFoundError

    key = _reconstruction_key(job_ulid, "output/mesh.stl")
    try:
        return await asyncio.to_thread(_reconstruction_store().open, key)
    except ObjectNotFoundError:
        return None
