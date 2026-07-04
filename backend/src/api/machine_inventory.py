"""Machine-inventory API (verification-thesis crux) — org-owned machine registry.

The org-scoped home for a customer's DECLARED owned machines and their real
capability fields, plus the shop-level secondary-op set. The deliberate sibling
of the parts-manifest ingest surface (``src/api/manifest.py``): same streaming
size cap (413 without buffering), same org boundary (``_require_org`` → 403 when
the caller has no org), same role gates (``analyst`` to write, ``viewer`` to
read), same kill-switch gate on the mutating endpoints, and the same
partial-success import summary shape.

Tenancy: ORG-SCOPED via ``resolve_org``. Every read/write is scoped to the
caller's org; one org's machines never leak into another's list or hydration.

Honesty: every capability is a USER declaration (``provenance: "user"``), never a
measurement of the machine. Malformed inputs are reported (400 / per-line), never
coerced. Absent inventory → empty responses, byte-identical to the feature unused.
"""
from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator, Optional

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
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import machine_inventory_service as svc

logger = logging.getLogger("cadverify.machine_inventory")

router = APIRouter(tags=["machine-inventory"])

_CHUNK = 1024 * 1024  # 1 MiB


# ── request bodies ────────────────────────────────────────────────────────────
class MachineBody(BaseModel):
    name: Optional[str] = None
    process: str
    count: Optional[int] = None
    max_workpiece_kg: Optional[float] = None
    hourly_rate_usd: Optional[float] = None
    capital_frac: Optional[float] = None
    capabilities: Optional[dict] = None
    materials: Optional[list] = None
    material_thickness_map: Optional[dict] = None
    notes: Optional[str] = None


class MachinePatchBody(BaseModel):
    name: Optional[str] = None
    process: Optional[str] = None
    count: Optional[int] = None
    max_workpiece_kg: Optional[float] = None
    hourly_rate_usd: Optional[float] = None
    capital_frac: Optional[float] = None
    capabilities: Optional[dict] = None
    materials: Optional[list] = None
    material_thickness_map: Optional[dict] = None
    notes: Optional[str] = None


class ShopCapabilitiesBody(BaseModel):
    ops: dict = {}


# ── streaming import helpers (mirror manifest.py) ─────────────────────────────
def _import_cap_bytes() -> int:
    try:
        mb = int(os.getenv("MACHINE_IMPORT_MAX_MB", "10"))
    except ValueError:
        mb = 10
    return max(1, mb) * 1024 * 1024


async def _read_capped_chunks(chunks: AsyncIterator[bytes], limit: int) -> bytes:
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


