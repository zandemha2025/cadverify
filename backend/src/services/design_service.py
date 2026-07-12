"""Org-scoped Design Studio lifecycle and artifact storage."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import BinaryIO, Literal

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery, resolve_org
from src.auth.require_api_key import AuthedUser
from src.db.models import DesignProject, DesignRevision, Job
from src.designs.schema import DesignPlan, validate_design_plan
from src.services.audit_service import emit_event

DESIGN_BLOB_DIR = "/data/blobs/designs"


class DesignQueueUnavailableError(RuntimeError):
    """Raised after accepted rows are durably marked failed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _design_store():
    import os

    from src.storage import get_object_store

    return get_object_store(
        "designs",
        default_root=os.getenv("DESIGN_BLOB_DIR", DESIGN_BLOB_DIR),
    )


def artifact_prefix(org_id: str, project_ulid: str, revision_no: int) -> str:
    if not re.fullmatch(r"[0-9A-Za-z]{26}", project_ulid):
        raise ValueError("invalid design id")
    if not re.fullmatch(r"[0-9A-Za-z]{26}", org_id):
        raise ValueError("invalid organization id")
    if revision_no < 1:
        raise ValueError("invalid design revision")
    return f"{org_id}/{project_ulid}/revisions/{revision_no}"


def serialize_revision(project: DesignProject, revision: DesignRevision) -> dict:
    ready = revision.status == "ready"
    base = f"/api/v1/designs/{project.ulid}/revisions/{revision.revision_no}"
    return {
        "id": revision.ulid,
        "number": revision.revision_no,
        "status": revision.status,
        "plan": revision.operation_plan_json,
        "design_note": revision.design_note,
        "generation_engine": revision.generation_engine,
        "geometry_hash": revision.geometry_hash,
        "geometry": revision.geometry_metadata_json,
        "step_size_bytes": revision.step_size_bytes,
        "stl_size_bytes": revision.stl_size_bytes,
        "error": (
            {
                "code": revision.error_code,
                "message": revision.error_detail,
            }
            if revision.error_code
            else None
        ),
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "started_at": revision.started_at.isoformat() if revision.started_at else None,
        "completed_at": revision.completed_at.isoformat() if revision.completed_at else None,
        "links": {
            "preview": f"{base}/preview.stl" if ready else None,
            "download_step": f"{base}/download.step" if ready else None,
            "verify": (
                f"/verify?design={project.ulid}&revision={revision.revision_no}"
                if ready
                else None
            ),
        },
    }


def serialize_design(
    project: DesignProject,
    revision: DesignRevision | None,
) -> dict:
    ready = bool(revision and revision.status == "ready")
    return {
        "id": project.ulid,
        "name": project.name,
        "status": project.status,
        "source_kind": project.source_kind,
        "current_revision": project.current_revision,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "revision": serialize_revision(project, revision) if revision else None,
        "links": {
            "self": f"/api/v1/designs/{project.ulid}",
            "preview": f"/api/v1/designs/{project.ulid}/preview.stl" if ready else None,
            "download_step": f"/api/v1/designs/{project.ulid}/download.step" if ready else None,
            "verify": f"/verify?design={project.ulid}" if ready else None,
        },
    }


