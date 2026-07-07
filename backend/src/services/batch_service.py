"""Batch service -- create, extract, query, and export batch operations.

Handles batch creation, ZIP extraction with bomb protection, CSV manifest
parsing, progress queries, atomic counter updates, and CSV export.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery
from src.db.models import Analysis, Batch, BatchItem, CostDecision

logger = logging.getLogger("cadverify.batch_service")

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


class ZipTooLargeError(ValueError):
    """Uploaded ZIP exceeded the configured size cap (streamed, early-rejected)."""

# ---------------------------------------------------------------------------
# Constants (from env vars)
# ---------------------------------------------------------------------------

BATCH_MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", "10000"))
BATCH_MAX_ZIP_BYTES = int(os.getenv("BATCH_MAX_ZIP_BYTES", str(5 * 1024**3)))
BATCH_MAX_FILE_BYTES = int(os.getenv("BATCH_MAX_FILE_BYTES", str(100 * 1024**2)))
MAX_COMPRESSION_RATIO = 100
DEFAULT_BATCH_CONCURRENCY = int(os.getenv("DEFAULT_BATCH_CONCURRENCY", "10"))
BATCH_BLOB_DIR = os.getenv("BATCH_BLOB_DIR", "/data/blobs/batch")
VALID_EXTENSIONS = {".stl", ".step", ".stp", ".iges", ".igs"}
NATIVE_CAD_EXTENSIONS = {
    ".sldprt",
    ".sldasm",
    ".slddrw",
    ".prt",
    ".asm",
    ".ipt",
    ".iam",
    ".catpart",
    ".catproduct",
    ".x_t",
    ".x_b",
    ".sat",
    ".sab",
    ".jt",
    ".3dxml",
}
DRAWING_EXTENSIONS = {".dwg", ".dxf", ".drw", ".idw"}
CAD_TRIAGE_EXTENSIONS = NATIVE_CAD_EXTENSIONS | DRAWING_EXTENSIONS

_VALID_PRIORITIES = {"low", "normal", "high"}
_CSV_EXPORT_PAGE_SIZE = 200

# W3 cost-batch job type. BATCH_COST_ENABLED gates the cost path at create time
# (default ON); when off, a cost batch is rejected 501 (mirrors S3 honesty).
VALID_JOB_TYPES = {"dfm", "cost"}

# Cost-manifest validity vectors — mirror the POST /validate/cost validators
# (routes.py ``_REGIONS`` / ``_MATERIAL_CLASSES`` / ``_MAX_QTYS`` / ``_MAX_QTY``)
# so a manifest-supplied value is accepted iff the live cost route would accept
# it. Kept as literals here (not imported from the API layer) to avoid a
# service→router import cycle; they are stable domain enums.
_COST_VALID_REGIONS = {"US", "EU", "MX", "CN", "IN", "SA"}
_COST_VALID_MATERIAL_CLASSES = {
    "polymer", "aluminum", "steel", "stainless", "titanium",
}
_COST_MAX_QTYS = 6
_COST_MAX_QTY = 10_000_000


# ---------------------------------------------------------------------------
# Batch CRUD
# ---------------------------------------------------------------------------


async def create_batch(
    session: AsyncSession,
    user_id: int,
    input_mode: str,
    webhook_url: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    concurrency_limit: Optional[int] = None,
    api_key_id: Optional[int] = None,
    job_type: str = "dfm",
) -> Batch:
    """Create a Batch row with status='pending'. Returns the Batch object."""
    from src.auth.org_context import resolve_org

    batch = Batch(
        ulid=str(ULID()),
        user_id=user_id,
        org_id=await resolve_org(session, user_id),
        input_mode=input_mode,
        job_type=job_type,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        concurrency_limit=concurrency_limit or DEFAULT_BATCH_CONCURRENCY,
        api_key_id=api_key_id,
    )
    session.add(batch)
    await session.flush()

    # Audit: batch.submitted
    import asyncio
    from src.services.audit_service import fire_and_forget_audit, _lookup_email
    _email = await _lookup_email(user_id)
    asyncio.create_task(fire_and_forget_audit(
        user_id=user_id, user_email=_email,
        action="batch.submitted", resource_type="batch",
        resource_id=batch.ulid,
        detail={"input_mode": input_mode, "job_type": job_type},
    ))

    return batch


# ---------------------------------------------------------------------------
# ZIP extraction with bomb protection
# ---------------------------------------------------------------------------


async def stream_upload_to_tempfile(
    upload,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Stream an UploadFile to a temp file, rejecting once *max_bytes* exceeded.

    F-ARCH-9: the old path did ``await file.read()`` -- pulling the entire
    (potentially multi-GB) ZIP into RAM before checking the size cap. We now
    stream in chunks and reject as soon as the cumulative size crosses the cap,
    so an oversized upload never fully materializes in memory.

    Returns the temp file path (caller owns cleanup on success). On rejection the
    partial temp file is removed and ``ZipTooLargeError`` is raised.
    """
    fd, path = tempfile.mkstemp(suffix=".zip", prefix="cv_batch_")
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ZipTooLargeError(
                        f"ZIP upload exceeds maximum size of {max_bytes} bytes"
                    )
                out.write(chunk)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


