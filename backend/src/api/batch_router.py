"""Batch API endpoints -- create, status, items, CSV export, cancel.

POST /api/v1/batch          -- create batch (ZIP upload)
GET  /api/v1/batch/{id}     -- batch progress
GET  /api/v1/batch/{id}/items    -- paginated items
GET  /api/v1/batch/{id}/results/csv -- CSV export
POST /api/v1/batch/{id}/cancel   -- cancel batch
POST /api/v1/catalog-runs        -- catalog run (ZIP + optional parts list),
                                    free for work-email accounts within their allowance
GET  /api/v1/batch/{id}/catalog      -- a catalog run's sorted board
GET  /api/v1/batch/{id}/catalog.csv  -- the board as CSV
"""
from __future__ import annotations

from src.auth.validation_caps import require_paid_access
from src.config.public_urls import error_doc_url

import asyncio
import logging
import os
import re
import zipfile
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
from dataclasses import dataclass

from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.catalog_allowance import (
    CatalogAccess,
    free_catalog_concurrency,
    free_catalog_max_zip_bytes,
    require_catalog_access,
)
from src.auth.free_tool_limits import limit_free_catalog_runs
from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import caller_org_subquery
from src.auth.org_limits import enforce_org_limits
from src.auth.rbac import Role, require_org_writer, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Analysis, Batch, BatchItem, DirectUpload
from src.services import batch_service, catalog_run_service, direct_upload_service
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
# Catalog runs (shared with POST /batch through request.state)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogRunOptions:
    access: CatalogAccess
    material_class: str | None  # the run's material for parts the list doesn't name
    quantity: int  # the run's quantity for parts the list doesn't give one
    max_zip_bytes: int


def _decode_text(data: bytes) -> str:
    """A parts list as text: UTF-8 (with or without BOM), else Windows-1252 (Excel exports)."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _apply_catalog_meta(
    batch: Batch,
    items_data: list[dict],
    run: CatalogRunOptions,
    parts_list: list[dict] | None,
    list_name: str | None,
) -> None:
    """Each part's quantity ladder and material, and the run's facts (catalog_run_service)."""
    catalog_run_service.apply_catalog_meta(
        batch, items_data, free=run.access.free, material_class=run.material_class, quantity=run.quantity,
        parts_list=parts_list, list_name=list_name,
    )


async def _reserve_catalog_run(session: AsyncSession, user_id: int, batch: Batch, run: CatalogRunOptions):
    """Count the run's new parts against the free allowance, atomically with the batch."""
    return await catalog_run_service.reserve_catalog_run(session, user_id, batch, run.access)


# ---------------------------------------------------------------------------
# POST /batch -- create batch
# ---------------------------------------------------------------------------