# ── static / prefix routes FIRST (before the /{id} path param) ────────────────
@router.get("/catalog")
@limiter.limit("120/hour;1000/day")
async def catalog(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """Static ``MachineProfile`` reference options as editable prefill payloads.

    Each is a TEMPLATE (``provenance: "catalog_template"``) to seed a declaration —
    the org edits it to its machine's real specs before saving.
    """
    return {"catalog": svc.catalog_options()}


@router.get("/import/template", response_class=PlainTextResponse)
@limiter.limit("120/hour;1000/day")
async def import_template(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """The exact CSV header a customer produces for a machine-inventory import.

    Required column: ``process``. Optional: ``name``, ``count``,
    ``max_workpiece_kg``, ``hourly_rate_usd``, ``capital_frac``, ``materials``
    (pipe-separated), ``material_thickness_map`` (JSON), ``capabilities`` (JSON of
    the per-family scalars), ``notes``.
    """
    return svc.MACHINE_HEADER + "\n" + svc._example_row() + "\n"


@router.get("/shop-capabilities")
@limiter.limit("120/hour;1000/day")
async def get_shop_capabilities(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The org's shop-level secondary-op set (empty ``ops`` when unset)."""
    org_id = await _require_org(session, user)
    row = await svc.get_shop_capabilities(session, org_id)
    return svc.serialize_shop_capabilities(row)


@router.put("/shop-capabilities", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;300/day")
async def put_shop_capabilities(
    request: Request,
    response: Response,
    body: ShopCapabilitiesBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Declare (upsert) the org's shop-level secondary ops. Idempotent per org.

    ``ops`` = ``{op: True | {size/temp limits}}``. A malformed op (non-bool /
    non-limits value, or a non-positive limit) is a 400 — reported, never coerced.
    """
    org_id = await _require_org(session, user)
    try:
        row = await svc.upsert_shop_capabilities(
            session, org_id, body.ops, created_by=user.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    return svc.serialize_shop_capabilities(row)


@router.post("/import", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def import_machines(
    request: Request,
    response: Response,
    file: Optional[UploadFile] = File(None),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Bulk-import an org's owned machines from a CSV.

    Accepts a multipart ``file`` OR a raw ``text/csv`` body. Streams with an honest
    size cap (413 on overflow). Parses STRICTLY (see
    ``machine_inventory_service.parse_machine_csv``): every valid row is INSERTED
    (machines have no natural key → append, not upsert); every malformed row is
    reported, never coerced. Partial success is honest — a file with some bad rows
    returns 200 with the good rows imported and per-line errors listed.

    Returns ``{imported, skipped, total, errors:[{line, reason}]}``.
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

    rows, parse_errors = svc.parse_machine_csv(text)
    summary = await svc.import_machines(session, org_id, user.user_id, rows)
    await session.commit()

    errors = parse_errors + summary["errors"]
    return {
        "imported": summary["imported"],
        "skipped": summary["skipped"] + len(parse_errors),
        "total": summary["total"] + len(parse_errors),
        "errors": errors,
    }


# ── collection routes ─────────────────────────────────────────────────────────
@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;600/day")
async def create_machine(
    request: Request,
    response: Response,
    body: MachineBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Declare one owned machine. A malformed capability field is a 400 (reported,
    never coerced). The response is always ``provenance: "user"``."""
    org_id = await _require_org(session, user)
    try:
        row = await svc.create_machine(
            session, org_id, body.model_dump(), created_by=user.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    response.status_code = 201
    return svc.machine_to_public(row)


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_machines(
    request: Request,
    response: Response,
    cursor: Optional[str] = None,
    limit: int = 100,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller org's owned machines — keyset-paginated (``id`` ASC)."""
    org_id = await _require_org(session, user)
    return await svc.list_machines(session, org_id, cursor=cursor, limit=limit)


# ── item routes (path param LAST so /catalog etc. are not captured) ───────────
@router.get("/{machine_id}")
@limiter.limit("120/hour;1000/day")
async def get_machine(
    request: Request,
    response: Response,
    machine_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """One owned machine by its public id (org-scoped), or 404."""
    org_id = await _require_org(session, user)
    row = await svc.get_machine(session, org_id, machine_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such machine in org")
    return svc.machine_to_public(row)


@router.patch("/{machine_id}", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;600/day")
async def patch_machine(
    request: Request,
    response: Response,
    machine_id: str,
    body: MachinePatchBody,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Patch a machine's fields (org-scoped). Only supplied keys change; the merged
    result is re-validated. 404 when no such machine; 400 on a malformed field."""
    org_id = await _require_org(session, user)
    fields: dict[str, Any] = body.model_dump(exclude_unset=True)
    try:
        row = await svc.update_machine(session, org_id, machine_id, fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if row is None:
        raise HTTPException(status_code=404, detail="no such machine in org")
    await session.commit()
    return svc.machine_to_public(row)


@router.delete("/{machine_id}", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;600/day")
async def delete_machine(
    request: Request,
    response: Response,
    machine_id: str,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete one owned machine (org-scoped). 404 when no such machine."""
    org_id = await _require_org(session, user)
    removed = await svc.delete_machine(session, org_id, machine_id)
    if not removed:
        raise HTTPException(status_code=404, detail="no such machine in org")
    await session.commit()
    return {"deleted": True, "id": machine_id}