def _dedup_name(base: str, seen: set[str]) -> str:
    """Return a name unique within *seen*, suffixing ``_1``, ``_2`` on collision.

    Prevents the F-ARCH-9 silent collapse: two archive entries with the same
    basename in different folders (``a/part.stl`` + ``b/part.stl``) used to
    overwrite each other on disk and produce two items pointing at one file.
    """
    if base not in seen:
        seen.add(base)
        return base
    stem, ext = os.path.splitext(base)
    i = 1
    while True:
        candidate = f"{stem}_{i}{ext}"
        if candidate not in seen:
            seen.add(candidate)
            return candidate
        i += 1


def _unsupported_cad_error(ext: str) -> str:
    kind = "drawing" if ext in DRAWING_EXTENSIONS else "native CAD"
    return (
        f"Unsupported {kind} file type {ext or '(none)'}. "
        "Upload STL, STEP/STP, or IGES/IGS for batch analysis; native CAD and "
        "drawings require conversion before processing."
    )


def _extract_zipfile(zf: zipfile.ZipFile, batch_ulid: str) -> list[dict]:
    """Core extraction shared by the bytes- and path-based entry points.

    Enforces:
    - Max items (BATCH_MAX_ITEMS)
    - Per-file size limit (BATCH_MAX_FILE_BYTES)
    - Compression ratio limit (MAX_COMPRESSION_RATIO) for zip bomb protection
    - Path traversal prevention via os.path.basename()
    - Basename dedup so same-named files in different folders don't collapse
      (BATCH_ZIP_DEDUP, default on)
    """
    results: list[dict] = []
    extract_dir = os.path.join(BATCH_BLOB_DIR, batch_ulid)
    os.makedirs(extract_dir, exist_ok=True)

    dedup = _flag("BATCH_ZIP_DEDUP", "1")
    seen: set[str] = set()

    cad_entries = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        base = os.path.basename(info.filename)
        if not base:
            continue
        ext = os.path.splitext(base)[1].lower()
        if ext not in VALID_EXTENSIONS and ext not in CAD_TRIAGE_EXTENSIONS:
            continue  # skip non-CAD silently
        # Assign the final on-disk name up front (deduped) so both skip records
        # and extracted files carry a distinct, stable filename.
        safe_name = _dedup_name(base, seen) if dedup else base
        cad_entries.append((info, safe_name, ext))

    if len(cad_entries) > BATCH_MAX_ITEMS:
        raise ValueError(
            f"ZIP contains {len(cad_entries)} CAD files, "
            f"exceeding limit of {BATCH_MAX_ITEMS}"
        )

    for info, safe_name, ext in cad_entries:
        if ext in CAD_TRIAGE_EXTENSIONS:
            results.append({
                "filename": safe_name,
                "status": "skipped",
                "error": _unsupported_cad_error(ext),
                "size": info.file_size,
            })
            continue

        # Pre-check uncompressed size
        if info.file_size > BATCH_MAX_FILE_BYTES:
            results.append({
                "filename": safe_name,
                "status": "skipped",
                "error": f"File size {info.file_size} exceeds limit {BATCH_MAX_FILE_BYTES}",
            })
            continue

        # Compression ratio check (zip bomb protection)
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > MAX_COMPRESSION_RATIO:
                raise ValueError(
                    f"Compression ratio {ratio:.0f}:1 for '{safe_name}' "
                    f"exceeds limit {MAX_COMPRESSION_RATIO}:1 (possible zip bomb)"
                )

        # Extract file
        dest_path = os.path.join(extract_dir, safe_name)
        with zf.open(info) as src, open(dest_path, "wb") as dst:
            dst.write(src.read())

        results.append({
            "filename": safe_name,
            "path": dest_path,
            "size": info.file_size,
        })

    return results