@router.post("/batch", status_code=202)
async def create_batch(
    request: Request,
    user: AuthedUser = Depends(require_org_writer),
    session: AsyncSession = Depends(get_db_session),
    file: Optional[UploadFile] = File(None),
    direct_upload_id: Optional[str] = Form(None),
    webhook_url: Optional[str] = Form(None),
    webhook_secret: Optional[str] = Form(
        None, description="Required with webhook_url. Shared HMAC signing secret; never returned in batch responses."
    ),
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
    _paid_access: None = Depends(require_paid_access),
):
    """Create a batch for bulk analysis (job_type=dfm) or should-costing
    (job_type=cost).

    Accepts either the existing proxied ZIP file or a completed, org-scoped
    direct_upload_id. Raw remote object-store references remain unsupported.
    Returns 202 with batch_id and status URL.
    """
    release_test_fault = requested_release_fault(request, BATCH_FAULT_MODES)
    # A catalog run arrives through POST /catalog-runs, which checked who may
    # run it and set its options; POST /batch itself never accepts one.
    catalog_run: CatalogRunOptions | None = getattr(request.state, "catalog_run", None)
    max_zip_bytes = catalog_run.max_zip_bytes if catalog_run is not None else BATCH_MAX_ZIP_BYTES

    # W3: validate the job type. Invalid -> 422 structured (mirrors FastAPI's
    # own validation status for an out-of-domain field value).
    job_type = (job_type or "dfm").strip().lower()
    valid_job_types = VALID_JOB_TYPES | ({"catalog"} if catalog_run is not None else set())
    if job_type not in valid_job_types:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_JOB_TYPE",
                "message": (
                    f"job_type must be one of {sorted(VALID_JOB_TYPES)}; "
                    f"got {job_type!r}."
                    + (" Start a catalog run with POST /api/v1/catalog-runs." if job_type == "catalog" else "")
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

    if webhook_url and (not webhook_secret or not webhook_secret.strip()):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WEBHOOK_SECRET_REQUIRED",
                "message": "A webhook signing secret is required when a webhook URL is provided.",
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

    # A catalog run's parts list: files with a quantity and a material each.
    # Parsed before anything is stored, so a list it can't read is a clean 400.
    parts_list: list[dict] | None = None
    if catalog_run is not None and manifest_bytes is not None:
        try:
            list_text = _decode_text(manifest_bytes)
            parts_list = catalog_run_service.parse_parts_list(list_text)
            # Finish, Ra, heat treatment, inspection and certification columns.
            from src.services import parts_list_specs

            parts_list = parts_list_specs.attach(parts_list, list_text)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_PARTS_LIST", "message": str(exc)},
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
            if declared_len is not None and declared_len > max_zip_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Upload Content-Length {declared_len} exceeds maximum "
                        f"ZIP size of {max_zip_bytes} bytes"
                    ),
                )
        try:
            zip_tmp_path = await batch_service.stream_upload_to_tempfile(
                file, max_zip_bytes
            )
        except ZipTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc))

    # Direct uploads are prepared after the request. Parse the optional
    # manifest now and persist only validated metadata for the worker; request
    # bodies are not available to an asynchronous task.
    direct_manifest_items: list[dict] | None = None
    if input_mode == "direct_upload" and manifest_bytes is not None and catalog_run is None:
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
    catalog_reservation = None
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
            if catalog_run is not None:
                # Unpacked on the worker: the run's options go with the batch, and it
                # counts as the account's free run from now (one at a time).
                manifest_json = dict(batch.manifest_json or {})
                manifest_json[catalog_run_service.PENDING_KEY] = catalog_run_service.pending_options(
                    free=catalog_run.access.free, material_class=catalog_run.material_class,
                    quantity=catalog_run.quantity, parts_list=parts_list,
                    list_name=getattr(manifest, "filename", None),
                )
                manifest_json["catalog"] = {"free": catalog_run.access.free,
                                            "material_class": catalog_run.material_class,
                                            "quantity": catalog_run.quantity}
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
            except (ValueError, zipfile.BadZipFile) as exc:
                # Bad archive (not a ZIP / zip bomb / too many items): reject
                # with a clean 400, don't orphan the batch or leak a 500.
                message = str(exc) or "Uploaded file is not a valid ZIP archive"
                raise HTTPException(status_code=400, detail=message)

            if catalog_run is not None:
                _apply_catalog_meta(batch, items_data, catalog_run, parts_list,
                                    getattr(manifest, "filename", None))
            # Parse manifest CSV if provided
            elif manifest_bytes is not None:
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
            if catalog_run is not None:
                catalog_reservation = await _reserve_catalog_run(
                    session, user.user_id, batch, catalog_run
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
        recovered = {
            "batch_id": batch.ulid,
            "status": batch.status,
            "status_url": f"/api/v1/batch/{batch.ulid}",
        }
        if catalog_run is not None:
            recovered.update(job_type="catalog", board_url=f"/api/v1/batch/{batch.ulid}/catalog",
                             parts=None, preparing=False, catalog={"free": catalog_run.access.free, "pending": False})
        return recovered

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
    response = {
        "batch_id": batch.ulid,
        "status": batch.status,
        "status_url": f"/api/v1/batch/{batch.ulid}",
    }
    if catalog_run is not None and input_mode == "direct_upload":
        # The ZIP is unpacked on the worker: the parts and the allowance are known
        # once it's done (GET /batch/{id}/catalog: "preparing", then "parts" and
        # "reservation", or "failure" with the refusal).
        response.update(job_type="catalog", board_url=f"/api/v1/batch/{batch.ulid}/catalog", parts=None,
                        preparing=True, catalog={"free": catalog_run.access.free, "pending": True})
    elif catalog_run is not None:
        response["job_type"] = "catalog"
        response["board_url"] = f"/api/v1/batch/{batch.ulid}/catalog"
        response["parts"] = batch.total_items - (batch.failed_items or 0)
        if catalog_reservation is not None:
            response["catalog"] = {
                "free": True,
                "new": catalog_reservation.new,
                "reruns": catalog_reservation.reruns,
                "cap": catalog_reservation.cap,
                "remaining": catalog_reservation.remaining,
            }
        else:
            response["catalog"] = {"free": False}
    return response


# ---------------------------------------------------------------------------
# POST /catalog-runs -- a catalog run (free for work-email accounts)
# ---------------------------------------------------------------------------


@router.post("/catalog-runs", status_code=202, dependencies=[Depends(require_kill_switch_open)])
async def create_catalog_run(
    request: Request,
    user: AuthedUser = Depends(require_org_writer),
    session: AsyncSession = Depends(get_db_session),
    file: Optional[UploadFile] = File(None, description="ZIP of CAD files (STL, STEP, IGES). The app zips many files or a folder."),
    direct_upload_id: Optional[str] = Form(
        None, description="Instead of file: a completed batch_zip direct upload (POST /api/v1/uploads/multipart)."
    ),
    manifest: Optional[UploadFile] = File(
        None, description="Optional parts list (CSV or a BOM export): file or part number, quantity, material."
    ),
    material_class: Optional[str] = Form(
        None, description="Material for parts the list doesn't name: polymer|aluminum|steel|stainless|titanium."
    ),
    quantity: Optional[int] = Form(None, description="Quantity for parts the list doesn't give one (default 100)."),
    concurrency_limit: Optional[int] = Form(None, description="Parts checked at a time (free runs: at most 4)."),
    access: CatalogAccess = Depends(require_catalog_access),
    _org_limit: None = Depends(enforce_org_limits),
    _free_ceiling: None = Depends(limit_free_catalog_runs),
):
    """Check every part of a catalog against the org's machines, then sort them.

    Each part gets the DFM analysis and the cost decision with the org's
    machines bound, the same two steps as a single-part check, in the worker.
    The result is a board (GET /batch/{id}/catalog): make in-house, buy
    outside, needs a new machine, can't be made as drawn.

    Pilot: unlimited. Work-email accounts: their first FREE_CATALOG_PARTS
    distinct parts free (403 ``catalog_allowance_exceeded`` past that; a part
    run or checked before is free again). Personal email: 403
    ``catalog_run_work_email``. Free runs take a ZIP up to
    FREE_CATALOG_MAX_ZIP_BYTES, check at most FREE_CATALOG_CONCURRENCY parts at
    a time, carry no webhook, and one runs at a time per account.

    The ZIP comes as ``file`` or, for a large one, as ``direct_upload_id``: the
    browser uploaded it to storage in parts (resumably), and it is read from
    there, checksum-verified, into the same path as a posted ZIP.
    """
    if (file is None) == (direct_upload_id is None):
        raise HTTPException(
            status_code=400,
            detail={"code": "BATCH_INPUT_REQUIRED", "message": "Provide either a ZIP file or direct_upload_id."},
        )
    cls = (material_class or "").strip().lower() or None
    if cls is not None and cls not in catalog_run_service.MATERIAL_CLASSES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_MATERIAL_CLASS",
                "message": f"material_class must be one of {list(catalog_run_service.MATERIAL_CLASSES)}.",
            },
        )
    if quantity is not None and not (1 <= quantity <= catalog_run_service.MAX_QUANTITY):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_QUANTITY",
                "message": f"quantity must be a whole number from 1 to {catalog_run_service.MAX_QUANTITY:,}.",
            },
        )
    if access.free:
        concurrency_limit = min(concurrency_limit or free_catalog_concurrency(), free_catalog_concurrency())
        max_zip = min(free_catalog_max_zip_bytes(), BATCH_MAX_ZIP_BYTES)
    else:
        max_zip = BATCH_MAX_ZIP_BYTES
    request.state.catalog_run = CatalogRunOptions(
        access=access,
        material_class=cls,
        quantity=quantity or catalog_run_service.DEFAULT_RUN_QUANTITY,
        max_zip_bytes=max_zip,
    )
    if direct_upload_id is not None:
        return await _catalog_run_from_upload(
            request, user, session, direct_upload_id, max_zip, manifest=manifest, concurrency_limit=concurrency_limit,
        )
    return await create_batch(
        request=request,
        user=user,
        session=session,
        file=file,
        direct_upload_id=None,
        webhook_url=None,
        webhook_secret=None,
        concurrency_limit=concurrency_limit,
        job_type="catalog",
        s3_bucket=None,
        s3_prefix=None,
        manifest_url=None,
        manifest=manifest,
        _org_limit=None,
        _paid_access=None,
    )


