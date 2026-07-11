"""Batch API endpoints -- create, status, items, CSV export, cancel.

POST /api/v1/batch          -- create batch (ZIP upload)
GET  /api/v1/batch/{id}     -- batch progress
GET  /api/v1/batch/{id}/items    -- paginated items
GET  /api/v1/batch/{id}/results/csv -- CSV export
POST /api/v1/batch/{id}/cancel   -- cancel batch
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.errors import DOC_BASE
from src.auth.org_context import caller_org_subquery
from src.auth.org_limits import enforce_org_limits
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Batch, BatchItem
from src.services import batch_service
from src.services.batch_service import (
    BATCH_MAX_ZIP_BYTES,
    VALID_JOB_TYPES,
    ZipTooLargeError,
)
from src.services.url_guard import UnsafeURLError, validate_outbound_url

logger = logging.getLogger("cadverify.batch_router")

router = APIRouter(prefix="/api/v1", tags=["batch"])

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# POST /batch -- create batch
# ---------------------------------------------------------------------------


@router.post("/batch", status_code=202)
async def create_batch(
    request: Request,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
    file: Optional[UploadFile] = File(None),
    webhook_url: Optional[str] = Form(None),
    webhook_secret: Optional[str] = Form(None),
    concurrency_limit: Optional[int] = Form(None),
    job_type: str = Form("dfm"),
    s3_bucket: Optional[str] = Form(None),
    s3_prefix: Optional[str] = Form(None),
    manifest_url: Optional[str] = Form(None),
    manifest: Optional[UploadFile] = File(None),
    _org_limit: None = Depends(enforce_org_limits),
):
    """Create a batch for bulk analysis (job_type=dfm) or should-costing
    (job_type=cost).

    Accepts a ZIP file upload. Remote object-store references are rejected up
    front with 501 on this server rather than creating orphaned per-item work.
    Returns 202 with batch_id and status URL.
    """
    # W3: validate the job type. Invalid -> 422 structured (mirrors FastAPI's
    # own validation status for an out-of-domain field value).
    job_type = (job_type or "dfm").strip().lower()
    if job_type not in VALID_JOB_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_JOB_TYPE",
                "message": (
                    f"job_type must be one of {sorted(VALID_JOB_TYPES)}; "
                    f"got {job_type!r}."
                ),
                "doc_url": f"{DOC_BASE}/INVALID_JOB_TYPE",
            },
        )

    # W3 (cost honesty): the cost pipeline is flag-gated. When off, a cost batch
    # is rejected up front with a stable 501 (mirrors the S3 pattern) rather than
    # silently DFM-processed. Flag ON is the default; DFM is never gated, so
    # flag-off leaves every existing behaviour byte-identical.
    if job_type == "cost" and not _flag("BATCH_COST_ENABLED", "1"):
        raise HTTPException(
            status_code=501,
            detail={
                "code": "BATCH_COST_NOT_ENABLED",
                "message": (
                    "Cost batches are not enabled on this server. Set "
                    "BATCH_COST_ENABLED=1 to turn on the should-cost pipeline."
                ),
                "doc_url": f"{DOC_BASE}/BATCH_COST_NOT_ENABLED",
            },
        )

    # F-ARCH-5 (S3/manifest honesty): remote object input requires an object-fetch
    # adapter. No adapter exists in this codebase yet, so reject remote references
    # unconditionally before any Batch row is created. This avoids an env flag
    # accidentally creating a doomed "pending" batch that the worker cannot fetch.
    if s3_bucket is not None or s3_prefix is not None or manifest_url is not None:
        raise HTTPException(
            status_code=501,
            detail={
                "code": "S3_INPUT_UNSUPPORTED",
                "message": (
                    "S3/manifest batch input is not enabled on this server; "
                    "upload a ZIP file or import a manifest CSV instead."
                ),
                "doc_url": f"{DOC_BASE}/S3_INPUT_UNSUPPORTED",
            },
        )

    # Determine input mode
    if file is not None:
        input_mode = "zip"
    elif s3_bucket is not None:
        input_mode = "s3"
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either a ZIP file upload or s3_bucket field",
        )

    # SSRF guard (S7): reject webhook targets that resolve to internal ranges
    # BEFORE any batch row is written. Re-checked at delivery time in
    # webhook_service as defense-in-depth against DNS rebinding.
    if webhook_url is not None:
        try:
            validate_outbound_url(webhook_url)
        except UnsafeURLError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "webhook_url_rejected",
                    "message": f"webhook_url rejected: {exc}",
                    "doc_url": "https://docs.cadverify.com/errors#webhook_url_rejected",
                },
            )

    # For a ZIP upload, stream to a temp file with early size rejection BEFORE
    # creating the batch row -- so an oversized/invalid upload never leaves an
    # orphaned 'pending' batch behind (F-ARCH-9 + F-ARCH-1).
    zip_tmp_path: Optional[str] = None
    if input_mode == "zip":
        # F-ARCH-9 (early cheap reject): if the client declared a Content-Length
        # that already exceeds the cap, reject with 413 before reading a single
        # byte of the body. The streamed read below remains authoritative (a
        # spoofed/absent header cannot bypass the cap), but this short-circuits
        # the obvious 5 GB upload without touching the socket payload.
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                declared_len = int(declared)
            except ValueError:
                declared_len = None
            if declared_len is not None and declared_len > BATCH_MAX_ZIP_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload Content-Length {declared_len} exceeds maximum "
                        f"ZIP size of {BATCH_MAX_ZIP_BYTES} bytes"
                    ),
                )
        try:
            zip_tmp_path = await batch_service.stream_upload_to_tempfile(
                file, BATCH_MAX_ZIP_BYTES
            )
        except ZipTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc))

    try:
        # Create batch row
        batch = await batch_service.create_batch(
            session=session,
            user_id=user.user_id,
            input_mode=input_mode,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            concurrency_limit=concurrency_limit,
            api_key_id=user.api_key_id,
            job_type=job_type,
        )

        if input_mode == "zip":
            # Extract files to disk (streamed from the temp file, not RAM).
            try:
                items_data = batch_service.extract_zip_path_to_items(
                    zip_tmp_path, batch.ulid
                )
            except ValueError as exc:
                # Bad archive (zip bomb / too many items): reject, don't orphan.
                raise HTTPException(status_code=400, detail=str(exc))

            # Parse manifest CSV if provided
            if manifest is not None:
                manifest_bytes = await manifest.read()
                if job_type == "cost":
                    # Cost manifests additionally carry quantities/region/
                    # material_class/shop; an invalid value is a per-row 400
                    # (reject at create time, never at the worker).
                    try:
                        manifest_items = batch_service.parse_csv_manifest(
                            manifest_bytes.decode("utf-8"), validate_cost=True
                        )
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=400,
                            detail={
                                "code": "INVALID_COST_MANIFEST",
                                "message": str(exc),
                                "doc_url": f"{DOC_BASE}/INVALID_COST_MANIFEST",
                            },
                        )
                else:
                    manifest_items = batch_service.parse_csv_manifest(
                        manifest_bytes.decode("utf-8")
                    )
                # Merge manifest metadata with extracted items by filename
                manifest_map = {m["filename"]: m for m in manifest_items}
                for item in items_data:
                    if item.get("status") == "skipped":
                        continue
                    meta = manifest_map.get(item["filename"], {})
                    item["process_types"] = meta.get("process_types")
                    item["rule_pack"] = meta.get("rule_pack")
                    item["priority"] = meta.get("priority", "normal")
                    if job_type == "cost":
                        # Cost knobs (None → engine default at cost time).
                        item["quantities"] = meta.get("quantities")
                        item["region"] = meta.get("region")
                        item["material_class"] = meta.get("material_class")
                        item["shop"] = meta.get("shop")

            # Create batch items
            count = await batch_service.create_batch_items(
                session, batch.id, items_data
            )
            batch.total_items = count
            batch.failed_items = sum(
                1
                for item in items_data
                if item.get("status") in {"failed", "skipped"}
            )
    finally:
        if zip_tmp_path is not None:
            try:
                os.unlink(zip_tmp_path)
            except OSError:
                pass

    await session.commit()

    # Enqueue coordinator task. If enqueue fails, the batch row is already
    # committed -- reject-don't-orphan (F-ARCH-1): mark it failed and return an
    # honest 503 instead of leaving it 'pending' forever with a bare 500.
    from src.jobs.arq_backend import get_arq_pool

    try:
        pool = await get_arq_pool()
        await pool.enqueue_job("run_batch_coordinator", batch.ulid)
    except Exception:
        logger.exception(
            "Failed to enqueue coordinator for batch %s; marking failed", batch.ulid
        )
        batch_service.mark_batch_failed(batch, "enqueue_failed")
        # F-ARCH-1/#3: the batch is failed but its items are still 'pending', so
        # progress (pending_items = total - completed - failed) would advertise
        # work that can never run. Move them to a terminal state so reads agree.
        await batch_service.mark_pending_items_terminal(session, batch.id, "skipped")
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "code": "BATCH_ENQUEUE_FAILED",
                "message": (
                    "Batch was accepted but could not be scheduled (job queue "
                    "unavailable). It has been marked failed; please retry."
                ),
                "doc_url": f"{DOC_BASE}/BATCH_ENQUEUE_FAILED",
            },
        )

    # Never return webhook_secret (T-09-03)
    return {
        "batch_id": batch.ulid,
        "status": batch.status,
        "status_url": f"/api/v1/batch/{batch.ulid}",
    }


# ---------------------------------------------------------------------------
# GET /batches -- list user's batches (most recent first)
# ---------------------------------------------------------------------------


@router.get("/batches")
async def list_batches(
    cursor: Optional[str] = Query(None),
    limit: int = Query(default=20, le=100),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """List the caller's org's batches, most recent first, cursor-paginated.

    W1 step 3: org-scoped (tenant boundary); never leaks another org's batches.
    """
    stmt = (
        select(Batch)
        .where(Batch.org_id == caller_org_subquery(user.user_id))
        .order_by(Batch.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        stmt = stmt.where(Batch.id < int(cursor))

    rows = (await session.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    batches = rows[:limit]

    return {
        "batches": [
            {
                "batch_ulid": b.ulid,
                "status": b.status,
                "total_items": b.total_items,
                "completed_items": b.completed_items,
                "failed_items": b.failed_items,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in batches
        ],
        "next_cursor": str(batches[-1].id) if batches and has_more else None,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# GET /batch/{batch_id} -- progress
# ---------------------------------------------------------------------------


@router.get("/batch/{batch_id}")
async def get_batch_progress(
    batch_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Get batch progress with denormalized counters (D-18)."""
    progress = await batch_service.get_batch_progress(session, batch_id, user.user_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return progress


# ---------------------------------------------------------------------------
# GET /batch/{batch_id}/items -- paginated items
# ---------------------------------------------------------------------------


@router.get("/batch/{batch_id}/items")
async def get_batch_items(
    batch_id: str,
    status: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(default=50, le=200),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Get cursor-paginated batch items with optional status filter (D-19)."""
    # Verify batch ownership (404 not 403, T-09-04)
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.ulid == batch_id,
                Batch.org_id == caller_org_subquery(user.user_id),
            )
        )
    ).scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    cursor_int = int(cursor) if cursor else None
    items, has_more = await batch_service.get_batch_items_page(
        session, batch.id, status_filter=status, cursor=cursor_int, limit=limit
    )

    items_list = [
        {
            "item_ulid": item.ulid,
            "filename": item.filename,
            "status": item.status,
            "priority": item.priority,
            "analysis_id": item.analysis_id,
            "error_message": item.error_message,
            "duration_ms": item.duration_ms,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in items
    ]

    next_cursor = str(items[-1].id) if items and has_more else None

    return {
        "batch_id": batch_id,
        "items": items_list,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


# ---------------------------------------------------------------------------
# GET /batch/{batch_id}/results/csv -- CSV export
# ---------------------------------------------------------------------------


@router.get("/batch/{batch_id}/results/csv")
async def get_batch_results_csv(
    batch_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Stream batch results as CSV download."""
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.ulid == batch_id,
                Batch.org_id == caller_org_subquery(user.user_id),
            )
        )
    ).scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Batch not yet completed (status: {batch.status})",
        )

    csv_generator = batch_service.generate_results_csv(
        session, batch.id, batch.job_type
    )
    return StreamingResponse(
        csv_generator,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=batch_{batch_id}_results.csv"
        },
    )


# ---------------------------------------------------------------------------
# POST /batch/{batch_id}/cancel -- cancel batch
# ---------------------------------------------------------------------------


@router.post("/batch/{batch_id}/cancel")
async def cancel_batch(
    batch_id: str,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Cancel a batch -- skips pending items, does not interrupt in-progress."""
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.ulid == batch_id,
                Batch.org_id == caller_org_subquery(user.user_id),
            )
        )
    ).scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    terminal_statuses = {"completed", "failed", "cancelled"}
    if batch.status in terminal_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Batch already in terminal state: {batch.status}",
        )

    # Cancel batch
    batch.status = "cancelled"

    # Skip all pending/queued items
    pending_items = (
        await session.execute(
            select(BatchItem).where(
                BatchItem.batch_id == batch.id,
                BatchItem.status.in_(["pending", "queued"]),
            )
        )
    ).scalars().all()

    for item in pending_items:
        item.status = "skipped"

    await session.commit()

    return {"batch_id": batch.ulid, "status": "cancelled"}
