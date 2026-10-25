"""arq task definitions -- thin adapters calling service functions."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from src.db.engine import get_session_factory
from src.db.models import Job

logger = logging.getLogger("cadverify.jobs.tasks")

_TERMINAL_JOB_STATUSES = {"done", "partial", "failed"}


async def run_sam3d_job(ctx: dict, job_ulid: str) -> dict:
    """Process a SAM-3D segmentation job.

    1. Read job from DB
    2. Load mesh from blob storage
    3. Run segment_sam3d()
    4. On failure: run segment_heuristic() fallback
    5. Write result to jobs row
    """
    import asyncio
    import io
    import os

    import trimesh

    from src.segmentation.fallback import segment_heuristic
    from src.segmentation.sam3d.config import SAM3DConfig
    from src.segmentation.sam3d.pipeline import segment_sam3d

    session_factory = get_session_factory()

    async with session_factory() as session:
        # 1. Load job
        job = (
            await session.execute(select(Job).where(Job.ulid == job_ulid))
        ).scalars().first()
        if job is None:
            logger.error("Job %s not found", job_ulid)
            return {"error": "job_not_found"}
        if job.job_type != "sam3d":
            logger.error("Job %s has unexpected type %s", job_ulid, job.job_type)
            return {"error": "job_type_mismatch"}
        if job.status in _TERMINAL_JOB_STATUSES:
            logger.info("SAM-3D job %s already terminal: %s", job_ulid, job.status)
            return job.result_json or {"status": job.status}
        if job.status == "running" and int(ctx.get("job_try", 1)) <= 1:
            logger.info("SAM-3D job %s is already running", job_ulid)
            return job.result_json or {"status": "running"}

        # Update status to running
        job.status = "running"
        job.started_at = job.started_at or datetime.now(timezone.utc)
        await session.commit()

        # 2. Load mesh from blob storage
        mesh_hash = job.params_json.get("mesh_hash", "") if job.params_json else ""

        try:
            from src.services.job_service import MESH_BLOB_DIR
            from src.storage import get_object_store

            store = get_object_store(
                "meshes",
                default_root=os.getenv("MESH_BLOB_DIR", MESH_BLOB_DIR),
            )
            mesh_bytes = await asyncio.to_thread(store.get, f"{mesh_hash}.bin")
            mesh = trimesh.load(io.BytesIO(mesh_bytes), file_type="stl")
        except Exception:
            logger.exception("Failed to load mesh for job %s", job_ulid)
            job.status = "partial"
            job.result_json = {"error": "mesh_load_failed", "fallback": "none"}
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return job.result_json

        # 3. Try SAM-3D
        config = SAM3DConfig.from_env()
        start = time.time()
        status = "done"
        try:
            segments = segment_sam3d(mesh, config)
            if not segments:
                raise RuntimeError("SAM-3D returned empty segments")
        except Exception:
            logger.warning("SAM-3D failed for job %s, falling back to heuristic", job_ulid)
            segments = segment_heuristic(mesh)
            status = "partial"

        duration_ms = (time.time() - start) * 1000

        # 4. Serialize result
        result = {
            "segments": [_segment_to_dict(s) for s in segments],
            "method": "sam3d" if status == "done" else "heuristic_fallback",
            "duration_ms": round(duration_ms, 1),
            "segment_count": len(segments),
        }

        # 5. Write result
        job.status = status
        job.result_json = result
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()

        logger.info(
            "Job %s completed: status=%s segments=%d duration=%.1fms",
            job_ulid, status, len(segments), duration_ms,
        )
        return result


def _segment_to_dict(seg) -> dict:
    """Convert a segment (SemanticSegment or FeatureSegment) to dict."""
    if hasattr(seg, "label"):
        # SemanticSegment from SAM-3D
        return {
            "label": seg.label.value if hasattr(seg.label, "value") else str(seg.label),
            "face_indices": seg.face_indices[:1000],  # Cap for JSON size
            "centroid": list(seg.centroid),
            "confidence": seg.confidence,
            "view_agreement": getattr(seg, "view_agreement", None),
        }
    else:
        # FeatureSegment from heuristic fallback
        return {
            "feature_type": seg.feature_type.value if hasattr(seg.feature_type, "value") else str(seg.feature_type),
            "face_indices": seg.face_indices[:1000],
            "centroid": list(seg.centroid),
            "confidence": seg.confidence,
            "segment_id": seg.segment_id,
        }