async def _catalog_run_from_upload(
    request: Request, user: AuthedUser, session: AsyncSession, upload_ulid: str, max_zip: int, *,
    manifest: Optional[UploadFile], concurrency_limit: Optional[int],
):
    """A catalog run from a ZIP the browser uploaded to storage.

    The request checks what it can without reading the ZIP (the upload is a
    finished batch ZIP of this organization, within this run's size limit, and
    a free account has no other run going), then attaches it to a new run and
    hands it to the worker, as a pilot batch from a stored ZIP: the worker
    downloads it (size and SHA-256 verified), unpacks it with the same
    extraction limits as a posted ZIP, gives each part its quantities and
    material, and reserves the free allowance with the items
    (``batch_tasks.prepare_direct_upload_batch``). A refusal there ends the run
    with the reason kept on it (the board's ``failure``). The answer is 202 with
    ``preparing: true``; posting the same upload again returns the same run.
    """
    from src.auth.catalog_allowance import active_free_run, run_active

    def _http(exc: direct_upload_service.DirectUploadError) -> HTTPException:
        return HTTPException(status_code=exc.status_code, detail=exc.detail)

    try:
        upload, existing = await direct_upload_service.lock_for_batch_attachment(
            session, user_id=user.user_id, upload_ulid=upload_ulid
        )
    except direct_upload_service.DirectUploadError as exc:
        raise _http(exc) from exc
    if upload.purpose != direct_upload_service.PURPOSE_BATCH_ZIP:
        raise HTTPException(status_code=409, detail={"code": "DIRECT_UPLOAD_WRONG_PURPOSE",
                                                     "message": "This upload is a single part; check it with POST /api/v1/checks."})
    if existing is None:
        if upload.expected_size_bytes > max_zip:
            raise HTTPException(status_code=413, detail=f"ZIP of {upload.expected_size_bytes} bytes exceeds the maximum of {max_zip} bytes for this run")
        options: CatalogRunOptions = request.state.catalog_run
        if options.access.free:
            other = await active_free_run(session, user.user_id)
            if other is not None:
                raise run_active(other)
    await session.rollback()  # create_batch takes the upload's lock again, in its own transaction
    return await create_batch(
        request=request, user=user, session=session, file=None, direct_upload_id=upload_ulid,
        webhook_url=None, webhook_secret=None, concurrency_limit=concurrency_limit, job_type="catalog",
        s3_bucket=None, s3_prefix=None, manifest_url=None, manifest=manifest,
        _org_limit=None, _paid_access=None,
    )