async def _current_pair_for_user(
    session: AsyncSession,
    project_ulid: str,
    user_id: int,
) -> tuple[DesignProject, DesignRevision] | None:
    row = (
        await session.execute(
            select(DesignProject, DesignRevision)
            .join(
                DesignRevision,
                and_(
                    DesignRevision.design_id == DesignProject.id,
                    DesignRevision.revision_no == DesignProject.current_revision,
                ),
            )
            .where(
                DesignProject.ulid == project_ulid,
                DesignProject.org_id == caller_org_subquery(user_id),
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def list_designs(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = 50,
) -> list[tuple[DesignProject, DesignRevision]]:
    rows = (
        await session.execute(
            select(DesignProject, DesignRevision)
            .join(
                DesignRevision,
                and_(
                    DesignRevision.design_id == DesignProject.id,
                    DesignRevision.revision_no == DesignProject.current_revision,
                ),
            )
            .where(
                DesignProject.org_id == caller_org_subquery(user_id),
                DesignProject.status != "archived",
            )
            .order_by(DesignProject.updated_at.desc(), DesignProject.id.desc())
            .limit(max(1, min(limit, 100)))
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def get_design(
    session: AsyncSession,
    project_ulid: str,
    user_id: int,
) -> tuple[DesignProject, DesignRevision] | None:
    return await _current_pair_for_user(session, project_ulid, user_id)


async def list_revisions(
    session: AsyncSession,
    project_ulid: str,
    user_id: int,
) -> tuple[DesignProject, list[DesignRevision]] | None:
    project = (
        await session.execute(
            select(DesignProject).where(
                DesignProject.ulid == project_ulid,
                DesignProject.org_id == caller_org_subquery(user_id),
            )
        )
    ).scalars().first()
    if project is None:
        return None
    revisions = list(
        (
            await session.execute(
                select(DesignRevision)
                .where(
                    DesignRevision.design_id == project.id,
                    DesignRevision.org_id == project.org_id,
                )
                .order_by(DesignRevision.revision_no.desc())
            )
        ).scalars().all()
    )
    return project, revisions


async def get_revision(
    session: AsyncSession,
    project_ulid: str,
    revision_no: int,
    user_id: int,
) -> tuple[DesignProject, DesignRevision] | None:
    row = (
        await session.execute(
            select(DesignProject, DesignRevision)
            .join(DesignRevision, DesignRevision.design_id == DesignProject.id)
            .where(
                DesignProject.ulid == project_ulid,
                DesignProject.org_id == caller_org_subquery(user_id),
                DesignRevision.org_id == DesignProject.org_id,
                DesignRevision.revision_no == revision_no,
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


def _clean_name(value: str) -> str:
    name = " ".join(value.split()).strip()
    if not name:
        raise ValueError("Design name is required")
    return name[:120]


def _clean_note(value: str | None) -> str | None:
    note = (value or "").strip()
    return note[:1000] if note else None


async def _enqueue(job: Job) -> None:
    from src.jobs.arq_backend import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job(
        "run_design_generation_job",
        job.ulid,
        _job_id=f"design_{job.ulid}",
    )


async def _mark_enqueue_failed(
    session: AsyncSession,
    project: DesignProject,
    revision: DesignRevision,
    job: Job,
    actor_id: int,
) -> None:
    now = _now()
    project.status = "failed"
    project.updated_at = now
    revision.status = "failed"
    revision.error_code = "DESIGN_ENQUEUE_FAILED"
    revision.error_detail = "Generation could not be scheduled. Retry this revision."
    revision.completed_at = now
    job.status = "failed"
    job.result_json = {"code": "DESIGN_ENQUEUE_FAILED"}
    job.completed_at = now
    await emit_event(
        session,
        actor_id=actor_id,
        action="design.generation_failed",
        resource_type="design",
        resource_id=project.ulid,
        detail={"revision": revision.revision_no, "code": "DESIGN_ENQUEUE_FAILED"},
        org_id=project.org_id,
    )
    await session.commit()


async def create_design(
    session: AsyncSession,
    user: AuthedUser,
    *,
    name: str,
    plan: DesignPlan,
    design_note: str | None,
) -> tuple[DesignProject, DesignRevision, Job]:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    validated = validate_design_plan(plan)
    project = DesignProject(
        ulid=str(ULID()),
        org_id=org_id,
        created_by=user.user_id,
        name=_clean_name(name),
        status="generating",
        source_kind="template",
        current_revision=1,
    )
    session.add(project)
    await session.flush()
    revision = DesignRevision(
        ulid=str(ULID()),
        design_id=project.id,
        org_id=org_id,
        created_by=user.user_id,
        revision_no=1,
        status="queued",
        operation_plan_json=validated.model_dump(mode="json"),
        design_note=_clean_note(design_note),
        generation_engine="proofshape-occ-v1",
    )
    job = Job(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=org_id,
        job_type="design_generation",
        status="queued",
        params_json={"revision_ulid": revision.ulid},
    )
    session.add(revision)
    session.add(job)
    await emit_event(
        session,
        actor_id=user.user_id,
        action="design.created",
        resource_type="design",
        resource_id=project.ulid,
        detail={"revision": 1, "kind": validated.kind},
        org_id=org_id,
    )
    await emit_event(
        session,
        actor_id=user.user_id,
        action="design.generation_requested",
        resource_type="design_revision",
        resource_id=revision.ulid,
        detail={"design_id": project.ulid, "revision": 1},
        org_id=org_id,
    )
    # The worker must never race an uncommitted job/revision row.
    await session.commit()
    try:
        await _enqueue(job)
    except Exception as exc:
        await _mark_enqueue_failed(session, project, revision, job, user.user_id)
        raise DesignQueueUnavailableError("design generation queue unavailable") from exc
    return project, revision, job


async def create_revision(
    session: AsyncSession,
    user: AuthedUser,
    *,
    project_ulid: str,
    plan: DesignPlan,
    design_note: str | None,
) -> tuple[DesignProject, DesignRevision, Job]:
    project = (
        await session.execute(
            select(DesignProject)
            .where(
                DesignProject.ulid == project_ulid,
                DesignProject.org_id == caller_org_subquery(user.user_id),
            )
            .with_for_update()
        )
    ).scalars().first()
    if project is None or project.status == "archived":
        raise HTTPException(status_code=404, detail="Design not found")
    current = (
        await session.execute(
            select(DesignRevision).where(
                DesignRevision.design_id == project.id,
                DesignRevision.revision_no == project.current_revision,
            )
        )
    ).scalars().first()
    if current and current.status in {"queued", "generating"}:
        raise HTTPException(status_code=409, detail="The current revision is still generating")

    validated = validate_design_plan(plan)
    revision_no = project.current_revision + 1
    project.current_revision = revision_no
    project.status = "generating"
    project.updated_at = _now()
    revision = DesignRevision(
        ulid=str(ULID()),
        design_id=project.id,
        org_id=project.org_id,
        created_by=user.user_id,
        revision_no=revision_no,
        status="queued",
        operation_plan_json=validated.model_dump(mode="json"),
        design_note=_clean_note(design_note),
        generation_engine="proofshape-occ-v1",
    )
    job = Job(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=project.org_id,
        job_type="design_generation",
        status="queued",
        params_json={"revision_ulid": revision.ulid},
    )
    session.add(revision)
    session.add(job)
    await emit_event(
        session,
        actor_id=user.user_id,
        action="design.generation_requested",
        resource_type="design_revision",
        resource_id=revision.ulid,
        detail={"design_id": project.ulid, "revision": revision_no},
        org_id=project.org_id,
    )
    await session.commit()
    try:
        await _enqueue(job)
    except Exception as exc:
        await _mark_enqueue_failed(session, project, revision, job, user.user_id)
        raise DesignQueueUnavailableError("design generation queue unavailable") from exc
    return project, revision, job


async def archive_design(
    session: AsyncSession,
    project_ulid: str,
    user: AuthedUser,
) -> None:
    pair = await _current_pair_for_user(session, project_ulid, user.user_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="Design not found")
    project, revision = pair
    if revision.status in {"queued", "generating"}:
        raise HTTPException(status_code=409, detail="A generating design cannot be archived")
    project.status = "archived"
    project.updated_at = _now()
    await emit_event(
        session,
        actor_id=user.user_id,
        action="design.archived",
        resource_type="design",
        resource_id=project.ulid,
        detail={"revision": project.current_revision},
        org_id=project.org_id,
    )
    await session.commit()


async def open_artifact(
    session: AsyncSession,
    project_ulid: str,
    user_id: int,
    *,
    kind: Literal["step", "stl"],
    revision_no: int | None = None,
) -> tuple[DesignProject, DesignRevision, BinaryIO]:
    pair = (
        await get_revision(session, project_ulid, revision_no, user_id)
        if revision_no is not None
        else await _current_pair_for_user(session, project_ulid, user_id)
    )
    if pair is None:
        raise HTTPException(status_code=404, detail="Design not found")
    project, revision = pair
    if revision.status != "ready":
        raise HTTPException(status_code=409, detail="Design artifact is not ready")
    key = revision.step_object_key if kind == "step" else revision.stl_object_key
    if not key:
        raise HTTPException(status_code=409, detail="Design artifact is unavailable")
    # This route performs no mutation. End the read transaction before opening a
    # potentially slow object stream so a large customer download cannot pin a
    # Postgres connection for its entire duration. expire_on_commit=False keeps
    # the already-loaded project/revision metadata available to the response.
    await session.commit()
    from src.storage import ObjectNotFoundError

    try:
        stream = await asyncio.to_thread(_design_store().open, key)
    except ObjectNotFoundError:
        raise HTTPException(status_code=410, detail="Design artifact is no longer available")
    return project, revision, stream
