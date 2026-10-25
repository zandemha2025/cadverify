"""A part's revisions (src.services.part_revision_service).

* ``GET /parts/{mesh_hash}/revisions`` -> ``{mesh_hash, revision_of, next}``;
  each linked side is ``{mesh_hash, filename, record_id, problem, at}`` or null.
* ``PUT /parts/{mesh_hash}/revision-of`` ``{from_mesh_hash, problem?}`` records
  this part as the next revision of ``from_mesh_hash`` (the file uploaded from
  that part's problem card). The same writer check as the other parts writes
  (platform analyst and org member, ``require_org_writer``); both parts must be
  saved parts of the caller's active organization, else 404. Never a check.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role, require_org_writer
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import part_revision_service as svc

router = APIRouter(tags=["parts"])


class RevisionOfBody(BaseModel):
    from_mesh_hash: str = Field(min_length=64, max_length=64)
    problem: Optional[str] = Field(default=None, max_length=64)


def _org(ctx: OrgAuthContext) -> str:
    if not ctx.org_id:
        raise HTTPException(status_code=404, detail="No such part in your organization.")
    return ctx.org_id


@router.get("/{mesh_hash}/revisions")
@limiter.limit("600/hour;5000/day")
async def part_revisions(
    request: Request,
    response: Response,
    mesh_hash: str,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The part this one revises, and the part that revises it, when linked."""
    try:
        return await svc.revisions(session, _org(ctx), mesh_hash)
    except svc.RevisionLinkError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc


@router.put("/{mesh_hash}/revision-of", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;600/day")
async def set_revision_of(
    request: Request,
    response: Response,
    mesh_hash: str,
    body: RevisionOfBody,
    _writer: AuthedUser = Depends(require_org_writer),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    session: AsyncSession = Depends(get_db_session),
):
    """Record this part as the next revision of ``from_mesh_hash``."""
    try:
        return await svc.link_revision(session, _org(ctx), ctx.user_id, mesh_hash, body.from_mesh_hash, body.problem)
    except svc.RevisionLinkError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
