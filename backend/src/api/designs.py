"""ProofShape Design Studio API.

Every read and write is scoped to the caller's organization. Generation is
asynchronous and returns immutable STEP/STL revision artifacts; clients poll the
design or its job rather than holding an API request open around OpenCASCADE.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import (
    OrgRole,
    Role,
    require_role,
    require_role_and_org_role,
)
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.designs.schema import DesignPlan
from src.services import design_service as svc
from src.services.release_fault_injection import (
    DESIGN_FAULT_MODES,
    requested_release_fault,
)

router = APIRouter(tags=["designs"])
require_design_mutation = require_role_and_org_role(Role.analyst, OrgRole.member)


class CreateDesignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    design_note: Annotated[str | None, Field(max_length=1000)] = None
    plan: DesignPlan


class CreateRevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_note: Annotated[str | None, Field(max_length=1000)] = None
    plan: DesignPlan


class InterpretDesignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: Annotated[str, Field(min_length=1, max_length=500)]


def _filename(name: str, suffix: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "proofshape-design"
    return f"{stem[:80]}{suffix}"


def _stream_body(stream):
    try:
        while chunk := stream.read(256 * 1024):
            yield chunk
    finally:
        stream.close()


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_designs(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    rows = await svc.list_designs(session, user.user_id, limit=limit)
    return {"designs": [svc.serialize_design(project, revision) for project, revision in rows]}


@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def create_design(
    request: Request,
    response: Response,
    body: CreateDesignBody,
    user: AuthedUser = Depends(require_design_mutation),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        release_test_fault = requested_release_fault(request, DESIGN_FAULT_MODES)
        project, revision, job = await svc.create_design(
            session,
            user,
            name=body.name,
            plan=body.plan,
            design_note=body.design_note,
            release_test_fault=release_test_fault,
        )
    except svc.DesignQueueUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "DESIGN_ENQUEUE_FAILED",
                    "message": svc.DESIGN_QUEUE_FAILURE_COPY,
                },
                "design": svc.serialize_design(exc.project, exc.revision),
            },
        )
    return JSONResponse(
        status_code=202,
        content={
            "design": svc.serialize_design(project, revision),
            "job_id": job.ulid,
            "poll_url": f"/api/v1/designs/{project.ulid}",
        },
    )


@router.post("/interpret")
@limiter.limit("120/hour;600/day")
async def interpret_design(
    request: Request,
    response: Response,
    body: InterpretDesignBody,
    user: AuthedUser = Depends(require_design_mutation),
):
    del user
    from src.designs.interpreter import interpret_design_prompt

    return interpret_design_prompt(body.prompt)


@router.get("/{design_id}")
@limiter.limit("120/hour;1000/day")
async def get_design(
    design_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    pair = await svc.get_design(session, design_id, user.user_id)
    if pair is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Design not found")
    return {"design": svc.serialize_design(*pair)}


@router.post("/{design_id}/revisions", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def create_revision(
    design_id: str,
    request: Request,
    response: Response,
    body: CreateRevisionBody,
    user: AuthedUser = Depends(require_design_mutation),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        release_test_fault = requested_release_fault(request, DESIGN_FAULT_MODES)
        project, revision, job = await svc.create_revision(
            session,
            user,
            project_ulid=design_id,
            plan=body.plan,
            design_note=body.design_note,
            release_test_fault=release_test_fault,
        )
    except svc.DesignQueueUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "DESIGN_ENQUEUE_FAILED",
                    "message": svc.DESIGN_QUEUE_FAILURE_COPY,
                },
                "design": svc.serialize_design(exc.project, exc.revision),
            },
        )
    return JSONResponse(
        status_code=202,
        content={
            "design": svc.serialize_design(project, revision),
            "job_id": job.ulid,
            "poll_url": f"/api/v1/designs/{project.ulid}",
        },
    )


@router.get("/{design_id}/revisions")
@limiter.limit("120/hour;1000/day")
async def list_design_revisions(
    design_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    result = await svc.list_revisions(session, design_id, user.user_id)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Design not found")
    project, revisions = result
    return {
        "design_id": project.ulid,
        "current_revision": project.current_revision,
        "revisions": [svc.serialize_revision(project, revision) for revision in revisions],
    }


@router.get("/{design_id}/revisions/{revision_no}")
@limiter.limit("120/hour;1000/day")
async def get_design_revision(
    design_id: str,
    revision_no: int,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    from fastapi import HTTPException

    if revision_no < 1:
        raise HTTPException(status_code=404, detail="Design revision not found")
    pair = await svc.get_revision(session, design_id, revision_no, user.user_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="Design revision not found")
    project, revision = pair
    return {"design_id": project.ulid, "revision": svc.serialize_revision(project, revision)}


@router.delete("/{design_id}", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def archive_design(
    design_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_design_mutation),
    session: AsyncSession = Depends(get_db_session),
):
    await svc.archive_design(session, design_id, user)
    return Response(status_code=204)


@router.get("/{design_id}/preview.stl")
@limiter.limit("120/hour;1000/day")
async def preview_design(
    design_id: str,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    project, _revision, stream = await svc.open_artifact(
        session, design_id, user.user_id, kind="stl"
    )
    return StreamingResponse(
        _stream_body(stream),
        media_type="model/stl",
        headers={"Content-Disposition": f'inline; filename="{_filename(project.name, ".stl")}"'},
    )


@router.get("/{design_id}/download.step")
@limiter.limit("120/hour;1000/day")
async def download_design_step(
    design_id: str,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    project, revision, stream = await svc.open_artifact(
        session, design_id, user.user_id, kind="step"
    )
    return StreamingResponse(
        _stream_body(stream),
        media_type="model/step",
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(project.name, ".step")}"',
            "Cache-Control": "private, no-store",
            "X-Geometry-SHA256": revision.geometry_hash or "",
        },
    )


@router.get("/{design_id}/revisions/{revision_no}/preview.stl")
@limiter.limit("120/hour;1000/day")
async def preview_design_revision(
    design_id: str,
    revision_no: int,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    project, _revision, stream = await svc.open_artifact(
        session,
        design_id,
        user.user_id,
        kind="stl",
        revision_no=revision_no,
    )
    return StreamingResponse(
        _stream_body(stream),
        media_type="model/stl",
        headers={
            "Content-Disposition": (
                f'inline; filename="{_filename(project.name, f"-r{revision_no}.stl")}"'
            )
        },
    )


@router.get("/{design_id}/revisions/{revision_no}/download.step")
@limiter.limit("120/hour;1000/day")
async def download_design_revision_step(
    design_id: str,
    revision_no: int,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    project, revision, stream = await svc.open_artifact(
        session,
        design_id,
        user.user_id,
        kind="step",
        revision_no=revision_no,
    )
    return StreamingResponse(
        _stream_body(stream),
        media_type="model/step",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_filename(project.name, f"-r{revision_no}.step")}"'
            ),
            "Cache-Control": "private, no-store",
            "X-Geometry-SHA256": revision.geometry_hash or "",
        },
    )