def extract_zip_to_items(zip_bytes: bytes, batch_ulid: str) -> list[dict]:
    """Extract valid CAD files from an in-memory ZIP archive to disk."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        return _extract_zipfile(zf, batch_ulid)


def extract_zip_path_to_items(zip_path: str, batch_ulid: str) -> list[dict]:
    """Extract valid CAD files from a ZIP on disk (streamed upload path).

    zipfile reads entries lazily from the file, so the whole archive is never
    held in RAM -- the counterpart to stream_upload_to_tempfile().
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        return _extract_zipfile(zf, batch_ulid)


# ---------------------------------------------------------------------------
# CSV manifest parsing
# ---------------------------------------------------------------------------


def parse_csv_manifest(csv_content: str, *, validate_cost: bool = False) -> list[dict]:
    """Parse a CSV manifest with columns: filename, process_types, rule_pack, priority.

    'filename' is required; others are optional with sensible defaults.
    Raises ValueError on missing filename column or invalid priority values.

    When *validate_cost* is True (a cost batch), the optional cost columns
    ``quantities`` (semicolon-separated ints, e.g. "1;100;1000"), ``region``,
    ``material_class`` and ``shop`` are parsed and validated against the SAME
    vectors the live POST /validate/cost route accepts — an invalid value raises
    ``ValueError`` naming the 1-indexed row, which the router turns into a
    structured 400. Missing values stay ``None`` → the worker uses engine
    defaults. DFM batches (validate_cost False) ignore these columns entirely, so
    their behaviour is byte-identical.
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    if reader.fieldnames is None or "filename" not in reader.fieldnames:
        raise ValueError("CSV manifest must contain a 'filename' column")

    items: list[dict] = []
    for row_num, row in enumerate(reader, start=2):  # start=2 for 1-indexed + header
        filename = (row.get("filename") or "").strip()
        if not filename:
            raise ValueError(f"Row {row_num}: missing filename")

        priority = (row.get("priority") or "normal").strip().lower()
        if priority not in _VALID_PRIORITIES:
            raise ValueError(
                f"Row {row_num}: invalid priority '{priority}'. "
                f"Valid: {sorted(_VALID_PRIORITIES)}"
            )

        item = {
            "filename": filename,
            "process_types": (row.get("process_types") or "").strip() or None,
            "rule_pack": (row.get("rule_pack") or "").strip() or None,
            "priority": priority,
        }

        if validate_cost:
            item.update(_parse_cost_manifest_fields(row, row_num))

        items.append(item)

    return items


def _parse_cost_manifest_fields(row: dict, row_num: int) -> dict:
    """Validate + normalize the cost columns of one manifest row.

    Returns ``{"quantities","region","material_class","shop"}`` (each None when
    the column is absent/blank → engine default at cost time). Raises ValueError
    naming *row_num* on any invalid value, matching the route's fail-fast 400.
    """
    # quantities: a semicolon-separated list of ints inside one cell.
    raw_qty = (row.get("quantities") or "").strip()
    quantities: Optional[str] = None
    if raw_qty:
        toks = [t.strip() for t in raw_qty.split(";") if t.strip()]
        parsed: list[int] = []
        for tok in toks:
            try:
                v = int(tok)
            except ValueError:
                raise ValueError(
                    f"Row {row_num}: invalid quantity '{tok}' (must be an integer)"
                )
            if not (1 <= v <= _COST_MAX_QTY):
                raise ValueError(
                    f"Row {row_num}: quantity {v} out of range [1, {_COST_MAX_QTY}]"
                )
            parsed.append(v)
        if not parsed:
            raise ValueError(f"Row {row_num}: quantities column is empty")
        if len(parsed) > _COST_MAX_QTYS:
            raise ValueError(
                f"Row {row_num}: at most {_COST_MAX_QTYS} quantities allowed"
            )
        # Re-serialize canonically (strip whitespace) for durable storage.
        quantities = ";".join(str(v) for v in parsed)

    # region
    raw_region = (row.get("region") or "").strip()
    region: Optional[str] = None
    if raw_region:
        if raw_region not in _COST_VALID_REGIONS:
            raise ValueError(
                f"Row {row_num}: unknown region '{raw_region}'. "
                f"Use one of {sorted(_COST_VALID_REGIONS)}"
            )
        region = raw_region

    # material_class
    raw_material = (row.get("material_class") or "").strip()
    material_class: Optional[str] = None
    if raw_material:
        if raw_material not in _COST_VALID_MATERIAL_CLASSES:
            raise ValueError(
                f"Row {row_num}: unknown material_class '{raw_material}'. "
                f"Use one of {sorted(_COST_VALID_MATERIAL_CLASSES)}"
            )
        material_class = raw_material

    # shop: resolve to a known local profile slug (or reject). Mirrors the route's
    # _resolve_shop_param — only an existing profile (by slug or display name) is
    # accepted, never an arbitrary path.
    raw_shop = (row.get("shop") or "").strip()
    shop: Optional[str] = None
    if raw_shop:
        shop = _resolve_manifest_shop(raw_shop, row_num)

    return {
        "quantities": quantities,
        "region": region,
        "material_class": material_class,
        "shop": shop,
    }


def _resolve_manifest_shop(shop: str, row_num: int) -> str:
    """Resolve a caller-supplied shop (slug OR display name) to a known profile
    slug, or raise ValueError(row_num). Reads the local shop-profile store only —
    the same allow-list the cost route enforces (no path traversal)."""
    from src.costing.shop_profile import _slug, load_profile, list_profiles

    req = shop.strip()
    req_slug = _slug(req)
    for slug in list_profiles():
        if req == slug or req_slug == slug:
            return slug
        try:
            p = load_profile(slug)
        except Exception:  # pragma: no cover - defensive; skip unreadable profile
            continue
        if req.lower() == (p.name or "").lower():
            return slug
    raise ValueError(
        f"Row {row_num}: unknown shop '{shop}'. Available: "
        f"{list(list_profiles()) or '(none)'}"
    )


# ---------------------------------------------------------------------------
# Batch items bulk insert
# ---------------------------------------------------------------------------


async def create_batch_items(
    session: AsyncSession,
    batch_id: int,
    items_data: list[dict],
) -> int:
    """Bulk-insert BatchItem rows from parsed manifest/extraction data.

    Returns count of items created.
    """
    from src.auth.org_context import resolve_org_via_batch

    org_id = await resolve_org_via_batch(session, batch_id)
    count = 0
    for item in items_data:
        status = item.get("status", "pending")
        bi = BatchItem(
            ulid=str(ULID()),
            batch_id=batch_id,
            org_id=org_id,
            filename=item["filename"],
            status=status,
            process_types=item.get("process_types"),
            rule_pack=item.get("rule_pack"),
            priority=item.get("priority", "normal"),
            # W3 cost params (None for DFM items / unset manifest cells).
            quantities=item.get("quantities"),
            region=item.get("region"),
            material_class=item.get("material_class"),
            shop=item.get("shop"),
            error_message=item.get("error"),
            file_size_bytes=item.get("size"),
        )
        session.add(bi)
        count += 1
    await session.flush()
    return count


# ---------------------------------------------------------------------------
# Progress queries
# ---------------------------------------------------------------------------


async def get_batch_progress(
    session: AsyncSession,
    batch_ulid: str,
    user_id: int,
) -> dict | None:
    """Return batch progress dict. O(1) via denormalized counters.

    Returns None if the batch does not exist or belongs to another org
    (W1 step 3: org-scoped — ``user_id`` resolves the caller's org boundary).
    """
    stmt = select(Batch).where(
        Batch.ulid == batch_ulid,
        Batch.org_id == caller_org_subquery(user_id),
    )
    batch = (await session.execute(stmt)).scalars().first()
    if batch is None:
        return None

    return {
        "batch_ulid": batch.ulid,
        "status": batch.status,
        "input_mode": batch.input_mode,
        "total_items": batch.total_items,
        "completed_items": batch.completed_items,
        "failed_items": batch.failed_items,
        "pending_items": batch.total_items - batch.completed_items - batch.failed_items,
        "concurrency_limit": batch.concurrency_limit,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
    }


async def get_batch_items_page(
    session: AsyncSession,
    batch_id: int,
    status_filter: Optional[str] = None,
    cursor: Optional[int] = None,
    limit: int = 50,
) -> tuple[list[BatchItem], bool]:
    """Cursor-paginated batch items query.

    Returns (items, has_more).
    """
    stmt = select(BatchItem).where(BatchItem.batch_id == batch_id)

    if status_filter:
        stmt = stmt.where(BatchItem.status == status_filter)

    if cursor is not None:
        stmt = stmt.where(BatchItem.id > cursor)

    stmt = stmt.order_by(BatchItem.id).limit(limit + 1)

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    items = list(rows[:limit])
    return items, has_more


# ---------------------------------------------------------------------------
# CSV export (streaming)
# ---------------------------------------------------------------------------


async def generate_results_csv(
    session: AsyncSession,
    batch_id: int,
    job_type: str = "dfm",
) -> AsyncGenerator[str, None]:
    """Async generator yielding CSV rows for StreamingResponse.

    Paginated internally (200 items per page) to avoid memory bloat. Branches on
    the batch's *job_type*: a DFM batch joins analyses (verdict/best_process); a
    cost batch joins cost_decisions and emits the should-cost columns. Both honour
    the catalog honesty rule — a cost row withholds ``unit_cost_usd`` when the
    make-now estimate is DFM-blocked, and ``validated`` is copied from the
    engine's confidence band, never computed here.
    """
    if job_type == "cost":
        async for chunk in _generate_cost_results_csv(session, batch_id):
            yield chunk
        return

    header = "filename,status,verdict,best_process,issue_count,duration_ms,analysis_url,error\n"
    yield header

    cursor: int | None = None
    while True:
        stmt = (
            select(BatchItem, Analysis)
            .outerjoin(Analysis, BatchItem.analysis_id == Analysis.id)
            .where(BatchItem.batch_id == batch_id)
        )
        if cursor is not None:
            stmt = stmt.where(BatchItem.id > cursor)
        stmt = stmt.order_by(BatchItem.id).limit(_CSV_EXPORT_PAGE_SIZE)

        rows = (await session.execute(stmt)).all()
        if not rows:
            break

        for bi, analysis in rows:
            verdict = ""
            best_process = ""
            issue_count = ""
            analysis_url = ""

            if analysis is not None:
                result = analysis.result_json or {}
                verdict = analysis.verdict or ""
                best_process = result.get("best_process", "") or ""
                issues = result.get("issues", [])
                issue_count = str(len(issues)) if isinstance(issues, list) else ""
                analysis_url = f"/api/v1/analyses/{analysis.ulid}"

            row_str = (
                f"{_csv_escape(bi.filename)},"
                f"{_csv_escape(bi.status)},"
                f"{_csv_escape(verdict)},"
                f"{_csv_escape(best_process)},"
                f"{issue_count},"
                f"{bi.duration_ms or ''},"
                f"{_csv_escape(analysis_url)},"
                f"{_csv_escape(bi.error_message or '')}\n"
            )
            yield row_str
            cursor = bi.id

        if len(rows) < _CSV_EXPORT_PAGE_SIZE:
            break


async def _generate_cost_results_csv(
    session: AsyncSession,
    batch_id: int,
) -> AsyncGenerator[str, None]:
    """Cost-batch CSV: one row per item, joined to its cost_decision.

    ``unit_cost_usd`` follows catalog withholding (empty when the make-now
    estimate is DFM-blocked); ``validated`` is copied verbatim from the estimate's
    confidence band (never computed here).
    """
    from src.services.catalog_service import make_now_estimate

    header = (
        "filename,status,make_now_process,crossover_qty,quantities,"
        "unit_cost_usd,validated,cost_decision_url,error\n"
    )
    yield header

    cursor: int | None = None
    while True:
        stmt = (
            select(BatchItem, CostDecision)
            .outerjoin(
                CostDecision, BatchItem.cost_decision_id == CostDecision.id
            )
            .where(BatchItem.batch_id == batch_id)
        )
        if cursor is not None:
            stmt = stmt.where(BatchItem.id > cursor)
        stmt = stmt.order_by(BatchItem.id).limit(_CSV_EXPORT_PAGE_SIZE)

        rows = (await session.execute(stmt)).all()
        if not rows:
            break

        for bi, decision in rows:
            make_now_process = ""
            crossover_qty = ""
            quantities = ""
            unit_cost_usd = ""
            validated = ""
            cost_decision_url = ""

            if decision is not None:
                result = decision.result_json or {}
                make_now_process = decision.make_now_process or ""
                crossover_qty = (
                    "" if decision.crossover_qty is None
                    else str(decision.crossover_qty)
                )
                qtys = decision.quantities or result.get("quantities") or []
                if isinstance(qtys, list):
                    quantities = ";".join(str(q) for q in qtys)
                cost_decision_url = f"/api/v1/cost-decisions/{decision.ulid}"

                est = make_now_estimate(result)
                if est is not None:
                    blocked = not est.get("dfm_ready", True)
                    # Withhold the price on a DFM-blocked route (catalog honesty).
                    if not blocked and est.get("unit_cost_usd") is not None:
                        unit_cost_usd = str(est.get("unit_cost_usd"))
                    ci = est.get("confidence") or {}
                    # Copied from the artifact — never computed here.
                    validated = str(bool(ci.get("validated", False)))

            row_str = (
                f"{_csv_escape(bi.filename)},"
                f"{_csv_escape(bi.status)},"
                f"{_csv_escape(make_now_process)},"
                f"{_csv_escape(crossover_qty)},"
                f"{_csv_escape(quantities)},"
                f"{_csv_escape(unit_cost_usd)},"
                f"{_csv_escape(validated)},"
                f"{_csv_escape(cost_decision_url)},"
                f"{_csv_escape(bi.error_message or '')}\n"
            )
            yield row_str
            cursor = bi.id

        if len(rows) < _CSV_EXPORT_PAGE_SIZE:
            break


def _csv_escape(value: str) -> str:
    """Escape a CSV field value if it contains commas, quotes, or newlines."""
    if not value:
        return ""
    if any(c in value for c in (",", '"', "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


# ---------------------------------------------------------------------------
# Atomic counter updates
# ---------------------------------------------------------------------------


async def update_batch_counters(
    session: AsyncSession,
    batch_id: int,
    field: str,
) -> None:
    """Atomic SQL increment of a counter field on the batches table.

    field must be 'completed_items' or 'failed_items'.
    Uses raw SQL to avoid read-modify-write race conditions.
    """
    if field not in ("completed_items", "failed_items"):
        raise ValueError(f"Invalid counter field: {field}")

    await session.execute(
        text(f"UPDATE batches SET {field} = {field} + 1 WHERE id = :batch_id"),
        {"batch_id": batch_id},
    )


# ---------------------------------------------------------------------------
# Failure / orphan handling (F-ARCH-1)
# ---------------------------------------------------------------------------

# How long a batch with NO coordinator heartbeat may sit in pending/processing
# before the sweeper declares it orphaned. This is only the fallback anchor (a
# batch whose coordinator never wrote a single heartbeat -- e.g. the API crashed
# between committing the batch and enqueuing its coordinator). Default: 6 hours.
BATCH_ORPHAN_TTL_SECONDS = int(os.getenv("BATCH_ORPHAN_TTL_SECONDS", str(6 * 3600)))

# Heartbeat-based staleness (F-ARCH-6/#2). The self-re-enqueueing coordinator
# writes manifest_json["heartbeat_at"] every poll tick, and run_batch_item
# refreshes the same field on every item completion/failure -- so the heartbeat
# reflects liveness from EITHER source, not just the coordinator. A live
# long-running batch keeps advancing its heartbeat; a dead one (worker crashed,
# coordinator chain broke, a tick was cancelled at arq's job_timeout) stops.
# The sweeper reaps a batch whose heartbeat has not advanced within this
# window -- so a legitimately long batch is NEVER reaped while it is still
# working.
#
# Floored at 600s (not 60s): the coordinator's re-enqueued ticks and every
# batch item share the SAME 12-slot arq pool (WorkerSettings.max_jobs=12), each
# job up to job_timeout=600s. Under pool saturation -- or a deploy pause/worker
# restart lasting longer than a few seconds -- a coordinator tick can easily be
# delayed well past 60s even though the batch is completely healthy. A 60s
# floor made that a false-positive orphan reap that permanently stranded
# not-yet-queued items (the batch is marked failed but items are never
# resumed). 600s matches the worst case of "one more full-length job must
# drain from the shared pool before a tick/item can run again," which is the
# real bound on how stale a live batch's heartbeat can legitimately get.
# Still env-tunable via BATCH_HEARTBEAT_STALE_SECONDS for deployments with a
# different pool/timeout shape.
_BATCH_POLL_INTERVAL_SECONDS = int(os.getenv("BATCH_POLL_INTERVAL_SECONDS", "2"))
BATCH_HEARTBEAT_STALE_FACTOR = int(os.getenv("BATCH_HEARTBEAT_STALE_FACTOR", "10"))
BATCH_HEARTBEAT_STALE_FLOOR_SECONDS = 600
BATCH_HEARTBEAT_STALE_SECONDS = int(
    os.getenv(
        "BATCH_HEARTBEAT_STALE_SECONDS",
        str(
            max(
                BATCH_HEARTBEAT_STALE_FACTOR * _BATCH_POLL_INTERVAL_SECONDS,
                BATCH_HEARTBEAT_STALE_FLOOR_SECONDS,
            )
        ),
    )
)


def mark_batch_failed(batch: Batch, reason: str) -> None:
    """Mark a Batch row failed and record *why* in manifest_json.

    Reassigns manifest_json (rather than mutating in place) so SQLAlchemy detects
    the JSONB change. Caller commits.
    """
    batch.status = "failed"
    batch.completed_at = datetime.now(timezone.utc)
    manifest = dict(batch.manifest_json or {})
    manifest["failure_reason"] = reason
    batch.manifest_json = manifest


def touch_batch_heartbeat(batch: Batch, now: Optional[datetime] = None) -> None:
    """Record a fresh coordinator heartbeat in manifest_json['heartbeat_at'].

    The self-re-enqueueing coordinator calls this on every poll tick. The orphan
    sweeper uses it to tell a live long-running batch (heartbeat advancing) apart
    from a dead one (heartbeat stale). Reassigns manifest_json so SQLAlchemy sees
    the JSONB mutation. Caller commits.
    """
    now = now or datetime.now(timezone.utc)
    manifest = dict(batch.manifest_json or {})
    manifest["heartbeat_at"] = now.isoformat()
    batch.manifest_json = manifest


def _parse_heartbeat(manifest_json: Optional[dict]) -> Optional[datetime]:
    """Extract a UTC-aware heartbeat timestamp from manifest_json, or None."""
    if not manifest_json:
        return None
    raw = manifest_json.get("heartbeat_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def mark_pending_items_terminal(
    session: AsyncSession,
    batch_id: int,
    terminal_status: str = "skipped",
) -> None:
    """Move a batch's non-terminal items to a terminal state (F-ARCH-1/#3).

    When a batch is marked failed on the enqueue-failure path, its items would
    otherwise keep their non-terminal 'pending' status, so progress endpoints
    (pending_items = total - completed - failed) would advertise work that will
    never run. Terminalize them so the read is consistent. Caller commits.
    """
    await session.execute(
        text(
            "UPDATE batch_items SET status = :s "
            "WHERE batch_id = :b AND status IN ('pending', 'queued', 'processing')"
        ),
        {"s": terminal_status, "b": batch_id},
    )


async def sweep_orphaned_batches(
    session: AsyncSession,
    ttl_seconds: Optional[int] = None,
    heartbeat_stale_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> int:
    """Mark dead batches stuck in pending/processing as failed=orphaned.

    Staleness is measured from the coordinator's heartbeat
    (manifest_json['heartbeat_at']) when present: a batch is reaped only once its
    heartbeat is older than *heartbeat_stale_seconds*, so a legitimately long
    batch that keeps ticking is never reaped (F-ARCH-6/#2). Only when NO heartbeat
    was ever written -- the coordinator never ran (crash between commit and
    enqueue) -- do we fall back to the wall-clock TTL from started_at/created_at.

    Returns the number of batches reaped. Caller commits.
    """
    from datetime import timedelta

    ttl = BATCH_ORPHAN_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    hb_stale = (
        BATCH_HEARTBEAT_STALE_SECONDS
        if heartbeat_stale_seconds is None
        else heartbeat_stale_seconds
    )
    now = now or datetime.now(timezone.utc)
    ttl_cutoff = now - timedelta(seconds=ttl)
    hb_cutoff = now - timedelta(seconds=hb_stale)

    stmt = select(Batch).where(Batch.status.in_(["pending", "processing"]))
    rows = (await session.execute(stmt)).scalars().all()

    reaped = 0
    for batch in rows:
        heartbeat = _parse_heartbeat(batch.manifest_json)
        if heartbeat is not None:
            # Primary path: reap only when the heartbeat has gone stale.
            if heartbeat <= hb_cutoff:
                mark_batch_failed(batch, "orphaned")
                reaped += 1
                logger.warning(
                    "Reaped orphaned batch %s (status was %s, heartbeat=%s stale)",
                    batch.ulid, batch.status, heartbeat.isoformat(),
                )
            continue
        # Fallback: no heartbeat ever written -> the coordinator never ran.
        anchor = batch.started_at or batch.created_at
        if anchor is None:
            continue
        # Normalize naive timestamps (defensive) to UTC-aware for comparison.
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        if anchor <= ttl_cutoff:
            mark_batch_failed(batch, "orphaned")
            reaped += 1
            logger.warning(
                "Reaped orphaned batch %s (status was %s, no heartbeat, anchor=%s)",
                batch.ulid, batch.status, anchor.isoformat(),
            )
    return reaped


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_batch_files(batch_ulid: str) -> None:
    """Delete /data/blobs/batch/{batch_ulid}/ directory.

    Called by cleanup task after retention period.
    """
    target_dir = os.path.join(BATCH_BLOB_DIR, batch_ulid)
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)
        logger.info("Cleaned up batch files: %s", target_dir)
    else:
        logger.debug("No batch directory to clean: %s", target_dir)
