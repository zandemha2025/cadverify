"""ARQ task for deterministic, sandboxed Design Studio generation."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from src.db.engine import get_session_factory
from src.db.models import DesignProject, DesignRevision, Job
from src.designs.generator import DesignGenerationError, generate_design_artifacts
from src.services.audit_service import emit_event
from src.services.design_service import (
    DESIGN_KERNEL_FAILURE_COPY,
    DESIGN_STORE_FAILURE_COPY,
    _design_store,
    artifact_prefix,
)

logger = logging.getLogger("cadverify.jobs.design_tasks")


async def _mark_failed(job_ulid: str, code: str, message: str) -> dict:
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        job = (
            await session.execute(select(Job).where(Job.ulid == job_ulid))
        ).scalars().first()
        if job is None:
            return {"code": "DESIGN_JOB_NOT_FOUND"}
        if job.status == "done":
            return job.result_json or {"status": "done"}
        revision_ulid = (job.params_json or {}).get("revision_ulid")
        revision = (
            await session.execute(
                select(DesignRevision).where(
                    DesignRevision.ulid == revision_ulid,
                    DesignRevision.org_id == job.org_id,
                )
            )
        ).scalars().first()
        project = (
            await session.execute(
                select(DesignProject).where(
                    DesignProject.id == revision.design_id,
                    DesignProject.org_id == job.org_id,
                )
            )
        ).scalars().first() if revision is not None else None
        job.status = "failed"
        job.result_json = {"code": code, "message": message}
        job.completed_at = now
        if revision is None or project is None:
            await session.commit()
            return {"code": code, "message": message}
        revision.status = "failed"
        revision.error_code = code
        revision.error_detail = message
        revision.completed_at = now
        if project.current_revision == revision.revision_no:
            project.status = "failed"
            project.updated_at = now
        await emit_event(
            session,
            actor_id=job.user_id,
            action="design.generation_failed",
            resource_type="design_revision",
            resource_id=revision.ulid,
            detail={"design_id": project.ulid, "revision": revision.revision_no, "code": code},
            org_id=job.org_id,
        )
        await session.commit()
    return {"code": code, "message": message}


async def run_design_generation_job(ctx: dict, job_ulid: str) -> dict:
    """Apply the per-worker CAD admission cap before starting a child kernel."""
    semaphore = ctx.get("design_generation_semaphore")
    if semaphore is None:
        return await _run_design_generation_job(job_ulid)
    async with semaphore:
        return await _run_design_generation_job(job_ulid)


async def _run_design_generation_job(job_ulid: str) -> dict:
    """Generate one revision without holding a DB connection during CAD work."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        job = (
            await session.execute(select(Job).where(Job.ulid == job_ulid))
        ).scalars().first()
        if job is None or job.job_type != "design_generation":
            return {"code": "DESIGN_JOB_NOT_FOUND"}
        if job.status == "done":
            return job.result_json or {"status": "done"}
        job_params = job.params_json or {}
        revision_ulid = job_params.get("revision_ulid")
        release_test_fault = job_params.get("release_test_fault")
        revision = (
            await session.execute(
                select(DesignRevision).where(
                    DesignRevision.ulid == revision_ulid,
                    DesignRevision.org_id == job.org_id,
                )
            )
        ).scalars().first()
        if revision is None:
            job.status = "failed"
            job.result_json = {"code": "DESIGN_REVISION_NOT_FOUND"}
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"code": "DESIGN_REVISION_NOT_FOUND"}
        project = (
            await session.execute(
                select(DesignProject).where(
                    DesignProject.id == revision.design_id,
                    DesignProject.org_id == job.org_id,
                )
            )
        ).scalars().first()
        if project is None:
            job.status = "failed"
            job.result_json = {"code": "DESIGN_PROJECT_NOT_FOUND"}
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return {"code": "DESIGN_PROJECT_NOT_FOUND"}
        now = datetime.now(timezone.utc)
        job.status = "running"
        job.started_at = now
        revision.status = "generating"
        revision.started_at = now
        if project.current_revision == revision.revision_no:
            project.status = "generating"
            project.updated_at = now
        plan = dict(revision.operation_plan_json)
        project_ulid = project.ulid
        org_id = project.org_id
        revision_no = revision.revision_no
        await session.commit()

    try:
        if release_test_fault == "cad_kernel":
            raise DesignGenerationError("record-scoped release fault: CAD kernel")
        artifacts = await asyncio.to_thread(generate_design_artifacts, plan)

        store = _design_store()
        prefix = artifact_prefix(org_id, project_ulid, revision_no)
        step_key = f"{prefix}/model.step"
        stl_key = f"{prefix}/preview.stl"
        try:
            await asyncio.to_thread(
                store.put,
                step_key,
                artifacts.step_bytes,
                content_type="model/step",
            )
            if release_test_fault == "object_store":
                raise RuntimeError("record-scoped release fault: object store")
            await asyncio.to_thread(
                store.put,
                stl_key,
                artifacts.stl_bytes,
                content_type="model/stl",
            )
        except BaseException:
            await asyncio.to_thread(store.delete_prefix, prefix)
            raise
    except DesignGenerationError as exc:
        logger.warning("Design generation failed for %s: %s", job_ulid, exc)
        return await _mark_failed(
            job_ulid,
            getattr(exc, "code", "DESIGN_GENERATION_FAILED"),
            DESIGN_KERNEL_FAILURE_COPY,
        )
    except Exception:
        logger.exception("Design artifact persistence failed for %s", job_ulid)
        return await _mark_failed(
            job_ulid,
            "DESIGN_ARTIFACT_STORE_FAILED",
            DESIGN_STORE_FAILURE_COPY,
        )

    geometry_hash = hashlib.sha256(artifacts.step_bytes).hexdigest()
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        job = (
            await session.execute(select(Job).where(Job.ulid == job_ulid))
        ).scalars().first()
        if job is None:
            await asyncio.to_thread(store.delete_prefix, prefix)
            return {"code": "DESIGN_ROW_DISAPPEARED"}
        if job.status == "done":
            return job.result_json or {"status": "done"}
        revision = (
            await session.execute(
                select(DesignRevision).where(
                    DesignRevision.ulid == revision_ulid,
                    DesignRevision.org_id == job.org_id,
                )
            )
        ).scalars().first()
        project = (
            await session.execute(
                select(DesignProject).where(
                    DesignProject.ulid == project_ulid,
                    DesignProject.org_id == job.org_id,
                )
            )
        ).scalars().first()
        if not revision or not project:
            await asyncio.to_thread(store.delete_prefix, prefix)
            return {"code": "DESIGN_ROW_DISAPPEARED"}
        revision.status = "ready"
        revision.geometry_hash = geometry_hash
        revision.step_object_key = step_key
        revision.stl_object_key = stl_key
        revision.step_size_bytes = len(artifacts.step_bytes)
        revision.stl_size_bytes = len(artifacts.stl_bytes)
        revision.geometry_metadata_json = artifacts.metadata
        revision.error_code = None
        revision.error_detail = None
        revision.completed_at = now
        if project.current_revision == revision.revision_no:
            project.status = "ready"
            project.updated_at = now
        result = {
            "design_id": project.ulid,
            "revision": revision.revision_no,
            "geometry_hash": geometry_hash,
            "preview_url": (
                f"/api/v1/designs/{project.ulid}/revisions/"
                f"{revision.revision_no}/preview.stl"
            ),
            "step_url": (
                f"/api/v1/designs/{project.ulid}/revisions/"
                f"{revision.revision_no}/download.step"
            ),
        }
        job.status = "done"
        job.result_json = result
        job.completed_at = now
        await emit_event(
            session,
            actor_id=job.user_id,
            action="design.generated",
            resource_type="design_revision",
            resource_id=revision.ulid,
            detail={
                "design_id": project.ulid,
                "revision": revision.revision_no,
                "engine": revision.generation_engine,
                "geometry_hash": geometry_hash,
            },
            org_id=job.org_id,
            file_hash=geometry_hash,
        )
        await session.commit()
    logger.info("Generated design %s revision %d", project_ulid, revision_no)
    return result
