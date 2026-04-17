"""Batch API endpoints -- create, status, items, CSV export, cancel.

POST /api/v1/batch          -- create batch (ZIP upload or S3 reference)
GET  /api/v1/batch/{id}     -- batch progress
GET  /api/v1/batch/{id}/items    -- paginated items
GET  /api/v1/batch/{id}/results/csv -- CSV export
POST /api/v1/batch/{id}/cancel   -- cancel batch
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Batch, BatchItem
from src.services import batch_service
from src.services.batch_service import BATCH_MAX_ZIP_BYTES

logger = logging.getLogger("cadverify.batch_router")

router = APIRouter(prefix="/api/v1", tags=["batch"])


# ---------------------------------------------------------------------------
# POST /batch -- create batch
# ---------------------------------------------------------------------------


@router.post("/batch", status_code=202)
async def create_batch(
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
    file: Optional[UploadFile] = File(None),
    webhook_url: Optional[str] = Form(None),
    webhook_secret: Optional[str] = Form(None),
    concurrency_limit: Optional[int] = Form(None),
    s3_bucket: Optional[str] = Form(None),
    s3_prefix: Optional[str] = Form(None),
    manifest_url: Optional[str] = Form(None),
    manifest: Optional[UploadFile] = File(None),
):
    """Create a batch for bulk analysis.

    Accepts either a ZIP file upload or S3 reference fields.
    Returns 202 with batch_id and status URL.
    """
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

    # Create batch row
    batch = await batch_service.create_batch(
        session=session,
        user_id=user.user_id,
        input_mode=input_mode,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        concurrency_limit=concurrency_limit,
        api_key_id=user.api_key_id,
    )

    if input_mode == "zip":
        # Read and validate ZIP
        zip_bytes = await file.read()
        if len(zip_bytes) > BATCH_MAX_ZIP_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"ZIP file exceeds maximum size of {BATCH_MAX_ZIP_BYTES} bytes",
            )

        # Extract files to disk
        items_data = batch_service.extract_zip_to_items(zip_bytes, batch.ulid)

        # Parse manifest CSV if provided
        if manifest is not None:
            manifest_bytes = await manifest.read()
            manifest_items = batch_service.parse_csv_manifest(manifest_bytes.decode("utf-8"))
            # Merge manifest metadata with extracted items by filename
            manifest_map = {m["filename"]: m for m in manifest_items}
            for item in items_data:
                if item.get("status") == "skipped":
                    continue
                meta = manifest_map.get(item["filename"], {})
                item["process_types"] = meta.get("process_types")
                item["rule_pack"] = meta.get("rule_pack")
                item["priority"] = meta.get("priority", "normal")

        # Create batch items
        count = await batch_service.create_batch_items(session, batch.id, items_data)
        batch.total_items = count

    elif input_mode == "s3":
        # Store S3 reference in manifest_json for coordinator
        batch.manifest_json = {
            "s3_bucket": s3_bucket,
            "s3_prefix": s3_prefix,
            "manifest_url": manifest_url,
        }

    await session.commit()

    # Enqueue coordinator task
    from src.jobs.arq_backend import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job("run_batch_coordinator", batch.ulid)

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
    """List user's batches, most recent first, cursor-paginated."""
    stmt = (
        select(Batch)
        .where(Batch.user_id == user.user_id)
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
            select(Batch).where(Batch.ulid == batch_id, Batch.user_id == user.user_id)
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
            select(Batch).where(Batch.ulid == batch_id, Batch.user_id == user.user_id)
        )
    ).scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    if batch.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Batch not yet completed (status: {batch.status})",
        )

    csv_generator = batch_service.generate_results_csv(session, batch.id)
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
            select(Batch).where(Batch.ulid == batch_id, Batch.user_id == user.user_id)
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
