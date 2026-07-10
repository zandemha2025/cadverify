"""BOM / assembly-hierarchy API (customer-context Slice 3 — the rollup surface).

Persists the customer's REAL multi-level parent->child tree and rolls a part's
total up it, so a part's environment and total (handle -> door assembly -> vehicle)
come from the customer's own data and FEED the analysis. Two honest ingest sources
and a read that returns the ancestry chain + rolled-up multiplier + provenance:

  * ``POST /bom/ingest-assembly`` — parse an uploaded STEP/IGES assembly (REUSING
    the ``/validate/assembly`` extraction) and persist its DERIVED edges
    (``source='assembly_step'``). Idempotent per ``(org, assembly_key)``.
  * ``POST /bom/onboard`` — a customer ``parent_ref,child_ref,qty_per_parent`` BOM
    (CSV/JSON). USER-declared; bad rows reported + skipped (``source='bom_csv'``).
  * ``GET /bom/{assembly_key}/ancestry?child_ref=…`` — the child->root chain, the
    rolled-up multiplier, and ``has_tree`` provenance. HONEST when absent: a missing
    tree/part is ``has_tree=false`` + ``rolled_up_multiplier=null`` — never a 500,
    never a fabricated chain.

Tenancy: ORG-SCOPED via ``resolve_org``; every read/write filters by ``org_id`` so
a caller can never touch another org's edges. Writes require ``analyst`` +
kill-switch; reads require ``viewer`` (mirrors ``manifest`` / ``part_context``).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import bom_service as svc

logger = logging.getLogger("cadverify.bom")

router = APIRouter(tags=["bom"])

_CHUNK = 1024 * 1024  # 1 MiB


def _import_cap_bytes() -> int:
    """BOM CSV/JSON size cap (text, not meshes → a small cap is honest)."""
    try:
        mb = int(os.getenv("BOM_IMPORT_MAX_MB", "10"))
    except ValueError:
        mb = 10
    return max(1, mb) * 1024 * 1024


def _assembly_cap_bytes() -> int:
    """STEP/IGES upload cap for assembly ingest."""
    try:
        mb = int(os.getenv("BOM_ASSEMBLY_MAX_MB", "256"))
    except ValueError:
        mb = 256
    return max(1, mb) * 1024 * 1024


async def _require_org(session: AsyncSession, user: AuthedUser) -> str:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds {limit // (1024 * 1024)}MB limit",
            )
    if not buf:
        raise HTTPException(status_code=400, detail="empty upload")
    return bytes(buf)


@router.post("/ingest-assembly", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def ingest_assembly(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    assembly_key: Optional[str] = Query(
        None, description="key to store this tree under (defaults to the filename)"
    ),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Persist the REAL edge tree of an uploaded STEP/IGES assembly.

    Reuses the ``/validate/assembly`` extraction (same OCC parse + security gate +
    pool), then derives + persists the DESIGN-collapsed parent->child edges
    (``qty_per_parent`` = the MEASURED instance count of a child design under one
    parent occurrence). Idempotent per ``(org, assembly_key)`` — a re-ingest
    REPLACES the tree. ``assembly_key`` defaults to the uploaded filename when
    omitted. A single-part / degenerate file persists 0 edges with an honest note
    (nothing to roll up) — never a fabricated hierarchy.

    Returns ``{assembly_key, edges, roots, source}``.
    """
    org_id = await _require_org(session, user)
    data = await _read_capped(file, _assembly_cap_bytes())
    filename = file.filename or "upload.step"
    key = (assembly_key or "").strip() or filename

    # Reuse the live assembly extraction path (security gate + pool + honest 400s).
    from src.api.routes import _extract_assembly_async

    model = await _extract_assembly_async(data, filename)
    summary = await svc.ingest_assembly(session, org_id, key, model)
    await session.commit()
    return summary


