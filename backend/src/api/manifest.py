"""Parts-manifest ingest API (Aramco GAP 3) — declared inventory onboarding.

The org-scoped home for a customer's DECLARED inventory: they upload a parts
manifest (CSV exported from SAP/Excel — part numbers + demand/program/material
metadata, usually WITHOUT geometry) and immediately see it organized, plus an
honest geometry-coverage headline.

The deliberate sibling of the ground-truth CSV import surface
(``src/api/groundtruth.py``): same streaming size cap (413 without buffering),
same org boundary (``_require_org`` → 403 when the caller has no org), same
role gates (``analyst`` to write, ``viewer`` to read), same kill-switch gate on
the mutating endpoint, and the same partial-success import summary shape.

Tenancy: ORG-SCOPED via ``resolve_org``. Every read/write is scoped to the
caller's org; one org's manifest never leaks into another's list or coverage.
"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
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
from src.services import manifest_service as svc

logger = logging.getLogger("cadverify.manifest")

router = APIRouter(tags=["manifest"])

_CHUNK = 1024 * 1024  # 1 MiB


def _import_cap_bytes() -> int:
    """Bulk-import size cap. Read lazily so tests can override via env.

    A manifest is text (part numbers + metadata), not meshes — a small cap is
    honest here. Mirrors ``groundtruth`` (``MANIFEST_IMPORT_MAX_MB``, default 10).
    """
    try:
        mb = int(os.getenv("MANIFEST_IMPORT_MAX_MB", "10"))
    except ValueError:
        mb = 10
    return max(1, mb) * 1024 * 1024


async def _read_capped_chunks(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    """Stream chunks, rejecting anything over ``limit`` WITHOUT buffering the
    whole payload — mirrors ``groundtruth._read_capped_chunks``. Raises 413 as
    soon as the running total crosses the cap; 400 if empty.
    """
    buf = bytearray()
    async for chunk in chunks:
        if not chunk:
            continue
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"CSV exceeds {limit // (1024 * 1024)}MB import limit",
            )
    if not buf:
        raise HTTPException(status_code=400, detail="Empty CSV upload")
    return bytes(buf)


async def _upload_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        yield chunk


async def _require_org(session: AsyncSession, user: AuthedUser) -> str:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


@router.post("/import", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def import_manifest(
    request: Request,
    response: Response,
    file: Optional[UploadFile] = File(None),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Bulk-import an org's declared parts manifest from a CSV.

    Accepts either a multipart ``file`` upload OR a raw ``text/csv`` request body.
    Streams with an honest size cap (``MANIFEST_IMPORT_MAX_MB``, 413 on overflow)
    — never buffered unbounded. Parses STRICTLY (see
    ``manifest_service.parse_manifest_csv``): every valid declared row is UPSERTED
    org-scoped on ``(org_id, part_id)`` (last-write-wins — a re-import UPDATES the
    existing row); every malformed row is reported, never coerced.

    Partial success is honest: a file with some bad rows returns 200 with the good
    rows imported/updated and per-line errors listed. A fully-invalid / empty file
    still returns 200 with ``imported=0`` and the errors — the endpoint reports, it
    does not crash. Columns are documented at ``GET /import/template``.

    Returns ``{imported, updated, skipped, total, errors:[{line, reason}]}``.
    """
    org_id = await _require_org(session, user)

    limit = _import_cap_bytes()
    if file is not None:
        raw = await _read_capped_chunks(_upload_chunks(file), limit)
    else:
        raw = await _read_capped_chunks(request.stream(), limit)

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400, detail="CSV must be UTF-8 encoded text."
        )

    rows, parse_errors = svc.parse_manifest_csv(text)
    summary = await svc.import_manifest(session, org_id, user.user_id, rows)
    await session.commit()

    errors = parse_errors + summary["errors"]
    return {
        "imported": summary["imported"],
        "updated": summary["updated"],
        "skipped": summary["skipped"] + len(parse_errors),
        "total": summary["total"] + len(parse_errors),
        "errors": errors,
    }


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_manifest(
    request: Request,
    response: Response,
    cursor: Optional[str] = None,
    limit: int = 100,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller org's declared manifest — keyset-paginated (``part_id`` ASC).

    Returns ``{parts, next_cursor}``; ``next_cursor`` is None only on the final
    page. Pass it back as ``cursor`` to walk the next page. ``limit`` is bounded.
    """
    org_id = await _require_org(session, user)
    return await svc.list_manifest(session, org_id, cursor=cursor, limit=limit)


@router.get("/coverage")
@limiter.limit("120/hour;1000/day")
async def manifest_coverage(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The Aramco headline: total declared parts, a scalable ``by_program`` rollup,
    and an honest geometry-coverage count (``with_geometry`` / ``without_geometry``
    by exact normalized-stem match against uploaded analyses in the same org)."""
    org_id = await _require_org(session, user)
    return await svc.manifest_coverage(session, org_id)


@router.get("/import/template", response_class=PlainTextResponse)
@limiter.limit("120/hour;1000/day")
async def import_template(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """The exact CSV header a customer must produce for a manifest import.

    Required column: ``part_id``. Optional declared metadata: ``description``,
    ``material_class`` (must be one of the known cost-engine classes if present),
    ``program``, ``parent_assembly``, ``units_per_parent``, ``annual_volume``,
    ``quantity``, ``region``, ``source``, ``notes``.
    """
    return svc.MANIFEST_HEADER + "\n" + svc._example_row() + "\n"
