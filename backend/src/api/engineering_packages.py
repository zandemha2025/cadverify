"""Organization-scoped engineering packets. All writes create a new version."""
import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import engineering_package_service as svc
from src.storage import ObjectNotFoundError

router = APIRouter(tags=["engineering-packages"])


@router.get("")
@limiter.limit("240/hour;2000/day")
async def list_packages(request: Request, response: Response,
    mesh_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
    series_id: str | None = Query(None, max_length=100), cursor: str | None = Query(None, max_length=100),
    blocker_kind: str | None = Query(None, max_length=100), owner: str | None = Query(None, max_length=200),
    limit: int = Query(25, ge=1, le=100), user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session, scope="function")):
    org = await svc.require_org(session, user)
    return await svc.list_packages(session, org, mesh_hash=mesh_hash, series_id=series_id, cursor=cursor, limit=limit, blocker_kind=blocker_kind, owner=owner)


@router.get("/queue")
@limiter.limit("240/hour;2000/day")
async def blocker_queue(request: Request, response: Response,
    limit: int = Query(50, ge=1, le=100), user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session, scope="function")):
    org = await svc.require_org(session, user)
    # Aggregate latest snapshots in SQL; never load the organization's raw
    # geometry, documents or all package versions into the application process.
    rows = (await session.execute(text("""
        SELECT blocker->>'kind' AS kind, blocker->>'owner' AS owner,
               count(*) AS actions, count(DISTINCT p.series_id) AS packages
        FROM engineering_packages p
        CROSS JOIN LATERAL jsonb_array_elements(p.payload->'evaluation'->'blockers') blocker
        WHERE p.org_id = :org AND p.is_latest
        GROUP BY blocker->>'kind', blocker->>'owner'
        ORDER BY count(*) DESC, blocker->>'kind', blocker->>'owner'
        LIMIT :limit
    """), {"org": org, "limit": limit + 1})).mappings().all()
    return {"groups": [dict(r) for r in rows[:limit]], "truncated": len(rows) > limit,
            "basis": "Latest saved package assessments; grouping does not grant evidence applicability across parts."}


@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("240/hour;1000/day")
async def write_package(request: Request, response: Response, body: svc.WritePackage,
    user: AuthedUser = Depends(require_role(Role.analyst)), session: AsyncSession = Depends(get_db_session, scope="function")):
    try:
        row = await svc.save_package(session, user, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await session.commit()
    response.status_code = 201
    return svc.serialize_package(row)


@router.post("/documents", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;500/day")
async def upload_document(request: Request, response: Response, file: UploadFile = File(...),
    user: AuthedUser = Depends(require_role(Role.analyst)), session: AsyncSession = Depends(get_db_session, scope="function")):
    org = await svc.require_org(session, user)
    data = await file.read(20 * 1024 * 1024 + 1)
    return await svc.store_document(org, file.filename or "document.txt", data)


@router.post("/import-characteristics")
@limiter.limit("120/hour;500/day")
async def import_characteristics(request: Request, response: Response, file: UploadFile = File(...),
    user: AuthedUser = Depends(require_role(Role.analyst))):
    data = await file.read(2 * 1024 * 1024 + 1)
    try:
        rows = await asyncio.to_thread(svc.import_characteristics, data, file.filename or "")
    except (ValueError, UnicodeError, ValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"requirements": rows, "review_required": True,
            "coverage": "Only supplied characteristics were imported. Confirm source mappings and omissions."}


@router.get("/{package_id}")
@limiter.limit("240/hour;2000/day")
async def get_package(package_id: str, request: Request, response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)), session: AsyncSession = Depends(get_db_session, scope="function")):
    row = await svc.get_package(session, await svc.require_org(session, user), package_id)
    return {**svc.serialize_package(row), "current_assessment": await svc.current_assessment(session, row)}


@router.get("/{package_id}/documents/{source_id}")
@limiter.limit("120/hour;1000/day")
async def download_document(package_id: str, source_id: str, request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)), session: AsyncSession = Depends(get_db_session, scope="function")):
    row = await svc.get_package(session, await svc.require_org(session, user), package_id)
    source = next((s for s in row.payload["document"]["sources"] if s["id"] == source_id), None)
    if not source or not source["sha256"]:
        raise HTTPException(404, "Original document not attached")
    try:
        data = await asyncio.to_thread(svc.document_store().get, svc.document_key(row.org_id, source["sha256"]))
    except ObjectNotFoundError as exc:
        raise HTTPException(404, "Original document is unavailable") from exc
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(source["filename"] or source["name"], safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("/{package_id}/export.{format}")
@limiter.limit("120/hour;1000/day")
async def export_package(package_id: str, format: str, request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)), session: AsyncSession = Depends(get_db_session, scope="function")):
    row = await svc.get_package(session, await svc.require_org(session, user), package_id)
    if format == "json":
        data, mime = json.dumps(svc.serialize_package(row), indent=2), "application/json"
    elif format == "csv":
        data, mime = svc.export_characteristics(row.payload), "text/csv"
    elif format == "html":
        data, mime = svc.packet_html(row), "text/html"
    elif format == "pdf":
        from src.services.cost_pdf_service import generate_html_pdf
        data = await generate_html_pdf(svc.packet_html(row))
        mime = "application/pdf"
    else:
        raise HTTPException(404, "Use JSON, CSV, HTML or PDF")
    return Response(data, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="engineering-package-{row.id}.{format}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
