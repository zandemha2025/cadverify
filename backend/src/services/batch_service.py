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
import zipfile
from typing import AsyncGenerator, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import Analysis, Batch, BatchItem

logger = logging.getLogger("cadverify.batch_service")

# ---------------------------------------------------------------------------
# Constants (from env vars)
# ---------------------------------------------------------------------------

BATCH_MAX_ITEMS = int(os.getenv("BATCH_MAX_ITEMS", "10000"))
BATCH_MAX_ZIP_BYTES = int(os.getenv("BATCH_MAX_ZIP_BYTES", str(5 * 1024**3)))
BATCH_MAX_FILE_BYTES = int(os.getenv("BATCH_MAX_FILE_BYTES", str(100 * 1024**2)))
MAX_COMPRESSION_RATIO = 100
DEFAULT_BATCH_CONCURRENCY = int(os.getenv("DEFAULT_BATCH_CONCURRENCY", "10"))
BATCH_BLOB_DIR = os.getenv("BATCH_BLOB_DIR", "/data/blobs/batch")
VALID_EXTENSIONS = {".stl", ".step", ".stp"}

_VALID_PRIORITIES = {"low", "normal", "high"}
_CSV_EXPORT_PAGE_SIZE = 200


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
) -> Batch:
    """Create a Batch row with status='pending'. Returns the Batch object."""
    batch = Batch(
        ulid=str(ULID()),
        user_id=user_id,
        input_mode=input_mode,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        concurrency_limit=concurrency_limit or DEFAULT_BATCH_CONCURRENCY,
        api_key_id=api_key_id,
    )
    session.add(batch)
    await session.flush()
    return batch


# ---------------------------------------------------------------------------
# ZIP extraction with bomb protection
# ---------------------------------------------------------------------------


def extract_zip_to_items(zip_bytes: bytes, batch_ulid: str) -> list[dict]:
    """Extract valid CAD files from a ZIP archive to disk.

    Enforces:
    - Max items (BATCH_MAX_ITEMS)
    - Per-file size limit (BATCH_MAX_FILE_BYTES)
    - Compression ratio limit (MAX_COMPRESSION_RATIO) for zip bomb protection
    - Path traversal prevention via os.path.basename()

    Returns list of dicts with either extracted file info or skip records.
    """
    results: list[dict] = []
    extract_dir = os.path.join(BATCH_BLOB_DIR, batch_ulid)
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        cad_entries = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            safe_name = os.path.basename(info.filename)
            if not safe_name:
                continue
            ext = os.path.splitext(safe_name)[1].lower()
            if ext not in VALID_EXTENSIONS:
                continue  # skip non-CAD silently
            cad_entries.append((info, safe_name))

        if len(cad_entries) > BATCH_MAX_ITEMS:
            raise ValueError(
                f"ZIP contains {len(cad_entries)} CAD files, "
                f"exceeding limit of {BATCH_MAX_ITEMS}"
            )

        for info, safe_name in cad_entries:
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


# ---------------------------------------------------------------------------
# CSV manifest parsing
# ---------------------------------------------------------------------------


def parse_csv_manifest(csv_content: str) -> list[dict]:
    """Parse a CSV manifest with columns: filename, process_types, rule_pack, priority.

    'filename' is required; others are optional with sensible defaults.
    Raises ValueError on missing filename column or invalid priority values.
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

        items.append({
            "filename": filename,
            "process_types": (row.get("process_types") or "").strip() or None,
            "rule_pack": (row.get("rule_pack") or "").strip() or None,
            "priority": priority,
        })

    return items


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
    count = 0
    for item in items_data:
        status = item.get("status", "pending")
        bi = BatchItem(
            ulid=str(ULID()),
            batch_id=batch_id,
            filename=item["filename"],
            status=status,
            process_types=item.get("process_types"),
            rule_pack=item.get("rule_pack"),
            priority=item.get("priority", "normal"),
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

    Returns None if batch not found or not owned by user.
    """
    stmt = select(Batch).where(Batch.ulid == batch_ulid, Batch.user_id == user_id)
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
) -> AsyncGenerator[str, None]:
    """Async generator yielding CSV rows for StreamingResponse.

    Paginated internally (200 items per page) to avoid memory bloat.
    Joins batch_items with analyses for verdict/best_process data.
    """
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
