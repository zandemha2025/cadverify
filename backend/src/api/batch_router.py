"""Batch API endpoints -- create, status, items, CSV export, cancel.

POST /api/v1/batch          -- create batch (ZIP upload)
GET  /api/v1/batch/{id}     -- batch progress
GET  /api/v1/batch/{id}/items    -- paginated items
GET  /api/v1/batch/{id}/results/csv -- CSV export
POST /api/v1/batch/{id}/cancel   -- cancel batch
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, cast

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

from src.auth.org_context import caller_org_subquery
from src.auth.org_limits import enforce_org_limits
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Analysis, Batch, BatchItem, DirectUpload
from src.services import batch_service, direct_upload_service
from src.services.batch_service import (
    BATCH_MAX_ZIP_BYTES,
    MAX_BATCH_CONCURRENCY,
    MIN_BATCH_CONCURRENCY,
    ManifestTooLargeError,
    VALID_JOB_TYPES,
    ZipTooLargeError,
    validate_batch_concurrency_limit,
)
from src.services.release_fault_injection import (
    BATCH_FAULT_MODES,
    requested_release_fault,
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
    direct_upload_id: Optional[str] = Form(None),
    webhook_url: Optional[str] = Form(None),
    webhook_secret: Optional[str] = Form(None),
    concurrency_limit: Optional[int] = Form(
        None,
        description="Concurrent item jobs for this batch (1-12; default 10).",
        json_schema_extra={
            "minimum": MIN_BATCH_CONCURRENCY,
            "maximum": MAX_BATCH_CONCURRENCY,
        },
    ),
    job_type: str = Form("dfm"),
    s3_bucket: Optional[str] = Form(None),
    s3_prefix: Optional[str] = Form(None),
    manifest_url: Optional[str] = Form(None),
    manifest: Optional[UploadFile] = File(None),
    _org_limit: None = Depends(enforce_org_limits),
):
    """Create a batch for bulk analysis (job_type=dfm) or should-costing
    (job_type=cost).

    Accepts either the existing proxied ZIP file or a completed, org-scoped
    direct_upload_id. Raw remote object-store references remain unsupported.
    Returns 202 with batch_id and status URL.
    """
    release_test_fault = requested_release_fault(request, BATCH_FAULT_MODES)

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
                "doc_url": error_doc_url("INVALID_JOB_TYPE"),
            },
        )

    try:
        concurrency_limit = validate_batch_concurrency_limit(concurrency_limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_BATCH_CONCURRENCY",
                "message": str(exc),
                "min": MIN_BATCH_CONCURRENCY,
                "max": MAX_BATCH_CONCURRENCY,
                "doc_url": error_doc_url("INVALID_BATCH_CONCURRENCY"),
            },
        ) from exc

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
                "doc_url": error_doc_url("BATCH_COST_NOT_ENABLED"),
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
                "doc_url": error_doc_url("S3_INPUT_UNSUPPORTED"),
            },
        )

    # Determine input mode. A capability ID and a proxied body are mutually
    # exclusive so request ambiguity can never select the less-restrictive path.
    if file is not None and direct_upload_id is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "BATCH_INPUT_CONFLICT",
                "message": "Provide either file or direct_upload_id, not both.",
                "doc_url": error_doc_url("BATCH_INPUT_CONFLICT"),
            },
        )
    if file is not None:
        input_mode = "zip"
    elif direct_upload_id is not None:
        input_mode = "direct_upload"
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "BATCH_INPUT_REQUIRED",
                "message": "Provide either a ZIP file upload or direct_upload_id.",
                "doc_url": error_doc_url("BATCH_INPUT_REQUIRED"),
            },
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
                    "doc_url": error_doc_url("webhook_url_rejected"),
                },
            )

    # Manifests are intentionally small metadata, not another bulk-upload
    # channel. Read both input modes through one authoritative cap before the
    # potentially multi-GiB ZIP is staged; the helper buffers at most cap + 1.
    manifest_bytes: bytes | None = None
    if manifest is not None:
        try:
            manifest_bytes = await batch_service.read_manifest_upload_bounded(
                manifest
            )
        except ManifestTooLargeError as exc:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "BATCH_MANIFEST_TOO_LARGE",
                    "message": str(exc),
                    "doc_url": error_doc_url("BATCH_MANIFEST_TOO_LARGE"),
                },
            ) from exc

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

    # Direct uploads are prepared after the request. Parse the optional
    # manifest now and persist only validated metadata for the worker; request
    # bodies are not available to an asynchronous task.
    direct_manifest_items: list[dict] | None = None
    if input_mode == "direct_upload" and manifest_bytes is not None:
        try:
            direct_manifest_items = batch_service.parse_csv_manifest(
                manifest_bytes.decode("utf-8"),
                validate_cost=job_type == "cost",
            )
        except (UnicodeDecodeError, ValueError) as exc:
            code = "INVALID_COST_MANIFEST" if job_type == "cost" else "INVALID_BATCH_MANIFEST"
            raise HTTPException(
                status_code=400,
                detail={
                    "code": code,
                    "message": str(exc),
                    "doc_url": error_doc_url(code),
                },
            ) from exc

    batch: Batch | None = None
    direct_upload: DirectUpload | None = None
    recovered_attachment = False
    try:
        if input_mode == "direct_upload":
            direct_upload, batch = await direct_upload_service.lock_for_batch_attachment(
                session,
                user_id=user.user_id,
                upload_ulid=direct_upload_id or "",
            )
            recovered_attachment = batch is not None

        # Create batch row
        if not recovered_attachment:
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
        if batch is None:
            raise RuntimeError("batch was not created or recovered")

        if input_mode == "direct_upload" and not recovered_attachment:
            if direct_manifest_items is not None:
                manifest_json = dict(batch.manifest_json or {})
                manifest_json["direct_upload_manifest"] = direct_manifest_items
                batch.manifest_json = manifest_json
            if direct_upload is None:  # defensive: lock branch must set it
                raise RuntimeError("completed direct upload was not locked")
            await direct_upload_service.attach_to_batch(
                session,
                upload=direct_upload,
                batch=batch,
                actor_id=user.user_id,
            )

        if input_mode == "zip":
            if zip_tmp_path is None:  # defensive: upload branch must set it
                raise RuntimeError("batch ZIP temporary file was not created")
            # Extract files to disk (streamed from the temp file, not RAM).
            try:
                items_data = await asyncio.to_thread(
                    batch_service.extract_zip_path_to_items,
                    zip_tmp_path,
                    batch.ulid,
                )
            except ValueError as exc:
                # Bad archive (zip bomb / too many items): reject, don't orphan.
                raise HTTPException(status_code=400, detail=str(exc))

            # Parse manifest CSV if provided
            if manifest_bytes is not None:
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
                                "doc_url": error_doc_url("INVALID_COST_MANIFEST"),
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
        if release_test_fault and not recovered_attachment:
            manifest_json = dict(batch.manifest_json or {})
            manifest_json["release_test_fault"] = release_test_fault
            batch.manifest_json = manifest_json
        await session.commit()
    except direct_upload_service.DirectUploadError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except BaseException:
        if input_mode == "direct_upload":
            await session.rollback()
        if batch is not None and input_mode == "zip":
            try:
                await asyncio.to_thread(batch_service.cleanup_batch_files, batch.ulid)
            except Exception:
                logger.exception("Failed to clean rejected batch blobs for %s", batch.ulid)
        raise
    finally:
        if zip_tmp_path is not None:
            try:
                os.unlink(zip_tmp_path)
            except OSError:
                pass

    # Enqueue either asynchronous direct-ZIP preparation or the existing
    # coordinator. If enqueue fails, terminalize the already committed records
    # rather than leaving pending/preparing work orphaned.
    from src.jobs.arq_backend import get_arq_pool

    # A repeated POST after a lost response returns the original durable batch.
    # Terminal/consumed work needs no publication; active preparation uses the
    # same deterministic job id below, so Redis cannot create duplicate work.
    if (
        recovered_attachment
        and direct_upload is not None
        and (
            direct_upload.status not in {"attached", "preparing", "prepared"}
            or batch.status in {"completed", "failed", "cancelled"}
        )
    ):
        return {
            "batch_id": batch.ulid,
            "status": batch.status,
            "status_url": f"/api/v1/batch/{batch.ulid}",
        }

    try:
        if release_test_fault == "batch_queue":
            raise RuntimeError("record-scoped release fault: batch queue")
        pool = await get_arq_pool()
        if input_mode == "direct_upload":
            if direct_upload is None:
                raise RuntimeError("direct upload attachment was not persisted")
            await pool.enqueue_job(
                "prepare_direct_upload_batch",
                direct_upload.ulid,
                _job_id=f"direct-upload-prepare:{direct_upload.ulid}",
            )
        else:
            await pool.enqueue_job("run_batch_coordinator", batch.ulid)
    except Exception:
        logger.exception(
            "Failed to enqueue batch work for %s; marking failed", batch.ulid
        )
        if recovered_attachment:
            # Do not race a preparation job that may already be running. The
            # accepted batch reference is actionable and another identical POST
            # can safely retry deterministic publication.
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "BATCH_ENQUEUE_FAILED",
                    "message": (
                        "The existing batch could not be rescheduled; retry with "
                        "the same direct_upload_id."
                    ),
                    "doc_url": error_doc_url("BATCH_ENQUEUE_FAILED"),
                    "accepted_batch": {
                        "batch_id": batch.ulid,
                        "status": batch.status,
                        "status_url": f"/api/v1/batch/{batch.ulid}",
                    },
                },
            )
        if input_mode == "direct_upload" and direct_upload is not None:
            await direct_upload_service.mark_attachment_enqueue_failed(
                session,
                upload=direct_upload,
                batch=batch,
                actor_id=user.user_id,
            )
        else:
            batch_service.mark_batch_failed(batch, "enqueue_failed")
        # F-ARCH-1/#3: the batch is failed but its items are still 'pending', so
        # progress (pending_items = total - completed - failed) would advertise
        # work that can never run. Move them to a terminal state so reads agree.
        if input_mode != "direct_upload":
            await batch_service.mark_pending_items_terminal(session, batch.id, "skipped")
        await session.commit()
        if input_mode == "direct_upload" and direct_upload is not None:
            try:
                await direct_upload_service.delete_incoming_object(direct_upload)
                await direct_upload_service.mark_storage_cleaned(
                    session, direct_upload
                )
            except Exception:
                logger.exception(
                    "Failed to clean unscheduled direct upload %s", direct_upload.ulid
                )
        else:
            try:
                await asyncio.to_thread(batch_service.cleanup_batch_files, batch.ulid)
            except Exception:
                logger.exception("Failed to clean unscheduled batch blobs for %s", batch.ulid)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "BATCH_ENQUEUE_FAILED",
                "message": (
                    "Batch was accepted but could not be scheduled (job queue "
                    "unavailable). It has been marked failed; please retry."
                ),
                "doc_url": error_doc_url("BATCH_ENQUEUE_FAILED"),
                "accepted_batch": {
                    "batch_id": batch.ulid,
                    "status": batch.status,
                    "status_url": f"/api/v1/batch/{batch.ulid}",
                },
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
    status_counts = await batch_service.get_batch_item_status_counts(
        session, [batch.id for batch in batches]
    )

    return {
        "batches": [
            {
                "batch_ulid": b.ulid,
                "status": b.status,
                "total_items": b.total_items,
                "completed_items": status_counts.get(b.id, {}).get("completed", 0),
                "failed_items": status_counts.get(b.id, {}).get("failed", 0),
                "skipped_items": status_counts.get(b.id, {}).get("skipped", 0),
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
    """Get batch progress with exact durable item-state counters (D-18)."""
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

    normalized_items: list[tuple[BatchItem, Analysis | None]] = []
    for record in items:
        if isinstance(record, BatchItem):
            normalized_items.append((record, None))
        else:
            normalized_items.append(
                (record[0], cast(Analysis | None, record[1]))
            )

    items_list = []
    for item, analysis in normalized_items:
        result_fields = batch_service.dfm_analysis_result_fields(analysis)
        items_list.append(
            {
                "item_ulid": item.ulid,
                "filename": item.filename,
                "status": item.status,
                "priority": item.priority,
                "analysis_id": item.analysis_id,
                **result_fields,
                "error_message": item.error_message,
                "duration_ms": item.duration_ms,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )

    next_cursor = (
        str(normalized_items[-1][0].id) if normalized_items and has_more else None
    )

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
    """Cancel a batch and terminalize every unfinished item atomically."""
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.ulid == batch_id,
                Batch.org_id == caller_org_subquery(user.user_id),
            ).with_for_update()
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
    batch.completed_at = datetime.now(timezone.utc)

    # Include processing rows. A worker that finishes after this commit refreshes
    # the row, sees ``skipped``, and discards its result. This removes the state
    # where a terminal parent could report pending work forever.
    await batch_service.mark_pending_items_terminal(
        session,
        batch.id,
        "skipped",
    )

    await session.commit()

    return {"batch_id": batch.ulid, "status": "cancelled"}
