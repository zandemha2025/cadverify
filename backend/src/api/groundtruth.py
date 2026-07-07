"""Ground-truth ingest API (W5) — the durable, org-scoped home for real quotes.

Retires the Python-REPL requirement: real cost/quote data lands via
``POST /api/v1/ground-truth`` (org-stamped), lists/reads back, and a
``POST /api/v1/ground-truth/recalibrate`` trigger re-runs the tested ground-truth
loop over THIS org's records — refreshing the served Calibration / ResidualModel
so ``/validate/cost`` returns MEASURED confidence intervals.

Tenancy: ORG-SCOPED via the ``resolve_org`` boundary. Every read/write is scoped
to the caller's org; one org's ground truth never enters another's calibration
(cross-tenant test asserts this by name). Ingest requires ``analyst``; reads
require ``viewer``; recalibration requires ``analyst``.
"""
from __future__ import annotations

import logging
import os
from datetime import date
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
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.services import groundtruth_service as svc

logger = logging.getLogger("cadverify.groundtruth")

router = APIRouter(tags=["ground-truth"])

_CHUNK = 1024 * 1024  # 1 MiB


def _import_cap_bytes() -> int:
    """Bulk-import size cap. Read lazily so tests can override via env.

    Historical-cost CSVs are text, not meshes — a much smaller cap than the STL
    upload path (``GROUNDTRUTH_IMPORT_MAX_MB``, default 10MB) is honest here.
    """
    try:
        mb = int(os.getenv("GROUNDTRUTH_IMPORT_MAX_MB", "10"))
    except ValueError:
        mb = 10
    return max(1, mb) * 1024 * 1024