def _download_stem(value: str) -> str:
    """A Content-Disposition-safe file stem: letters, digits, ``_ . -`` only."""
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("._")
    return stem[:80] or "batch"


async def _catalog_batch(session: AsyncSession, batch_id: str, user_id: int) -> Batch:
    batch = (
        await session.execute(
            select(Batch).where(
                Batch.ulid == batch_id,
                Batch.org_id == caller_org_subquery(user_id),
                Batch.job_type == "catalog",
            )
        )
    ).scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Catalog run not found")
    return batch


@router.get("/batch/{batch_id}/catalog")
async def get_catalog_board(
    batch_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The run's sorted board: every part's bucket, reason, resources and price.

    Org-scoped like every batch read: another organization's run is a 404.
    Rows appear part by part while the run goes; ``totals`` sums each bucket.
    """
    batch = await _catalog_batch(session, batch_id, user.user_id)
    return await catalog_run_service.build_board(session, batch)


@router.get("/batch/{batch_id}/catalog.csv")
async def get_catalog_board_csv(
    batch_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """The board as CSV, one row per part (a run still going exports what's done)."""
    batch = await _catalog_batch(session, batch_id, user.user_id)
    board = await catalog_run_service.build_board(session, batch)
    body = "".join(catalog_run_service.board_csv_rows(board))
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="catalog_run_{_download_stem(batch.ulid)}.csv"'},
    )


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
                "job_type": b.job_type,
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


@router.get("/batch/{batch_id}/portfolio-verdict")
async def get_batch_portfolio_verdict(
    batch_id: str,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    batch = (await session.execute(select(Batch).where(
        Batch.ulid == batch_id,
        Batch.org_id == caller_org_subquery(user.user_id),
    ))).scalars().first()
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    rows = (await session.execute(
        select(BatchItem.status, Analysis.verdict)
        .outerjoin(Analysis, BatchItem.analysis_id == Analysis.id)
        .where(BatchItem.batch_id == batch.id)
    )).all()
    counts: dict[str, int] = {}
    for status, verdict in rows:
        key = verdict if status == "completed" and verdict in {"pass", "issues", "fail"} else "processing_failed" if status == "failed" else "skipped" if status == "skipped" else "pending"
        counts[key] = counts.get(key, 0) + 1
    return {"batch_id": batch_id, **batch_service.portfolio_verdict(counts, batch.total_items)}


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
            "Content-Disposition": f'attachment; filename="batch_{_download_stem(batch.ulid)}_results.csv"'
        },
    )


# ---------------------------------------------------------------------------
# POST /batch/{batch_id}/cancel -- cancel batch
# ---------------------------------------------------------------------------


@router.post("/batch/{batch_id}/cancel")
async def cancel_batch(
    batch_id: str,
    user: AuthedUser = Depends(require_org_writer),
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