@router.post("/onboard", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def onboard_bom(
    request: Request,
    response: Response,
    file: Optional[UploadFile] = File(None),
    assembly_key: Optional[str] = Query(
        None, description="key to store this BOM under (or the upload filename)"
    ),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Onboard a customer BOM (``parent_ref,child_ref,qty_per_parent`` CSV/JSON).

    Accepts a multipart ``file`` upload OR a raw ``text/csv`` / ``application/json``
    body. Parses STRICTLY (``bom_service.parse_bom``): every valid edge is persisted
    (idempotent per ``(org, assembly_key)`` — a re-onboard REPLACES the tree); every
    malformed row is reported and SKIPPED so the batch survives. ``assembly_key`` is
    required (query, form, or the uploaded filename). Contract at
    ``GET /bom/onboard/template``.

    Returns ``{assembly_key, edges, roots, source, skipped, errors:[{line, reason}]}``.
    """
    org_id = await _require_org(session, user)
    limit = _import_cap_bytes()
    content_hint = ""
    key = (assembly_key or "").strip()
    if file is not None:
        raw = await _read_capped(file, limit)
        content_hint = file.filename or ""
        if not key:
            key = (file.filename or "").strip()
    else:
        buf = bytearray()
        async for chunk in request.stream():
            buf.extend(chunk)
            if len(buf) > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"BOM exceeds {limit // (1024 * 1024)}MB limit",
                )
        raw = bytes(buf)
        content_hint = request.headers.get("content-type", "")
    if not raw:
        raise HTTPException(status_code=400, detail="empty BOM upload")
    if not key:
        raise HTTPException(
            status_code=400,
            detail="assembly_key is required (query, form field, or upload filename)",
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="BOM must be UTF-8 encoded text.")

    rows, parse_errors = svc.parse_bom(text, content_hint=content_hint)
    if len(rows) > svc.BOM_MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"BOM of {len(rows)} edges exceeds the {svc.BOM_MAX_ROWS} cap.",
        )
    summary = await svc.ingest_bom_rows(session, org_id, key, rows)
    await session.commit()
    summary["skipped"] = len(parse_errors)
    summary["errors"] = parse_errors
    return summary


@router.get("/onboard/template", response_class=PlainTextResponse)
@limiter.limit("120/hour;1000/day")
async def onboard_template(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """The exact CSV header a customer must produce for a BOM onboard.

    Required: ``parent_ref``, ``child_ref``. Optional: ``qty_per_parent`` (default
    1, positive integer), ``child_name``. One row per parent->child edge; the tree
    is the union of the rows (a shared child under two parents is two rows).
    """
    return svc.BOM_HEADER + "\n" + svc._example_bom_row() + "\n"


@router.get("/{assembly_key}/ancestry")
@limiter.limit("120/hour;1000/day")
async def get_ancestry(
    request: Request,
    response: Response,
    assembly_key: str,
    child_ref: str = Query(..., description="the part/design ref to trace to the root"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The child->root ancestry chain + rolled-up multiplier + provenance.

    HONEST when absent: a missing tree or a ``child_ref`` not in it returns
    ``has_tree=false`` with empty chains and ``rolled_up_multiplier=null`` — never a
    500, never a fabricated ancestry. A shared component returns every distinct
    root-path in ``ancestry_paths`` and the SUMMED multiplier.
    """
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return await svc.get_ancestry(session, org_id, assembly_key, child_ref)


@router.get("/{assembly_key}")
@limiter.limit("120/hour;1000/day")
async def get_tree(
    request: Request,
    response: Response,
    assembly_key: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The persisted edge list (tree) for ``(org, assembly_key)``. Empty ``edges``
    when no tree exists — honest, never a 404-as-error for a legitimately empty
    hierarchy."""
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    edges = await svc.load_edges(session, org_id, assembly_key)
    return {
        "assembly_key": assembly_key,
        "edges": edges,
        "roots": sorted(svc._roots(edges)),
        "has_tree": bool(edges),
    }