async def _read_capped_chunks(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    """Stream chunks, rejecting anything over ``limit`` WITHOUT buffering the
    whole payload — mirrors ``routes._read_capped``. Raises 413 as soon as the
    running total crosses the cap (before pulling further chunks); 400 if empty.
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


class GroundTruthIn(BaseModel):
    """One real cost/quote datum to persist as org-scoped ground truth."""

    part_id: str = Field(
        ..., min_length=1,
        description="Stable part identity = the STL filename (the split key).",
    )
    process: str = Field(
        ..., min_length=1,
        description="Engine ProcessType id, e.g. cnc_3axis, sls, injection_molding.",
    )
    quantity: int = Field(..., ge=1, description="Order quantity for this quote.")
    actual_unit_cost_usd: float = Field(
        ..., gt=0, description="The KNOWN real per-unit cost / quote."
    )
    material_class: str = Field(
        "polymer", description="polymer|aluminum|steel|stainless|titanium"
    )
    shop: Optional[str] = Field(
        None, description="Shop-profile id this quote is bound to (None = DEFAULT card)."
    )
    region: Optional[str] = Field(None, description="Explicit region override.")
    currency: str = "USD"
    source: str = Field(
        "", description="Provenance of the number (quote #, PO, vendor) — audit trail."
    )
    source_type: str = Field(
        "actual",
        description=(
            "actual|quote|invoice|pilot|synthetic|seed|demo|stand_in. "
            "Synthetic/seed/demo/stand_in are forced to stand_in=True and never validate."
        ),
    )
    vendor_quote_id: Optional[str] = Field(
        None, description="Customer/vendor quote, PO line, or invoice identifier."
    )
    invoice_date: Optional[date] = Field(
        None, description="Invoice/quote date when known (YYYY-MM-DD)."
    )
    actual_machine_hours: Optional[float] = Field(
        None, ge=0, description="Observed machine hours from the real job."
    )
    actual_setup_hours: Optional[float] = Field(
        None, ge=0, description="Observed setup hours from the real job."
    )
    actual_labor_hours: Optional[float] = Field(
        None, ge=0, description="Observed labor hours from the real job."
    )
    actual_inspection_hours: Optional[float] = Field(
        None, ge=0, description="Observed inspection/FAI hours from the real job."
    )
    actual_cycle_seconds: Optional[float] = Field(
        None, ge=0, description="Observed per-unit cycle seconds when available."
    )
    evidence_sha256: Optional[str] = Field(
        None, description="SHA-256 of the source artifact, quote, invoice, or job traveler."
    )
    evidence_uri: Optional[str] = Field(
        None, description="Customer-controlled reference to the source artifact."
    )
    stand_in: bool = Field(
        False,
        description=(
            "False (default) = REAL ground truth. True = synthetic stand-in — it "
            "can shape a band's spread but can NEVER flip validated=True."
        ),
    )
    part_path: Optional[str] = Field(
        None, description="Explicit STL path; else resolved from part_id under parts_dir."
    )
    notes: str = ""


async def _require_org(session: AsyncSession, user: AuthedUser) -> str:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


@router.post("", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;1000/day")
async def create_ground_truth(
    request: Request,
    response: Response,
    payload: GroundTruthIn,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Persist one real ground-truth record for the caller's organization.

    Org-stamped and validated through the costing ``GroundTruthRecord`` (a
    non-positive cost / empty part_id is a clean 400). Dedup: last write wins on
    ``(part_id, process, quantity, shop)`` within the org.
    """
    org_id = await _require_org(session, user)
    try:
        row = await svc.ingest_record(
            session, org_id, user.user_id, payload.model_dump()
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await session.commit()
    from src.services.audit_service import emit_event
    emit_event(
        user.user_id, "groundtruth.ingested", "ground_truth", row.ulid,
        {"org_id": org_id, "part_id": row.part_id, "process": row.process,
         "quantity": row.quantity},
    )
    return svc.row_to_public(row)


@router.get("")
@limiter.limit("120/hour;1000/day")
async def list_ground_truth(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller org's ground-truth records (newest first)."""
    org_id = await _require_org(session, user)
    rows = await svc.list_records(session, org_id)
    return {"records": [svc.row_to_public(r) for r in rows], "total": len(rows)}


@router.get("/{record_id}")
@limiter.limit("120/hour;1000/day")
async def get_ground_truth(
    request: Request,
    response: Response,
    record_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Fetch one record by its public id — 404 if it is not in the caller's org."""
    org_id = await _require_org(session, user)
    row = await svc.get_record(session, org_id, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ground-truth record not found.")
    return svc.row_to_public(row)


@router.post("/recalibrate", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("10/hour;50/day")
async def recalibrate_ground_truth(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Re-run the ground-truth loop over THIS org's records and refresh the
    served Calibration / ResidualModel. The manual recalibration trigger; the
    returned summary carries the measured claim and whether the band is now
    ``validated`` (True only from REAL held-out residuals).

    HONESTLY GATED: with fewer than ``MIN_REAL_RECORDS`` real (non-stand-in)
    records the request is REFUSED with a 422 that names the shortfall, rather
    than emitting a calibration from insufficient / synthetic data.
    """
    org_id = await _require_org(session, user)
    try:
        return await svc.recalibrate_org(session, org_id)
    except svc.InsufficientGroundTruth as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": str(exc),
                "n_real": exc.n_real,
                "n_records": exc.n_records,
                "min_real": exc.min_real,
            },
        )


@router.get("/import/template", response_class=PlainTextResponse)
@limiter.limit("120/hour;1000/day")
async def import_template(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
):
    """The exact CSV header a customer must produce for bulk import.

    Required columns: ``part_id, process, quantity, actual_unit_cost_usd``.
    Optional: ``material_class`` (default polymer), ``shop``, ``region``,
    ``currency`` (default USD), ``source``, source/evidence/hour metadata,
    ``part_path``, ``notes``. There is no ``stand_in`` column; use
    ``source_type=synthetic|seed|demo|stand_in`` for rows that should exercise
    the apparatus without counting as real ground truth.
    """
    example = (
        "widget-a.stl,cnc_3axis,100,42.50,aluminum,acme-shop,US,USD,"
        "PO-1001,quote,Q-1001,2026-06-30,1.2,0.4,0.8,0.2,43.2,"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,"
        "customer://quotes/Q-1001.pdf,,first article"
    )
    return svc.CSV_HEADER + "\n" + example + "\n"


@router.post("/import", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def import_ground_truth(
    request: Request,
    response: Response,
    file: Optional[UploadFile] = File(None),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Bulk-import an org's historical costs from a CSV to feed the flywheel.

    Accepts either a multipart ``file`` upload OR a raw ``text/csv`` request
    body. Streams with an honest size cap (``GROUNDTRUTH_IMPORT_MAX_MB``, 413 on
    overflow) — the file is never buffered unbounded. Parses STRICTLY: every
    valid row is persisted through the SAME single-record create path (org-scoped,
    ``stand_in=False`` — these are REAL and count toward the calibration floor);
    every malformed row is reported, never coerced.

    Partial success is honest: a file with some bad rows returns 200 with the
    valid rows imported and the per-line errors listed. A fully-invalid (or
    empty-of-valid-rows) file still returns 200 with ``imported=0`` and the
    errors — the endpoint reports, it does not crash. A row whose
    ``source_type`` is synthetic/seed/demo/stand_in is imported as ``stand_in``
    and never counts toward the validation floor. The columns are documented
    at ``GET /import/template`` and in ``groundtruth_service.CSV_HEADER``.

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

    rows, parse_errors = svc.parse_ground_truth_csv(text)
    imported, insert_errors = await svc.import_records(
        session, org_id, user.user_id, rows
    )
    await session.commit()

    errors = parse_errors + insert_errors
    total = len(rows) + len(parse_errors)
    return {
        "imported": imported,
        "skipped": total - imported,
        "total": total,
        "errors": errors,
    }
