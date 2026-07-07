"""Offline integration connector apparatus.

These routes are deliberately file-fed. They let an enterprise dry-run SAP/PLM
or quote/actual CSV exports through CadVerify's real parsers, record durable run
evidence, and optionally execute the matching import without pretending live
credentials exist.
"""
from __future__ import annotations

import os
from typing import AsyncIterator, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import integration_service as svc

router = APIRouter(tags=["integrations"])

_CHUNK = 1024 * 1024


def _import_cap_bytes() -> int:
    try:
        mb = int(os.getenv("INTEGRATION_IMPORT_MAX_MB", "10"))
    except ValueError:
        mb = 10
    return max(1, mb) * 1024 * 1024


async def _upload_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        yield chunk


async def _read_capped_chunks(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    buf = bytearray()
    async for chunk in chunks:
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"CSV exceeds {limit // (1024 * 1024)}MB integration limit",
            )
    if not buf:
        raise HTTPException(status_code=400, detail="Empty CSV upload")
    return bytes(buf)


async def _require_org(session: AsyncSession, user: AuthedUser) -> str:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


@router.get("/connectors")
@limiter.limit("120/hour;1000/day")
async def list_connectors(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    return {"connectors": svc.list_connectors()}


@router.post("/runs")
@limiter.limit("30/hour;100/day")
async def create_run(
    request: Request,
    response: Response,
    connector_id: str = Form(...),
    mode: str = Form(svc.MODE_DRY_RUN),
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Dry-run or import an offline connector CSV and persist the run ledger.

    ``mode=dry_run`` parses only. ``mode=import`` delegates to the existing
    manifest or ground-truth importer and is blocked when the global write
    kill-switch is closed. Raw CSV bytes are hashed and counted, not stored.
    """
    if mode == svc.MODE_IMPORT:
        require_kill_switch_open()
    elif mode != svc.MODE_DRY_RUN:
        raise HTTPException(status_code=400, detail="mode must be dry_run or import")

    org_id = await _require_org(session, user)
    raw = await _read_capped_chunks(_upload_chunks(file), _import_cap_bytes())
    run = await svc.run_connector_csv(
        session,
        org_id=org_id,
        user_id=user.user_id,
        connector_id=connector_id,
        raw=raw,
        filename=file.filename,
        mode=mode,
    )
    await session.commit()
    return {"run": svc.serialize_run(run)}


@router.get("/runs")
@limiter.limit("120/hour;1000/day")
async def list_runs(
    request: Request,
    response: Response,
    cursor: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    connector_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _require_org(session, user)
    rows, has_more = await svc.list_runs(
        session,
        org_id=org_id,
        limit=limit,
        cursor=cursor,
        connector_id=connector_id,
        status=status,
    )
    next_cursor = str(rows[-1].id) if has_more and rows else None
    return {
        "runs": [svc.serialize_run(row) for row in rows],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.get("/runs/{run_id}")
@limiter.limit("120/hour;1000/day")
async def get_run(
    run_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _require_org(session, user)
    row = await svc.get_run(session, org_id=org_id, run_id=run_id)
    return svc.serialize_run(row)
