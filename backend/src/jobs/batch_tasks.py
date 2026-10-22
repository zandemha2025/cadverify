"""Batch arq tasks -- coordinator, item processor, webhook dispatch.

run_batch_coordinator: Drip-feeds items respecting concurrency limit.
run_batch_item: Runs analysis_service.run_analysis per item.
dispatch_webhook: Delivers webhook with retry scheduling.
"""
from __future__ import annotations

import asyncio
import contextvars
import errno
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from arq import Retry
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    OperationalError,
    TimeoutError as SQLAlchemyTimeoutError,
)

from src.auth.require_api_key import AuthedUser
from src.db.engine import get_session_factory
from src.db.models import Batch, BatchItem, DirectUpload
from src.services import compute_budget
from src.services.batch_service import BATCH_ITEM_MAX_ATTEMPTS
from src.storage.base import ObjectNotFoundError

logger = logging.getLogger("cadverify.batch_tasks")

# arq's per-job ceiling for the worker (WorkerSettings.job_timeout): it cancels
# a job at this deadline, so nothing may be designed to outlive it.
JOB_TIMEOUT_SECONDS = 600

# When the current batch item's job started (time.monotonic()): how long it may
# still wait for room in the compute budget is measured from here.
_JOB_STARTED: contextvars.ContextVar[float | None] = contextvars.ContextVar("cadverify_batch_job_started", default=None)


def _item_wait_seconds(work_seconds: float) -> float:
    """How long this item may wait for compute room and still do ``work_seconds`` inside its job.

    Past it the item goes back to the run (``_put_back_for_room``) rather than
    being cancelled by arq mid-wait.
    """
    started = _JOB_STARTED.get() or time.monotonic()
    return compute_budget.job_wait_seconds(started, work_seconds, JOB_TIMEOUT_SECONDS)


async def _put_back_for_room(session, item_ulid: str, *, count_try: bool = False) -> None:
    """No compute room within the item's wait: back to pending, this delivery not counted as a try.

    The coordinator publishes it again on a later tick, in its turn. Nothing
    was computed or saved for it. ``count_try``: its meshing ran out of time on a
    saturated box (``MeshBusy``); that try counts, so a part that never meshes
    still ends after its tries with a plain reason.
    """
    try:
        await session.rollback()
    except Exception:
        pass
    item = (await session.execute(
        select(BatchItem).where(BatchItem.ulid == item_ulid).with_for_update()
    )).scalars().first()
    if item is None or item.status != "processing":
        return
    item.status = "pending"
    item.started_at = None
    item.lease_started_at = None
    if count_try:
        from src.services.batch_service import STOPPED_MID_CHECK

        item.error_message = STOPPED_MID_CHECK
    else:
        item.attempt_count = max(0, int(item.attempt_count or 1) - 1)
        item.error_message = None
    await session.commit()
    logger.info("BatchItem %s %s; back in the run", item_ulid,
                "was too busy to mesh" if count_try else "found no compute room in its wait")

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Coordinator task
# ---------------------------------------------------------------------------


_TERMINAL_BATCH_STATUSES = frozenset({"completed", "failed", "cancelled"})
_BATCH_ITEM_LEASE_FLOOR_SECONDS = 660
_BATCH_ITEM_QUEUE_LEASE_FLOOR_SECONDS = 660
DIRECT_UPLOAD_PREP_MAX_TRIES = 3
try:
    _configured_direct_prep_timeout = int(
        os.getenv("DIRECT_UPLOAD_PREP_TIMEOUT_SECONDS", "1800")
    )
except (TypeError, ValueError):
    _configured_direct_prep_timeout = 1800
# This task intentionally has a function-specific ceiling longer than the
# general ARQ 600-second item timeout.
DIRECT_UPLOAD_PREP_TIMEOUT_SECONDS = max(660, _configured_direct_prep_timeout)


class BatchStorageReadError(RuntimeError):
    """Marks an item failure as originating at the durable-storage boundary."""


def _item_attempt_count(item: BatchItem) -> int:
    value = getattr(item, "attempt_count", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        next_exc = current.__cause__ or current.__context__
        current = next_exc if isinstance(next_exc, BaseException) else None


def _is_retryable_provider_error(exc: BaseException) -> bool:
    """Recognize retryable S3/network responses without importing boto3."""

    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error") or {}
        metadata = response.get("ResponseMetadata") or {}
        code = str(error.get("Code", ""))
        status = metadata.get("HTTPStatusCode")
        if status in {408, 429, 500, 502, 503, 504}:
            return True
        if code in {
            "InternalError",
            "RequestTimeout",
            "RequestTimeoutException",
            "ServiceUnavailable",
            "SlowDown",
            "Throttling",
            "ThrottlingException",
        }:
            return True

    # botocore transport exceptions have stable public class names. Matching
    # them here keeps local-filesystem deployments import-safe without boto3.
    return type(exc).__name__ in {
        "ConnectTimeoutError",
        "ConnectionClosedError",
        "EndpointConnectionError",
        "HTTPClientError",
        "ReadTimeoutError",
    }


def is_transient_batch_item_error(exc: BaseException) -> bool:
    """Return true only for retryable storage or database infrastructure faults.

    CAD/parser/user errors—including compute timeouts and missing artifacts—are
    deliberately terminal. The retry allowlist is narrow so malformed customer
    input is never burned through the worker repeatedly.
    """

    chain = tuple(_exception_chain(exc))
    if any(isinstance(item, ObjectNotFoundError) for item in chain):
        return False

    if any(
        isinstance(
            item,
            (
                DisconnectionError,
                OperationalError,
                SQLAlchemyTimeoutError,
            ),
        )
        for item in chain
    ):
        return True
    if any(
        isinstance(item, DBAPIError) and item.connection_invalidated
        for item in chain
    ):
        return True

    storage_scoped = any(isinstance(item, BatchStorageReadError) for item in chain)
    if not storage_scoped:
        return False
    for item in chain:
        if _is_retryable_provider_error(item):
            return True
        if isinstance(item, (ConnectionError, TimeoutError)):
            return True
        if isinstance(item, OSError) and item.errno in {
            errno.EAGAIN,
            errno.EBUSY,
            errno.ECONNABORTED,
            errno.ECONNRESET,
            errno.EHOSTUNREACH,
            errno.EINTR,
            errno.ENETDOWN,
            errno.ENETUNREACH,
            errno.ETIMEDOUT,
        }:
            return True
    return False


def _transient_retry_delay(attempt_count: int) -> int:
    return min(30, 2 ** max(1, attempt_count))


def direct_upload_prep_concurrency() -> int:
    """Dedicated tempfile/extraction concurrency (default one for 20 GiB disks)."""
    try:
        configured = int(os.getenv("DIRECT_UPLOAD_PREP_CONCURRENCY", "1"))
    except (TypeError, ValueError):
        configured = 1
    return max(1, min(configured, 4))


async def _download_and_extract_direct_upload(
    ctx: dict,
    upload: DirectUpload,
    batch: Batch,
) -> list[dict]:
    """Hold the dedicated permit for the complete ZIP-tempfile lifetime."""
    from src.services import batch_service, direct_upload_service

    semaphore = ctx.get("direct_upload_preparation_semaphore")
    if semaphore is None:
        semaphore = asyncio.Semaphore(direct_upload_prep_concurrency())
        ctx["direct_upload_preparation_semaphore"] = semaphore
    temp_path: str | None = None
    async with semaphore:
        try:
            temp_path = await asyncio.to_thread(
                direct_upload_service.download_to_bounded_tempfile,
                upload,
            )
            return await asyncio.to_thread(
                batch_service.extract_zip_path_to_items,
                temp_path,
                batch.ulid,
            )
        finally:
            # A second 5 GiB download cannot start while this file exists.
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass


async def _clean_direct_upload_blobs(upload: DirectUpload, batch: Batch) -> dict[str, bool]:
    """Best-effort cleanup used by terminal preparation paths."""
    from src.services import batch_service, direct_upload_service

    errors = {"incoming": False, "extracted": False}
    try:
        await direct_upload_service.delete_incoming_object(upload)
    except Exception:
        errors["incoming"] = True
        logger.exception("Failed to delete incoming direct upload %s", upload.ulid)
    try:
        await asyncio.to_thread(batch_service.cleanup_batch_files, batch.ulid)
    except Exception:
        errors["extracted"] = True
        logger.exception("Failed to clean extracted batch %s", batch.ulid)
    return errors


async def _terminalize_direct_upload_preparation(
    upload_ulid: str,
    *,
    code: str,
    message: str,
    detail: dict | None = None,
) -> None:
    """Persist a terminal preparation failure and align parent/item state.

    The batch keeps why (``manifest_json["failure"]``: code, message and any
    details, such as a catalog run's allowance), so the app can say it.
    """
    from src.services import batch_service
    from src.services.audit_service import emit_event

    session_factory = get_session_factory()
    async with session_factory() as session:
        upload = (
            await session.execute(
                select(DirectUpload)
                .where(DirectUpload.ulid == upload_ulid)
                .with_for_update()
            )
        ).scalars().first()
        if upload is None or upload.status in {"consumed", "failed", "aborted", "expired"}:
            return
        batch = (
            await session.execute(
                select(Batch)
                .where(
                    Batch.id == upload.batch_id,
                    Batch.org_id == upload.org_id,
                )
                .with_for_update()
            )
        ).scalars().first()
        if batch is None:
            upload.status = "failed"
            upload.error_code = code
            upload.error_message = message[:500]
            upload.terminal_at = datetime.now(timezone.utc)
            await emit_event(
                session,
                actor_id=upload.user_id,
                action="direct_upload.failed",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={"code": code, "batch_missing": True},
                org_id=upload.org_id,
            )
            await session.commit()
            return

        if batch.status == "completed" and upload.status == "prepared":
            upload.status = "consumed"
            upload.consumed_at = datetime.now(timezone.utc)
            upload.terminal_at = upload.consumed_at
            upload.storage_cleaned_at = upload.consumed_at
            upload.error_code = None
            upload.error_message = None
            await emit_event(
                session,
                actor_id=upload.user_id,
                action="direct_upload.consumed",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={"batch_id": batch.ulid, "recovered_after_enqueue": True},
                org_id=upload.org_id,
            )
            await session.commit()
            return

        # Snapshot while the row lock proves these provider coordinates belong
        # to this exact upload. Cleanup happens before terminal commit so every
        # reachable blob gets an attempt even if the DB mutation later fails.
        cleanup_errors = await _clean_direct_upload_blobs(upload, batch)
        now = datetime.now(timezone.utc)
        upload.status = "failed"
        upload.error_code = code
        upload.error_message = message[:500]
        upload.terminal_at = now
        upload.storage_cleaned_at = (
            now if not cleanup_errors["incoming"] and not cleanup_errors["extracted"] else None
        )
        if batch.status not in _TERMINAL_BATCH_STATUSES:
            batch_service.mark_batch_failed(batch, code.lower())
            manifest = dict(batch.manifest_json or {})
            manifest["failure"] = {**(detail or {}), "code": code, "message": message[:500]}
            batch.manifest_json = manifest
        await batch_service.mark_pending_items_terminal(session, batch.id, "skipped")
        await emit_event(
            session,
            actor_id=upload.user_id,
            action="direct_upload.failed",
            resource_type="direct_upload",
            resource_id=upload.ulid,
            detail={
                "code": code,
                "batch_id": batch.ulid,
                "cleanup_errors": cleanup_errors,
            },
            org_id=upload.org_id,
        )
        await session.commit()


async def _release_direct_upload_preparation_for_retry(
    upload_ulid: str,
    *,
    code: str,
    message: str,
) -> None:
    """Make an interrupted pre-extraction claim schedulable by the next ARQ try."""
    from src.services.audit_service import emit_event

    session_factory = get_session_factory()
    async with session_factory() as session:
        upload = (
            await session.execute(
                select(DirectUpload)
                .where(DirectUpload.ulid == upload_ulid)
                .with_for_update()
            )
        ).scalars().first()
        if upload is None or upload.status in {
            "consumed",
            "failed",
            "aborted",
            "expired",
        }:
            return
        # A prepared upload has durable items and only needs incoming cleanup /
        # coordinator publication retried. Do not discard or re-extract them.
        if upload.status == "preparing":
            upload.status = "attached"
            upload.preparation_started_at = None
        elif upload.status != "prepared":
            return
        upload.error_code = code
        upload.error_message = message[:500]
        await emit_event(
            session,
            actor_id=upload.user_id,
            action="direct_upload.preparation_retry",
            resource_type="direct_upload",
            resource_id=upload.ulid,
            detail={"code": code, "attempt": upload.prepare_attempts},
            org_id=upload.org_id,
        )
        await session.commit()


async def _release_cancelled_direct_upload_preparation(upload_ulid: str) -> None:
    """Cancellation-safe fresh-session lease release for ARQ timeout handling."""
    await _release_direct_upload_preparation_for_retry(
        upload_ulid,
        code="DIRECT_UPLOAD_PREPARATION_CANCELLED",
        message="Direct-upload preparation was interrupted and will be retried.",
    )


async def prepare_direct_upload_batch(ctx: dict, upload_ulid: str) -> None:
    """Prepare one completed S3 ZIP, then start the existing batch coordinator.

    The task is safe under ARQ's at-least-once delivery. Extraction commits a
    durable ``prepared`` checkpoint before provider deletion/queue publication;
    a retry resumes from that checkpoint without creating duplicate items.
    """
    from src.services import batch_service, catalog_run_service, direct_upload_service
    from src.services.audit_service import emit_event

    session_factory = get_session_factory()
    try:
        job_try = max(1, int(ctx.get("job_try", 1)))
    except (TypeError, ValueError):
        job_try = 1

    upload: DirectUpload | None = None
    batch: Batch | None = None
    should_extract = False
    async with session_factory() as session:
        upload = (
            await session.execute(
                select(DirectUpload)
                .where(DirectUpload.ulid == upload_ulid)
                .with_for_update()
            )
        ).scalars().first()
        if upload is None:
            logger.error("DirectUpload %s not found", upload_ulid)
            return
        if upload.status in {"consumed", "failed", "aborted", "expired"}:
            logger.info(
                "DirectUpload %s already %s; duplicate task ignored",
                upload_ulid,
                upload.status,
            )
            return
        batch = (
            await session.execute(
                select(Batch)
                .where(
                    Batch.id == upload.batch_id,
                    Batch.org_id == upload.org_id,
                )
                .with_for_update()
            )
        ).scalars().first()
        if batch is None:
            await session.rollback()
            await _terminalize_direct_upload_preparation(
                upload_ulid,
                code="DIRECT_UPLOAD_BATCH_MISSING",
                message="The batch attached to this direct upload no longer exists.",
            )
            return
        if batch.status == "completed" and upload.status == "prepared":
            upload.status = "consumed"
            upload.consumed_at = datetime.now(timezone.utc)
            upload.terminal_at = upload.consumed_at
            upload.storage_cleaned_at = upload.consumed_at
            upload.error_code = None
            upload.error_message = None
            await emit_event(
                session,
                actor_id=upload.user_id,
                action="direct_upload.consumed",
                resource_type="direct_upload",
                resource_id=upload.ulid,
                detail={"batch_id": batch.ulid, "recovered_after_enqueue": True},
                org_id=upload.org_id,
            )
            await session.commit()
            return
        if batch.status in _TERMINAL_BATCH_STATUSES:
            prior = batch.status
            await session.commit()
            cleanup_errors = await _clean_direct_upload_blobs(upload, batch)
            async with session_factory() as terminal_session:
                current = (
                    await terminal_session.execute(
                        select(DirectUpload)
                        .where(DirectUpload.ulid == upload_ulid)
                        .with_for_update()
                    )
                ).scalars().first()
                if current is not None and current.status not in {"consumed", "failed"}:
                    current.status = "aborted" if prior == "cancelled" else "failed"
                    current.terminal_at = datetime.now(timezone.utc)
                    current.storage_cleaned_at = (
                        current.terminal_at
                        if not cleanup_errors["incoming"]
                        and not cleanup_errors["extracted"]
                        else None
                    )
                    current.error_code = "DIRECT_UPLOAD_BATCH_TERMINAL"
                    current.error_message = f"Attached batch became {prior}."
                    await emit_event(
                        terminal_session,
                        actor_id=current.user_id,
                        action="direct_upload.aborted" if prior == "cancelled" else "direct_upload.failed",
                        resource_type="direct_upload",
                        resource_id=current.ulid,
                        detail={"batch_status": prior, "cleanup_errors": cleanup_errors},
                        org_id=current.org_id,
                    )
                    await terminal_session.commit()
            return

        if upload.status == "prepared":
            should_extract = False
        elif upload.status == "attached":
            should_extract = True
        elif upload.status == "preparing":
            started = upload.preparation_started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            lease_seconds = max(60, DIRECT_UPLOAD_PREP_TIMEOUT_SECONDS + 60)
            lease_stale = started is None or started <= (
                datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)
            )
            # A larger ARQ try number proves the previous attempt ended; a stale
            # lease recovers hard process death. Otherwise this is concurrent
            # duplicate delivery and must not perform the external work twice.
            if job_try <= upload.prepare_attempts and not lease_stale:
                logger.info("DirectUpload %s preparation already active", upload_ulid)
                return
            should_extract = True
        else:
            unexpected_status = upload.status
            await session.rollback()
            await _terminalize_direct_upload_preparation(
                upload_ulid,
                code="DIRECT_UPLOAD_INVALID_PREPARATION_STATE",
                message=f"Direct upload entered unexpected state {unexpected_status}.",
            )
            return

        if should_extract:
            upload.status = "preparing"
            upload.prepare_attempts = max(upload.prepare_attempts + 1, job_try)
            upload.preparation_started_at = datetime.now(timezone.utc)
            upload.error_code = None
            upload.error_message = None
            batch.status = "extracting"
            # One durable heartbeat explains the visible extracting state and
            # anchors orphan recovery to this preparation attempt.
            batch_service.touch_batch_heartbeat(batch)
            await session.commit()

    temp_path: str | None = None
    try:
        if should_extract:
            if upload is None or batch is None:
                raise RuntimeError("direct-upload preparation snapshot missing")
            items_data = await _download_and_extract_direct_upload(
                ctx, upload, batch
            )
            manifest_items = (batch.manifest_json or {}).get("direct_upload_manifest")
            if manifest_items:
                batch_service.merge_manifest_metadata(
                    items_data,
                    list(manifest_items),
                    job_type=batch.job_type,
                )

            async with session_factory() as session:
                current_upload = (
                    await session.execute(
                        select(DirectUpload)
                        .where(DirectUpload.ulid == upload_ulid)
                        .with_for_update()
                    )
                ).scalars().first()
                if current_upload is None:
                    raise RuntimeError("direct upload disappeared during preparation")
                current_batch = (
                    await session.execute(
                        select(Batch)
                        .where(
                            Batch.id == current_upload.batch_id,
                            Batch.org_id == current_upload.org_id,
                        )
                        .with_for_update()
                    )
                ).scalars().first()
                if current_batch is None:
                    raise RuntimeError("attached batch disappeared during preparation")
                if current_upload.status == "prepared":
                    # Another legitimate retry won the durable checkpoint.
                    await session.rollback()
                elif current_upload.status != "preparing":
                    raise RuntimeError(
                        f"direct upload changed to {current_upload.status} during preparation"
                    )
                elif current_batch.status in _TERMINAL_BATCH_STATUSES:
                    raise RuntimeError(
                        f"batch changed to {current_batch.status} during preparation"
                    )
                else:
                    # Defensive idempotency for a transaction replay: no
                    # coordinator has run while the batch is `preparing`, so any
                    # rows here are an incomplete prior preparation checkpoint.
                    await session.execute(
                        delete(BatchItem).where(BatchItem.batch_id == current_batch.id)
                    )
                    if current_batch.job_type == "catalog":
                        # A catalog run from a stored ZIP: each part's quantities
                        # and material, from the options its request kept.
                        catalog_run_service.prepare_items(current_batch, items_data)
                    count = await batch_service.create_batch_items(
                        session,
                        current_batch.id,
                        items_data,
                    )
                    current_batch.total_items = count
                    current_batch.completed_items = 0
                    current_batch.failed_items = sum(
                        1
                        for item in items_data
                        if item.get("status") in {"failed", "skipped"}
                    )
                    current_batch.input_mode = "zip"
                    current_batch.status = "pending"
                    if current_batch.job_type == "catalog":
                        # The free allowance counts the run's new parts with its
                        # items, in this transaction; a refusal rolls both back
                        # and ends the preparation (CatalogRunRefused).
                        await session.flush()
                        await catalog_run_service.reserve_prepared_run(session, current_batch)
                    current_upload.status = "prepared"
                    current_upload.prepared_at = datetime.now(timezone.utc)
                    current_upload.checksum_verified_at = current_upload.prepared_at
                    current_upload.error_code = None
                    current_upload.error_message = None
                    await emit_event(
                        session,
                        actor_id=current_upload.user_id,
                        action="direct_upload.prepared",
                        resource_type="direct_upload",
                        resource_id=current_upload.ulid,
                        detail={"batch_id": current_batch.ulid, "item_count": count},
                        org_id=current_upload.org_id,
                    )
                    await session.commit()
                    upload = current_upload
                    batch = current_batch

        if upload is None or batch is None:
            raise RuntimeError("direct-upload preparation state missing")

        # This delete is deliberately before coordinator publication: item jobs
        # read only extracted batch blobs, so the original customer ZIP is no
        # longer needed once the durable prepared checkpoint exists.
        await direct_upload_service.delete_incoming_object(upload)

        pool = ctx.get("redis") or ctx.get("pool")
        if pool is None:
            from src.jobs.arq_backend import get_arq_pool

            pool = await get_arq_pool()
        await pool.enqueue_job(
            "run_batch_coordinator",
            batch.ulid,
            _job_id=f"batch-coordinator:{batch.ulid}",
        )

        async with session_factory() as session:
            current_upload = (
                await session.execute(
                    select(DirectUpload)
                    .where(DirectUpload.ulid == upload_ulid)
                    .with_for_update()
                )
            ).scalars().first()
            if current_upload is None or current_upload.status == "consumed":
                return
            if current_upload.status != "prepared":
                raise RuntimeError(
                    f"direct upload changed to {current_upload.status} before consumption"
                )
            current_upload.status = "consumed"
            current_upload.consumed_at = datetime.now(timezone.utc)
            current_upload.terminal_at = current_upload.consumed_at
            current_upload.storage_cleaned_at = current_upload.consumed_at
            current_upload.error_code = None
            current_upload.error_message = None
            await emit_event(
                session,
                actor_id=current_upload.user_id,
                action="direct_upload.consumed",
                resource_type="direct_upload",
                resource_id=current_upload.ulid,
                detail={"batch_id": batch.ulid},
                org_id=current_upload.org_id,
            )
            await session.commit()

    except asyncio.CancelledError:
        try:
            await asyncio.shield(
                _release_cancelled_direct_upload_preparation(upload_ulid)
            )
        except Exception:
            logger.exception(
                "Failed to release cancelled DirectUpload %s", upload_ulid
            )
        raise
    except BaseException as exc:
        code, message, retryable = direct_upload_service.preparation_error(exc)
        logger.exception(
            "DirectUpload %s preparation failed (%s, try=%d)",
            upload_ulid,
            code,
            job_try,
        )
        final = not retryable or job_try >= DIRECT_UPLOAD_PREP_MAX_TRIES
        if final:
            await _terminalize_direct_upload_preparation(
                upload_ulid,
                code=code,
                message=message,
                detail=getattr(exc, "refusal", None),
            )
            return
        await _release_direct_upload_preparation_for_retry(
            upload_ulid,
            code=code,
            message=message,
        )
        raise
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _batch_item_lease_seconds() -> int:
    """Return the stale-processing lease used by coordinator recovery.

    The arq worker hard-cancels jobs after 600 seconds. Reclaiming only after a
    60-second safety margin prevents overlapping a legitimately running job,
    while still making a worker crash or failed cancellation self-healing.
    Operators may lengthen, but never shorten, this safety boundary.
    """
    from src.services.batch_service import batch_item_lease_seconds

    return batch_item_lease_seconds()


def _batch_item_queue_lease_seconds() -> int:
    """Return how long a published item may wait before queue recovery.

    Queue wait is intentionally much longer than the processing lease: many
    healthy batches can share the 12 worker slots, so a delayed Redis message is
    not equivalent to a worker that exceeded its hard 600-second runtime.
    """

    try:
        configured = int(os.getenv("BATCH_ITEM_QUEUE_LEASE_SECONDS", str(6 * 3600)))
    except (TypeError, ValueError):
        configured = 6 * 3600
    return max(_BATCH_ITEM_QUEUE_LEASE_FLOOR_SECONDS, configured)


# ---------------------------------------------------------------------------
# The coordinator chain: one live chain per batch, that a failed tick never ends
# ---------------------------------------------------------------------------
#
# Each tick is its own arq job and queues the next. The chain's state lives in
# Redis (``_chain_key``): which chain owns the batch, its tick number, and when
# it last ticked. Three rules keep exactly one chain going:
#
#   * The next tick's job id is ``batch-coordinator:{batch}:{chain}:{seq}``, so
#     a tick that runs twice (arq re-runs a tick cancelled at shutdown; the
#     failure path below already queued its successor) queues its successor
#     once: arq refuses a job id that is queued or recently finished.
#   * A start without a chain (the API, a re-check, a resume, a kick, or a job
#     queued before chains existed) takes the batch over with a new chain; the
#     old chain's next tick sees another owner and stops.
#   * A tick that fails (a DB connect timing out under load, the job timeout, a
#     worker shutdown) still queues the next tick, a little later. The minute
#     cron ``rekick_batch_coordinators`` starts a chain for any running batch
#     whose chain hasn't ticked for a while (its next job was lost with Redis).

_CHAIN_TTL_SECONDS = 14 * 24 * 3600


def _chain_key(batch_ulid: str) -> str:
    return f"cadverify:batch-coordinator:{batch_ulid}"


def _coordinator_stale_seconds() -> int:
    """How long a running batch may go without a tick before the cron starts a coordinator."""
    try:
        configured = int(os.getenv("BATCH_COORDINATOR_STALE_SECONDS", "120"))
    except (TypeError, ValueError):
        configured = 120
    return max(30, configured)


def _coordinator_retry_delay(failures: int) -> int:
    """5, 10, 20, 40, then 60 s between ticks after consecutive failed ticks."""
    return min(60, 5 * 2 ** max(0, min(failures, 4)))


async def _chain_state(pool, batch_ulid: str) -> dict | None:
    """The batch's chain state from Redis, or None (no state, or a pool without get)."""
    getter = getattr(pool, "get", None)
    if getter is None:
        return None
    try:
        raw = await getter(_chain_key(batch_ulid))
    except Exception:
        logger.warning("Could not read the coordinator chain of batch %s", batch_ulid, exc_info=True)
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str):
        return None
    try:
        state = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(state, dict) or not isinstance(state.get("chain"), str):
        return None
    return state


async def _write_chain_state(pool, batch_ulid: str, chain: str, seq: int) -> None:
    setter = getattr(pool, "set", None)
    if setter is None:
        return
    try:
        await setter(
            _chain_key(batch_ulid),
            json.dumps({"chain": chain, "seq": seq, "at": time.time()}),
            ex=_CHAIN_TTL_SECONDS,
        )
    except Exception:
        logger.warning("Could not record the coordinator chain of batch %s", batch_ulid, exc_info=True)


async def _queue_next_tick(pool, batch_ulid: str, chain: str, seq: int, *, defer: int, failures: int) -> None:
    """Queue tick ``seq + 1`` of this chain (once, whoever asks: the job id is the tick)."""
    if pool is None:
        return
    next_seq = seq + 1
    await _write_chain_state(pool, batch_ulid, chain, next_seq)
    await pool.enqueue_job(
        "run_batch_coordinator",
        batch_ulid,
        chain=chain,
        seq=next_seq,
        failures=failures,
        _job_id=f"batch-coordinator:{batch_ulid}:{chain}:{next_seq}",
        _defer_by=defer,
    )


async def run_batch_coordinator(
    ctx: dict,
    batch_ulid: str,
    chain: str | None = None,
    seq: int = 0,
    failures: int = 0,
) -> None:
    """One tick of the batch's coordinator chain; a failed tick still queues the next.

    See the chain rules above. ``chain``/``seq`` name this tick; a call
    without them starts a chain (and takes the batch over from any other).
    ``failures`` counts the failed ticks just before this one, for the delay.
    """
    pool = ctx.get("redis") or ctx.get("pool")
    poll_interval = int(os.getenv("BATCH_POLL_INTERVAL_SECONDS", "2"))
    if chain is None:
        chain = uuid.uuid4().hex[:16]
        seq = 0
        if pool is not None:
            await _write_chain_state(pool, batch_ulid, chain, seq)
    elif pool is not None:
        state = await _chain_state(pool, batch_ulid)
        if state is not None and state.get("chain") != chain:
            logger.info("Batch %s coordinator chain %s superseded; stopping it", batch_ulid, chain)
            return

    retry_in = _coordinator_retry_delay(failures)
    try:
        more = await _coordinator_tick(ctx, batch_ulid)
    except asyncio.CancelledError:
        # arq's job timeout, or a worker shutting down. The next tick goes on
        # the queue first (its job id makes a re-run of this tick harmless).
        try:
            await asyncio.shield(
                _queue_next_tick(pool, batch_ulid, chain, seq, defer=retry_in, failures=failures + 1)
            )
        except BaseException:
            logger.exception("Batch %s: the tick after a cancelled one could not be queued", batch_ulid)
        raise
    except Exception:
        logger.warning(
            "Batch %s coordinator tick failed (%d in a row); the next tick runs in %d s",
            batch_ulid, failures + 1, retry_in, exc_info=True,
        )
        try:
            await _queue_next_tick(pool, batch_ulid, chain, seq, defer=retry_in, failures=failures + 1)
        except Exception:
            logger.exception("Batch %s: the tick after a failed one could not be queued", batch_ulid)
        raise
    if more:
        # Outside the session so no DB connection is pinned across the poll
        # interval. Without a pool (unit tests) the chain simply stops here.
        await _queue_next_tick(pool, batch_ulid, chain, seq, defer=poll_interval, failures=0)


async def rekick_batch_coordinators(ctx: dict) -> int:
    """arq cron (every minute): start a coordinator for a running batch whose chain stopped.

    A running batch (pending or processing, its parts unpacked) whose chain
    hasn't ticked for ``BATCH_COORDINATOR_STALE_SECONDS`` gets a new chain. The
    kick's job id carries the stalled chain's tick, so a minute later it isn't
    queued twice; a chain that was only slow stops when the new one starts.
    Off-switch: BATCH_COORDINATOR_REKICK_ENABLED=0.
    """
    if not _flag("BATCH_COORDINATOR_REKICK_ENABLED", "1"):
        return 0
    pool = ctx.get("redis") or ctx.get("pool")
    if pool is None:
        return 0
    stale = _coordinator_stale_seconds()
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Batch.ulid, Batch.created_at, Batch.started_at).where(
                    Batch.status.in_(["pending", "processing"]),
                    Batch.input_mode == "zip",
                )
            )
        ).all()
    now = time.time()
    kicked = 0
    for batch_ulid, created_at, started_at in rows:
        state = await _chain_state(pool, batch_ulid)
        if state is not None:
            try:
                at = float(state.get("at") or 0)
            except (TypeError, ValueError):
                at = 0.0
            if now - at < stale:
                continue
            stalled = f"{state['chain']}:{state.get('seq')}"
        else:
            anchor = started_at or created_at
            if anchor is not None:
                if anchor.tzinfo is None:
                    anchor = anchor.replace(tzinfo=timezone.utc)
                if now - anchor.timestamp() < stale:
                    continue
            stalled = "none"
        job = await pool.enqueue_job(
            "run_batch_coordinator", batch_ulid, _job_id=f"batch-coordinator-kick:{batch_ulid}:{stalled}"
        )
        if job is not None:
            kicked += 1
            logger.warning("Batch %s had no coordinator tick for %d s or more; started one", batch_ulid, stale)
    return kicked


async def _coordinator_tick(ctx: dict, batch_ulid: str) -> bool:
    """Run ONE coordination tick; True when the batch has work left (F-ARCH-6/#1).

    This is deliberately NOT a while-True poller. arq wraps every job in
    ``asyncio.wait_for(task, job_timeout)`` (arq/worker.py), so a job designed to
    live for a batch's whole lifetime (hours) is *cancelled* at ``job_timeout``.
    On py3.9 ``asyncio.CancelledError`` is a ``BaseException``, not an
    ``Exception``, so an ``except Exception`` cleanup handler never runs and the
    batch is orphaned in 'processing'. We remove the long-lived job entirely:

      * Each invocation performs a single short poll ("tick"): drip-feed pending
        items up to the concurrency limit, refresh the coordinator heartbeat, and
        finalize once every item is terminal.
      * If more work remains, the tick re-enqueues *itself* deferred by the poll
        interval. The chain of short jobs replaces the loop -- every job now
        finishes in milliseconds, far inside ``job_timeout``, so the cancellation
        window is designed out rather than patched around.
      * Recovery: ``run_batch_coordinator`` queues the next tick even when this
        one fails or is cancelled, the minute cron restarts a chain that stopped,
        and the orphan sweep resumes a batch that made no progress before it
        ever fails one (a run ends only when it can't be resumed).
    """
    from src.services import batch_service

    session_factory = get_session_factory()
    pool = ctx.get("redis") or ctx.get("pool")

    async with session_factory() as session:
        batch = (
            await session.execute(
                select(Batch).where(Batch.ulid == batch_ulid).with_for_update()
            )
        ).scalars().first()
        if batch is None:
            logger.error("Batch %s not found", batch_ulid)
            return False
        batch_id = batch.id

        # Terminal already (cancelled/failed/completed): stop the chain without
        # overwriting the status. Cancellation is driven by the cancel endpoint.
        if batch.status in _TERMINAL_BATCH_STATUSES:
            logger.info(
                "Batch %s already %s; coordinator stopping", batch_ulid, batch.status
            )
            return False

        # First tick: pending -> processing. total_items is authoritative from the
        # router, but recompute defensively so the coordinator is self-consistent.
        if batch.status == "pending":
            batch.status = "processing"
            batch.started_at = datetime.now(timezone.utc)
            batch.total_items = (
                await session.execute(
                    select(func.count(BatchItem.id)).where(
                        BatchItem.batch_id == batch_id
                    )
                )
            ).scalar() or 0

        total = batch.total_items
        done_count = batch.completed_items + batch.failed_items

        # Finalize: nothing to do (empty batch) or every item is terminal.
        if total == 0 or done_count >= total:
            batch.status = "completed"
            batch.completed_at = datetime.now(timezone.utc)

            if batch.webhook_url:
                from src.services import webhook_service

                payload = {
                    "event": "batch.completed",
                    "batch_id": batch.ulid,
                    "status": batch.status,
                    "total_items": batch.total_items,
                    "completed_items": batch.completed_items,
                    "failed_items": batch.failed_items,
                }
                delivery = await webhook_service.create_webhook_delivery(
                    session, batch.id, "batch.completed", payload
                )
                await session.commit()
                if pool is not None:
                    await pool.enqueue_job("dispatch_webhook", delivery.id)
            else:
                await session.commit()

            logger.info(
                "Batch %s coordinator done: status=%s total=%d completed=%d failed=%d",
                batch_ulid, batch.status, batch.total_items,
                batch.completed_items, batch.failed_items,
            )
            if batch.job_type == "catalog":
                await _notify_run_finished(batch_ulid)
            return False  # terminal -> do NOT re-enqueue; the chain stops here

        # Steady state: refresh heartbeat + drip-feed pending items up to the
        # concurrency limit. The heartbeat proves to the sweeper we are alive.
        batch_service.touch_batch_heartbeat(batch)

        # A worker can be SIGKILLed or lose its cancellation cleanup after it
        # durably claims an item. Reclaim only processing rows whose lease is
        # older than the worker's hard 600s timeout plus a safety margin. The
        # pending-item query below will then enqueue the recovered work in this
        # same tick. A NULL started_at on a processing row is invalid durable
        # state and is likewise safe to recover.
        lease_now = datetime.now(timezone.utc)
        recovery = await batch_service.recover_stale_batch_item_leases(
            session,
            batch,
            processing_cutoff=lease_now
            - timedelta(seconds=_batch_item_lease_seconds()),
            queued_cutoff=lease_now
            - timedelta(seconds=_batch_item_queue_lease_seconds()),
            now=lease_now,
        )
        if recovery.requeued_ulids:
            logger.warning(
                "Reclaimed %d expired batch-item lease(s) for batch %s: %s",
                len(recovery.requeued_ulids),
                batch_ulid,
                ", ".join(recovery.requeued_ulids),
            )
        if recovery.exhausted_ulids:
            logger.error(
                "Terminalized %d retry-exhausted batch item(s) for batch %s: %s",
                len(recovery.exhausted_ulids),
                batch_ulid,
                ", ".join(recovery.exhausted_ulids),
            )

        active_count = (
            await session.execute(
                select(func.count(BatchItem.id)).where(
                    BatchItem.batch_id == batch_id,
                    BatchItem.status.in_(["queued", "processing"]),
                )
            )
        ).scalar() or 0

        concurrency_limit = batch_service.validate_batch_concurrency_limit(
            batch.concurrency_limit
        )
        slots = concurrency_limit - active_count
        queued_jobs: list[tuple[str, int]] = []
        if slots > 0 and pool is not None:
            pending_items = (
                await session.execute(
                    select(BatchItem)
                    .where(
                        BatchItem.batch_id == batch_id,
                        BatchItem.status == "pending",
                    )
                    .order_by(
                        case(
                            (BatchItem.priority == "high", 0),
                            (BatchItem.priority == "normal", 1),
                            (BatchItem.priority == "low", 2),
                            else_=3,
                        ).asc(),
                        BatchItem.created_at.asc(),
                        BatchItem.id.asc(),
                    )
                    .limit(slots)
                )
            ).scalars().all()

            for item in pending_items:
                attempts = _item_attempt_count(item)
                if attempts >= BATCH_ITEM_MAX_ATTEMPTS:
                    item.status = "failed"
                    item.completed_at = lease_now
                    item.lease_started_at = None
                    item.error_message = batch_service.exhausted_reason(item)
                    batch.failed_items = int(batch.failed_items or 0) + 1
                    continue
                item.status = "queued"
                item.attempt_count = attempts + 1
                item.lease_started_at = lease_now
                defer_by = {"high": 0, "normal": 1, "low": 2}[item.priority]
                queued_jobs.append((item.ulid, defer_by))

        # Queue state must be visible before a worker can consume the message.
        # Publishing first lets a fast worker see `pending`/`processing`, exit as
        # a duplicate, and leave a permanently active `queued` row after commit.
        await session.commit()

        # Redis is at-least-once and an enqueue response can fail after partial
        # publication. A conditional reset is safe in every ordering: a worker
        # that already claimed the row changed it to `processing`; otherwise the
        # next coordinator tick can publish the restored `pending` row again.
        for item_ulid, defer_by in queued_jobs:
            try:
                if pool is None:
                    raise RuntimeError(
                        "Batch item was queued without an available Redis pool"
                    )
                await pool.enqueue_job(
                    "run_batch_item", item_ulid, _defer_by=defer_by
                )
            except Exception:
                logger.exception(
                    "Could not publish BatchItem %s; restoring queued lease",
                    item_ulid,
                )
                await session.execute(
                    update(BatchItem)
                    .where(
                        BatchItem.ulid == item_ulid,
                        BatchItem.status == "queued",
                    )
                    .values(
                        status="pending",
                        started_at=None,
                        lease_started_at=None,
                    )
                )
                await session.commit()

    # Work remains: the caller queues the next tick outside this session.
    return True


async def _notify_run_finished(batch_ulid: str) -> None:
    """One notification when a catalog run finishes, with its answer in counts.

    Its parts' records don't notify one by one (a run of 50 was 50 "Check
    recorded" rows). Best effort: a failure here never touches the run.
    """
    from src.services import catalog_run_service, notification_service

    try:
        async with get_session_factory()() as session:
            batch = (await session.execute(select(Batch).where(Batch.ulid == batch_ulid))).scalars().first()
            if batch is None:
                return
            board = await catalog_run_service.build_board(session, batch)
            a = board.get("answer") or {}
            bits = [f"{a.get('make', 0)} make in-house", f"{a.get('buy', 0)} buy"]
            for key, words in (("new_machine", "need a new machine"), ("cant_make", "can't be made as drawn"),
                               ("not_checked", "not checked")):
                if a.get(key):
                    bits.append(f"{a[key]} {words}")
            if a.get("saving_usd") is not None:
                bits.append(f"saves ${a['saving_usd']:,.0f} against what you pay today")
            name = board.get("name") or "Catalog run"
            # A run that stopped and was checked again has finished after all.
            await notification_service.resolve_by_source(
                session, org_id=batch.org_id, source_type="catalog_run", source_id=batch.ulid,
                kind="catalog.run_stopped",
            )
            await notification_service.emit_notification(
                session, org_id=batch.org_id, actor_user_id=batch.user_id, kind="catalog.run_finished",
                severity="info" if a.get("not_checked") else "pass",
                title=f"Catalog run finished - {name}", body=" · ".join(bits), dest="verify",
                source_type="catalog_run", source_id=batch.ulid,
                metadata={"batch_id": batch.ulid, "name": board.get("name"), "parts": a.get("parts"),
                          "answer": {k: a.get(k) for k in ("make", "buy", "new_machine", "cant_make",
                                                            "not_checked", "saving_usd")}},
            )
            await session.commit()
    except Exception:
        logger.warning("Run-finished notification not sent for %s", batch_ulid, exc_info=True)


async def _notify_run_stopped(batch_ulid: str) -> None:
    """One notification when a catalog run stops before every part was checked.

    Says how many were checked and how many weren't, and that they can be
    checked again (the run's page). Best effort: a failure here never touches
    the run. Idempotent per run (the inbox keeps one row per source).
    """
    from src.services import batch_service, notification_service
    from src.services.catalog_run_service import run_meta

    try:
        async with get_session_factory()() as session:
            batch = (await session.execute(select(Batch).where(Batch.ulid == batch_ulid))).scalars().first()
            if batch is None or batch.job_type != "catalog":
                return
            # The run page's own breakdown (op-28) and the reason the run kept (op-25).
            c = (await batch_service.catalog_run_counts(session, [batch])).get(batch.id) or {}
            total = int(c.get("total") or 0) + int(c.get("unlisted") or 0)
            checked = int(c.get("checked") or 0) + int(c.get("unlisted_checked") or 0)
            not_checked = total - checked
            name = run_meta(batch).get("name") or "Catalog run"
            failure = (batch.manifest_json or {}).get("failure") or {}
            left = int(c.get("not_checked") or 0) + int(c.get("to_go") or 0)
            line = f"{int(c.get('checked') or 0):,} of {int(c.get('total') or 0):,} checked; {left:,} not checked"
            if c.get("unlisted"):
                u = int(c["unlisted"])
                line += f"; {u:,} {'file isn’t' if u == 1 else 'files aren’t'} on your parts list"
            why = failure.get("message")
            body = (f"{line}. {why}" if why else
                    f"{line}. Check {'it' if left == 1 else 'them'} again on the run's page.")
            await notification_service.emit_notification(
                session, org_id=batch.org_id, actor_user_id=batch.user_id, kind="catalog.run_stopped",
                severity="cond", title=f"Catalog run stopped - {name}", body=body, dest="verify",
                source_type="catalog_run", source_id=batch.ulid,
                metadata={"batch_id": batch.ulid, "name": name, "parts": total, "checked": checked,
                          "not_checked": not_checked, "reason": failure.get("message")},
            )
            await session.commit()
    except Exception:
        logger.warning("Run-stopped notification not sent for %s", batch_ulid, exc_info=True)


# ---------------------------------------------------------------------------
# Orphan sweeper (F-ARCH-1)
# ---------------------------------------------------------------------------


async def sweep_orphaned_batches(ctx: dict) -> int:
    """arq cron: resume batches that stopped making progress; fail only those that can't go on.

    Backstops the reject-don't-orphan path in POST /batch: if the API crashed
    between committing the batch and enqueuing its coordinator (or the
    coordinator died mid-run), the batch would sit 'pending'/'processing'
    forever. A stale batch whose parts are stored is resumed (stuck parts back
    in the run, a new coordinator); one that can't be resumed is marked failed
    with reason 'orphaned', each skipped part says why, and a catalog run's
    owner gets one notification that it stopped.

    Off-switch: BATCH_ORPHAN_SWEEP_ENABLED=0.
    """
    if not _flag("BATCH_ORPHAN_SWEEP_ENABLED", "1"):
        return 0

    from src.services import batch_service

    resumed: list[str] = []
    stopped: list[str] = []
    session_factory = get_session_factory()
    async with session_factory() as session:
        reaped = await batch_service.sweep_orphaned_batches(
            session, resumed=resumed, stopped=stopped
        )
        if reaped or resumed:
            # Commit while the session context is alive. Committing after
            # __aexit__ silently loses the durable reaping transaction with a
            # real AsyncSession even though a loose mock appears to accept it.
            await session.commit()
    pool = ctx.get("redis") or ctx.get("pool")
    for batch_ulid in resumed:
        # A new chain takes the batch over (any old one stops at its next tick).
        try:
            if pool is None:
                from src.jobs.arq_backend import get_arq_pool

                pool = await get_arq_pool()
            await pool.enqueue_job("run_batch_coordinator", batch_ulid)
        except Exception:
            # The minute cron starts one when Redis is back.
            logger.exception("Resumed batch %s, but its coordinator could not be queued", batch_ulid)
    for batch_ulid in stopped:
        await _notify_run_stopped(batch_ulid)
    if reaped:
        from src.api.metrics_registry import record_orphan_sweep

        record_orphan_sweep(reaped)
        logger.warning("Orphan sweep reaped %d stuck batch(es)", reaped)
    return reaped


async def reconcile_terminal_batch_items(ctx: dict) -> int:
    """ARQ cron: remove non-terminal children from terminal batches.

    The cancel endpoint performs the same transition synchronously; this is the
    durable backstop for process death and state written by older releases.
    """

    if not _flag("BATCH_TERMINAL_RECONCILE_ENABLED", "1"):
        return 0

    from src.services import batch_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        reconciled = await batch_service.reconcile_terminal_batch_items(session)
        if reconciled:
            await session.commit()
    if reconciled:
        logger.warning(
            "Terminal-batch reconciliation skipped %d unfinished item(s)",
            reconciled,
        )
    return reconciled


async def sweep_expired_direct_uploads(ctx: dict) -> int:
    """ARQ cron: clean expired/completed-orphan and retry terminal blob cleanup."""
    if not _flag("DIRECT_UPLOAD_CLEANUP_SWEEP_ENABLED", "1"):
        return 0

    from src.services import direct_upload_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        cleaned = await direct_upload_service.sweep_expired_and_unclean_uploads(
            session
        )
    if cleaned:
        logger.info("Direct-upload cleanup sweep cleaned %d upload(s)", cleaned)
    return cleaned


async def _release_cancelled_item_lease(item_ulid: str) -> None:
    """Put a cancelled worker's claimed item back into schedulable state.

    This deliberately uses a fresh session: the analysis session may have been
    cancelled during a flush or transaction and cannot safely be reused. The
    row lock makes cleanup idempotent with cancellation, orphan handling, and a
    duplicate delivery. The coordinator's stale-lease recovery is the fallback
    if this best-effort cleanup is itself interrupted by process death.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        item = (
            await session.execute(
                select(BatchItem)
                .where(BatchItem.ulid == item_ulid)
                .with_for_update()
            )
        ).scalars().first()
        if item is None or item.status != "processing":
            return
        batch = (
            await session.execute(
                select(Batch)
                .where(Batch.id == item.batch_id)
                .with_for_update()
            )
        ).scalars().first()
        if batch is None or batch.status in _TERMINAL_BATCH_STATUSES:
            # Cancellation/failure owns the terminal parent. Returning this row
            # to pending would create work no coordinator is allowed to resume.
            item.status = "skipped"
            item.completed_at = datetime.now(timezone.utc)
            item.error_message = None
        else:
            # Back in the run with this try counted; the note says why it runs
            # again and, once its tries are used up, why it failed.
            from src.services.batch_service import STOPPED_MID_CHECK

            item.status = "pending"
            item.completed_at = None
            item.error_message = STOPPED_MID_CHECK
        item.started_at = None
        item.lease_started_at = None
        await session.commit()


# ---------------------------------------------------------------------------
# Cost-item helpers (W3) — a batch-costed part must match POST /validate/cost
# ---------------------------------------------------------------------------


def _cost_timeout_sec() -> float:
    """Per-item cost compute budget. Mirrors routes._analysis_timeout_sec (same
    env var, default, and floor) and is well within the 600s worker ceiling."""
    try:
        return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    except (TypeError, ValueError):
        return 60.0


def _parse_item_quantities(raw: str | None) -> list[int]:
    """Manifest quantities ("1;100;1000") -> [1,100,1000]. Empty/unset mirrors
    POST /validate/cost's default qty EXACTLY (Form default "50,5000")."""
    if not raw or not raw.strip():
        return [50, 5000]
    out: list[int] = []
    for tok in raw.split(";"):
        tok = tok.strip()
        if tok:
            out.append(int(tok))  # values validated at create time
    return out or [50, 5000]


def _compute_cost_report(file_bytes: bytes, filename: str, options):
    """Parse + cost one part off the event loop, reusing the LIVE cost route's
    mesh parse (``_parse_mesh``) and engine (``_run_cost_engine``) so a batch-
    costed part is byte-for-byte the same computation as POST /validate/cost with
    the same params. Returns ``(DecisionReport, suffix)``."""
    from src.api.routes import _parse_mesh, _run_cost_engine
    from src.costing import estimate_decision

    mesh, suffix = _parse_mesh(file_bytes, filename)
    result, m, features = _run_cost_engine(mesh, filename)
    return estimate_decision(result, m, features, options), suffix


async def _bind_org_rate_tables(session, org_id, options) -> dict | None:
    """Price on the org's governed tables, exactly as POST /validate/cost does.

    The published rate card in effect (RATE_LIBRARY_ENABLED) becomes the base
    table under shop/user overrides, and the published materials catalog's
    per-kg prices and materials are laid over it (MATERIAL_LIBRARY_ENABLED).
    Returns the card (``{"payload", "version"}``) for the record's stamp, or
    None when the org has none in effect (then the engine's own V0 table, as
    the route). Mirrors ``routes._run_cost_decision``'s W4 blocks.
    """
    import copy

    from src.costing.rates import RATE_CARD_V0
    from src.services.material_library_service import resolve_material_overrides_for
    from src.services.rate_library_service import resolve_rate_card_for_org

    if not (isinstance(org_id, str) and org_id):
        return None
    rate_card = await resolve_rate_card_for_org(session, org_id)
    if rate_card is not None:
        options.base_rate_table = rate_card["payload"]
    mat_payload = await resolve_material_overrides_for(session, org_id)
    mat_prices = (mat_payload or {}).get("material_prices") or {}
    mat_defs = (mat_payload or {}).get("materials") or {}
    if mat_prices or mat_defs:
        # The card payload may be the rate library's cached object: copy, never mutate it.
        base = copy.deepcopy(options.base_rate_table if options.base_rate_table is not None else RATE_CARD_V0)
        if mat_prices:
            base["material_prices"] = {**(base.get("material_prices") or {}), **mat_prices}
        if mat_defs:
            base["materials"] = {**(base.get("materials") or {}), **mat_defs}
        options.base_rate_table = base
    return rate_card


async def _run_cost_item(session, batch, item) -> dict:
    """Cost one batch item and link the resulting decision to it.

    Mirrors ``routes._run_cost_decision`` step-for-step (options, org-calibration
    bind, bounded executor, persist+dedup) so the number a batch produces equals
    the number the live route would — the honesty invariant of W3. Returns a dict
    of engine-computed webhook extras (copied from ``report_to_dict`` output).

    On ``report.status == "GEOMETRY_INVALID"`` the item is marked ``failed`` with
    the engine's repair reason (no fake success, no crash) and no decision is
    persisted — exactly the route's clean-refusal branch.
    """
    import asyncio
    import time

    from src import __version__ as _cv_version
    from src.auth.require_api_key import AuthedUser
    from src.costing import EstimateOptions, report_to_dict
    from src.services import batch_service, cost_decision_service
    from src.services.analysis_service import compute_mesh_hash
    from src.services.catalog_service import make_now_estimate

    start = time.time()

    # Persisting a duplicate cost decision may roll the session back and expire
    # these ORM rows. Snapshot immutable routing/input values up front and
    # refresh the mutable rows before writing the item outcome.
    batch_id = batch.id
    batch_ulid = batch.ulid
    batch_user_id = batch.user_id
    batch_api_key_id = batch.api_key_id or 0
    batch_org_id = batch.org_id
    batch_input_mode = batch.input_mode
    item_filename = item.filename
    item_quantities = item.quantities
    item_region = item.region
    item_material_class = item.material_class
    item_shop = item.shop

    # ---- read bytes (zip only unless a remote object adapter is configured) --
    if batch_input_mode == "zip":
        try:
            file_bytes = await asyncio.to_thread(
                batch_service.read_batch_blob, batch_ulid, item_filename
            )
        except Exception as exc:
            raise BatchStorageReadError(
                "batch artifact could not be read from durable storage"
            ) from exc
    elif batch_input_mode == "s3":
        raise RuntimeError(
            "S3 batch item fetch is unsupported on this server; upload a ZIP batch or import a manifest CSV."
        )
    else:
        raise ValueError(f"Unknown input_mode: {batch_input_mode}")

    filename = item_filename

    # ---- build EstimateOptions (mirror _run_cost_decision) ------------------
    # is_user is True ONLY for manifest-supplied values (parity rule); missing
    # values fall back to the engine defaults. quantities default mirrors the
    # route's Form default (50,5000). n_cavities/complexity are not manifest
    # fields, so they stay at the engine defaults (DEFAULT provenance).
    quantities = _parse_item_quantities(item_quantities)
    region = item_region                       # None => unset (DEFAULT US)
    material_class = item_material_class or "polymer"
    shop_slug = item_shop                       # a validated slug (or None)

    options = EstimateOptions(
        quantities=quantities,
        material_class=material_class,
        material_class_is_user=item_material_class is not None,
        region=region or "US",
        region_is_user=region is not None,
        shop=shop_slug,
        rate_overrides={},
        n_cavities=1,
        n_cavities_is_user=False,
        complexity="moderate",
        complexity_is_user=False,
    )

    # ---- bind org calibration EXACTLY like _run_cost_decision ---------------
    # The batch's persisted org is the immutable tenant boundary. Never resolve
    # the owner's current_org_id here: the user may switch organizations after
    # enqueue but before this delayed worker runs.
    user = AuthedUser(
        user_id=batch_user_id,
        api_key_id=batch_api_key_id,
        key_prefix="batch",
    )
    cal_org_id = batch_org_id
    if isinstance(cal_org_id, str) and cal_org_id:
        from src.services.groundtruth_service import load_served_calibration

        residual_model, calibration = load_served_calibration(cal_org_id)
        if residual_model is not None:
            options.residual_model = residual_model
        if calibration is not None:
            options.calibration = calibration
    # ---- the org's published rate card and materials, as the route binds them -
    rate_card = await _bind_org_rate_tables(session, cal_org_id, options)

    # ---- parse + cost, bounded by the same timeout the route uses -----------
    # Room in the compute budget first (the wait is not part of the part's time
    # or its limit); on a timeout the thread keeps that room until it ends.
    timeout = _cost_timeout_sec()
    waited = time.time()
    async with compute_budget.hold(compute_budget.need_for_data(file_bytes, filename),
                                   wait=_item_wait_seconds(timeout), label="batch cost item"):
        start += time.time() - waited
        report, suffix = await compute_budget.run_within_budget(
            _compute_cost_report, file_bytes, filename, options, timeout=timeout, label="batch cost item",
        )
    duration_ms = round((time.time() - start) * 1000, 1)

    # ---- broken geometry -> failed item with the structured reason ----------
    if report.status == "GEOMETRY_INVALID":
        item.status = "failed"
        item.error_message = (report.reason or "GEOMETRY_INVALID")[:500]
        item.duration_ms = duration_ms
        item.completed_at = datetime.now(timezone.utc)
        item.lease_started_at = None
        await batch_service.update_batch_counters(session, batch.id, "failed_items")
        batch_service.touch_batch_heartbeat(batch)
        await session.commit()
        logger.info(
            "BatchItem %s cost failed: GEOMETRY_INVALID (%s)",
            item.ulid, report.reason,
        )
        return {
            "cost_decision_id": None,
            "make_now_process": None,
            "unit_cost_usd": None,
            "crossover_qty": None,
        }

    result_dict = report_to_dict(report)
    # The record says which of the org's rate cards priced it, and the lines that
    # use the org's own rates say so, as a single check's record does.
    if rate_card is not None:
        from src.services.rate_card_basis import apply_rate_card

        result_dict = apply_rate_card(result_dict, rate_card["version"], rate_card["payload"])
    # The org's calibration from its own actuals (if one is applied); unchanged otherwise.
    from src.services.calibration_service import apply_org_calibration

    result_dict = await apply_org_calibration(session, cal_org_id, result_dict)

    # ---- persist (dedup-safe: reuse the existing row on conflict) -----------
    # persist_cost_decision keys on (org_id, user_id, mesh_hash, params_hash) and
    # RETURNS the existing row on a duplicate (pre-check or IntegrityError race)
    # — so a ZIP with duplicate parts still completes each item, all pointing at
    # the one decision row inside this batch's immutable organization. params_hash
    # matches the route's for the same params (dedup + parity coherence).
    params_hash = cost_decision_service.compute_params_hash(
        quantities=quantities,
        region=region,
        cavities=1,
        complexity="moderate",
        material_class=material_class,
        shop=shop_slug,
        overrides={},
    )
    mesh_hash = compute_mesh_hash(file_bytes)
    saved = await cost_decision_service.persist_cost_decision(
        session,
        user,
        mesh_hash=mesh_hash,
        params_hash=params_hash,
        engine_version=_cv_version,
        filename=filename,
        file_type=suffix.lstrip("."),
        result_json=result_dict,
        org_id=batch_org_id,
    )

    await session.refresh(item)
    await session.refresh(batch)
    if item.status != "processing":
        logger.info(
            "BatchItem %s finished costing after becoming %s; result not linked",
            item.ulid,
            item.status,
        )
        return {
            "cost_decision_id": None,
            "make_now_process": None,
            "unit_cost_usd": None,
            "crossover_qty": None,
        }

    # ---- success: link + counters + heartbeat (same shape as the DFM path) --
    item.status = "completed"
    item.cost_decision_id = saved.id
    item.duration_ms = duration_ms
    item.completed_at = datetime.now(timezone.utc)
    item.lease_started_at = None
    await batch_service.update_batch_counters(session, batch_id, "completed_items")
    batch_service.touch_batch_heartbeat(batch)
    await session.commit()

    # ---- engine-number webhook extras (copied from report_to_dict) ----------
    decision = result_dict.get("decision") or {}
    est = make_now_estimate(result_dict)
    unit_cost_usd = None
    if est is not None and est.get("dfm_ready", True):
        # Withhold the price on a DFM-blocked make-now route (catalog honesty).
        unit_cost_usd = est.get("unit_cost_usd")

    logger.info(
        "BatchItem %s cost completed: decision=%s make_now=%s duration=%.1fms",
        item.ulid, saved.ulid, decision.get("make_now_process"), duration_ms,
    )
    return {
        "cost_decision_id": saved.ulid,
        "make_now_process": decision.get("make_now_process"),
        "unit_cost_usd": unit_cost_usd,
        "crossover_qty": decision.get("crossover_qty"),
    }


# ---------------------------------------------------------------------------
# Catalog-run items: the same two steps as a single-part check
# ---------------------------------------------------------------------------


class CatalogOrgChanged(RuntimeError):
    """The run's owner switched organization after the run started."""


def _catalog_slots() -> "asyncio.Semaphore":
    """Catalog parts checked at once in this worker process: the parse pool's size.

    A part's analysis budget (ANALYSIS_TIMEOUT_SEC) includes any wait for a
    parse-ladder slot. Parts of several runs (or one run's 4 at a time) queued
    behind a slow STEP would time out while merely waiting; holding a slot here
    first means the clock starts when the part is actually being read. The wait
    is bounded (``_catalog_slot``): past it the part goes back to the run.
    Loop-local, like the parse pool's own.
    """
    from src.parsers import parse_pool

    loop = asyncio.get_event_loop()
    sem = getattr(loop, "_cadverify_catalog_sem", None)
    if sem is None:
        sem = asyncio.Semaphore(max(1, parse_pool.worker_count()))
        setattr(loop, "_cadverify_catalog_sem", sem)
    return sem


@asynccontextmanager
async def _catalog_slot(wait: float):
    """A catalog slot (``_catalog_slots``), waited for at most ``wait`` seconds (then ComputeBusy)."""
    sem = _catalog_slots()
    try:
        await asyncio.wait_for(sem.acquire(), max(0.0, wait))
    except asyncio.TimeoutError:
        raise compute_budget.ComputeBusy(wait) from None
    try:
        yield
    finally:
        sem.release()


def _catalog_owned_processes(processes) -> str:
    """The org's machine processes the cost route accepts as owned (others are left out)."""
    from src.costing.rates import _resolve_process_token

    return ",".join(sorted({p for p in processes if p and _resolve_process_token(p) is not None}))


async def _run_catalog_item(session, batch, item) -> dict:
    """Check one catalog part: the DFM analysis, then the cost decision with the org's machines.

    Both steps are the live single-check code paths (``run_analysis`` and the
    POST /validate/cost body ``routes._run_cost_decision``), so a part on the
    board carries exactly the numbers its own check would: the org's machines,
    materials, rates and calibration bound, its own quantity ladder and
    material. The analysis keeps the source file for the part's page; the
    analysed geometry is reused by the cost step, as in a single check.

    Invalid geometry is a result, not a failure: the item completes with the
    engine's reason (no decision is saved, as the route saves none). A free run
    keeps the part's allowance slot once the item completes, in the same
    transaction (``catalog_allowance.count_completed_part``).
    """
    from src.auth.org_context import resolve_org
    from src.services import batch_service
    from src.services.catalog_run_service import run_meta

    batch_id = batch.id
    batch_ulid = batch.ulid
    batch_user_id = batch.user_id
    batch_org_id = batch.org_id
    batch_api_key_id = batch.api_key_id or 0
    free_run = bool(run_meta(batch).get("free"))
    item_id = item.id
    item_ulid = item.ulid
    item_filename = item.filename
    item_quantities = item.quantities or ""
    item_material_class = item.material_class

    try:
        file_bytes = await asyncio.to_thread(batch_service.read_batch_blob, batch_ulid, item_filename)
    except Exception as exc:
        raise BatchStorageReadError("batch artifact could not be read from durable storage") from exc

    # The cost route resolves the caller's ACTIVE organization. A run belongs to
    # the organization it started in; if the owner switched since, stop rather
    # than save this part's records into another organization.
    if await resolve_org(session, batch_user_id) != batch_org_id:
        raise CatalogOrgChanged(
            "Your active organization changed after this run started. Switch back to start it again."
        )

    user = AuthedUser(user_id=batch_user_id, api_key_id=batch_api_key_id, key_prefix="batch")
    from fastapi import HTTPException

    from src.api.routes import refuse_over_memory_budget
    from src.config.check_limits import larger_limits

    # A part too heavy for this worker is refused before anything runs (the same
    # memory gate as any check), in plain words.
    try:
        refuse_over_memory_budget(file_bytes, item_filename)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise RuntimeError(str(detail.get("message") or "This file needs more memory than one check gets.")) from exc
    # A catalog part runs with the worker's own budget for its size (as a big
    # file's check does), not the 60 s a web request gets.
    budget = _catalog_budget_sec(len(file_bytes), item_filename)
    # A catalog slot, then room in the compute budget for the part's whole check
    # (its analysis, bodies and price), sized by the memory model. Waiting for
    # either isn't part of its time limit; past the wait its job allows, the part
    # goes back to the run (run_batch_item). A part that ran out of time keeps its
    # room until its thread really ends, so its retry never doubles it unseen.
    wait_until = time.monotonic() + _item_wait_seconds(2 * budget)
    try:
        with larger_limits(budget_sec=budget, max_triangles=_catalog_max_triangles(),
                           max_bytes=max(len(file_bytes), 1)):
            async with _catalog_slot(wait_until - time.monotonic()):
                async with compute_budget.hold(compute_budget.need_for_data(file_bytes, item_filename),
                                               wait=max(0.0, wait_until - time.monotonic()), label="catalog part"):
                    return await _check_catalog_part(
                        session, batch, item, file_bytes, user,
                        batch_id=batch_id, batch_org_id=batch_org_id, batch_user_id=batch_user_id,
                        free_run=free_run, item_id=item_id, item_ulid=item_ulid, item_filename=item_filename,
                        item_quantities=item_quantities, item_material_class=item_material_class,
                    )
    except CatalogPartTimedOut as exc:
        # Once more, after the rest of the run: a busy worker is the usual cause.
        if await _check_again_later(session, item_ulid, batch):
            logger.info("BatchItem %s ran past %.0fs; checking it again after the rest of the run", item_ulid, budget)
            return {}
        raise RuntimeError(f"Checking took longer than its {budget:.0f} s time limit, twice.") from exc


class CatalogPartTimedOut(RuntimeError):
    """A catalog part's check ran past its time limit."""


def _catalog_budget_sec(size_bytes: int, filename: str) -> float:
    """A catalog part's time limit: the big-file check's budget for its size, within the job's own."""
    from src.services.stored_check_service import time_budget_sec

    try:
        floor = float(os.getenv("CATALOG_PART_MIN_SECONDS", "180"))
    except ValueError:
        floor = 180.0
    # The analysis and the price each get the budget; both fit in the 600 s job.
    return max(floor, min(240.0, time_budget_sec(size_bytes, filename)))


def _catalog_max_triangles() -> int:
    try:
        return max(1, int(os.getenv("MAX_TRIANGLES", "2000000")))
    except ValueError:
        return 2_000_000


def _timed_out(exc: BaseException) -> bool:
    from fastapi import HTTPException

    if isinstance(exc, compute_budget.MeshBusy):
        return True  # meshing ran out of time on a saturated box: check it again later
    if isinstance(exc, HTTPException):
        if exc.status_code == 504:
            return True
        detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
        from src.services.catalog_run_service import _TIME_LIMIT

        return exc.status_code == 400 and bool(_TIME_LIMIT.search(str(detail or "")))
    return isinstance(exc, asyncio.TimeoutError)


async def _check_again_later(session, item_ulid: str, batch=None) -> bool:
    """Put a part that ran out of time back in the run once, behind the parts still to go.

    ``priority = 'low'`` marks the second try (and orders it last); a part that
    already had it fails with plain words instead. False when it was already retried.
    """
    try:
        await session.rollback()
    except Exception:
        pass
    item = (await session.execute(
        select(BatchItem).where(BatchItem.ulid == item_ulid).with_for_update()
    )).scalars().first()
    if batch is not None:
        await session.refresh(batch)
    if item is None or item.status != "processing":
        return True  # cancelled or finished elsewhere: nothing to record here
    if item.priority == "low":
        return False
    item.status = "pending"
    item.priority = "low"
    item.started_at = None
    item.lease_started_at = None
    item.error_message = None
    await session.commit()
    if batch is not None:
        await session.refresh(batch)  # the rollback above expired it; the caller reads it after
    return True


async def _declare_list_specs(session, org_id: str, user_id: int, file_bytes: bytes, specs: dict) -> None:
    """Store a parts-list row's specs on the part's context (best effort, never breaks a run)."""
    import copy

    from src.services import cost_decision_service, part_context_service as pcs
    from src.services.analysis_service import compute_mesh_hash

    mesh_hash = compute_mesh_hash(file_bytes)
    try:
        async with session.begin_nested():
            before = copy.deepcopy(pcs.engine_inputs(await pcs.get_context(session, org_id, mesh_hash)))
            row = await pcs.upsert_context(session, org_id, mesh_hash, {"part_specs": specs}, created_by=user_id)
            for reason in pcs.changed_input_reasons(before, pcs.engine_inputs(row))[:1]:
                await cost_decision_service.mark_part_decisions_stale(session, org_id, mesh_hash, reason=reason)
        await session.commit()
    except Exception:
        logger.warning("parts-list specs not stored for org %s part %.12s", org_id, mesh_hash, exc_info=True)


def part_facts(list_meta: dict, run: dict) -> dict:
    """A part's facts from its catalog run: the parts list's row for it, with the
    run's Quantity ("each, unless listed") as its yearly quantity when the list
    names none."""
    run_qty = run.get("quantity")
    if list_meta.get("quantity") or not isinstance(run_qty, int) or run_qty <= 0:
        return list_meta
    return {**list_meta, "quantity": run_qty}


async def _declare_list_facts(session, org_id: str, user_id: int, batch_ulid: str, file_bytes: bytes,
                              list_meta: dict) -> None:
    """The parts list's current price and yearly quantity on the part's declared context.

    The yearly quantity is the list's for this file, else the run's own Quantity
    ("each, unless listed": the same yearly figure for every part the list
    doesn't name), so a part from a run says how many a year and an RFQ asks
    for that many. Best effort, never breaks a run. A price typed on the part's
    Decision view stays (it wins over a list's); a yearly quantity already
    declared stays. Neither is an engine input, so no record goes out of date.
    """
    from src.services import part_context_service as pcs
    from src.services.analysis_service import compute_mesh_hash

    price = list_meta.get("current_price_usd")
    qty = list_meta.get("quantity")
    if not price and not qty:
        return
    mesh_hash = compute_mesh_hash(file_bytes)
    try:
        async with session.begin_nested():
            row = await pcs.get_context(session, org_id, mesh_hash)
            fields: dict = {}
            stored = getattr(row, "buy_price", None) if row is not None else None
            if price and not (isinstance(stored, dict) and stored.get("source") == "you"):
                fields["buy_price"] = pcs.normalize_buy_price({"usd_each": float(price)}, source="parts_list",
                                                              run_id=batch_ulid)
            if qty and (row is None or row.annual_volume is None):
                fields["annual_volume"] = int(qty)
            if fields:
                await pcs.upsert_context(session, org_id, mesh_hash, fields, created_by=user_id)
        await session.commit()
    except Exception:
        logger.warning("parts-list price and quantity not stored for org %s part %.12s", org_id, mesh_hash,
                       exc_info=True)


async def _check_catalog_part(
    session, batch, item, file_bytes: bytes, user, *, batch_id: int, batch_org_id: str,
    batch_user_id: int, free_run: bool, item_id: int, item_ulid: str, item_filename: str,
    item_quantities: str, item_material_class,
) -> dict:
    """The two steps of one catalog part, holding a parse slot (see _run_catalog_item)."""
    import io
    import time

    from fastapi import HTTPException
    from starlette.datastructures import Headers, UploadFile

    from src.api.routes import _run_cost_decision
    from src.auth.catalog_allowance import count_completed_part, file_identity
    from src.db.models import CostDecision, MachineInstance
    from src.services import analysis_service, batch_service
    from src.services.catalog_run_service import GEOMETRY_INVALID_PREFIX

    # The part's own time: from when it holds a parse slot, not while it waited.
    start = time.time()
    try:
        analysis_run = await analysis_service.run_analysis(
            file_bytes=file_bytes,
            filename=item_filename,
            processes=None,
            rule_pack=None,
            user=user,
            session=session,
            org_id=batch_org_id,
            return_persisted_id=True,
        )
    except (HTTPException, asyncio.TimeoutError) as exc:
        if _timed_out(exc):
            raise CatalogPartTimedOut(str(getattr(exc, "detail", exc))) from exc
        raise
    if not isinstance(analysis_run, analysis_service.AnalysisRun) or analysis_run.analysis_id is None:
        raise RuntimeError("Analysis completed without a durable persisted record")
    analysis_id = analysis_run.analysis_id

    owned = _catalog_owned_processes((await session.execute(
        select(MachineInstance.process).where(MachineInstance.org_id == batch_org_id)
    )).scalars().all())
    upload = UploadFile(
        file=io.BytesIO(file_bytes),
        filename=item_filename,
        headers=Headers({"content-type": "application/octet-stream"}),
    )
    qty = ",".join(t for t in item_quantities.split(";") if t.strip()) or "1,100,1000,2000,5000,10000"
    # The parts list's specs for this file become the part's declared specs, so
    # the price, the gates and the part's page all read them (the newest
    # declaration wins, as on the part's page).
    from src.services.catalog_run_service import run_meta

    list_meta = ((run_meta(batch).get("items") or {}).get(item_filename) or {})
    list_specs = list_meta.get("part_specs")
    if list_specs:
        await _declare_list_specs(session, batch_org_id, batch_user_id, file_bytes, list_specs)
    # The list's price and yearly quantity (else the run's quantity) go on the part, for its own page.
    await _declare_list_facts(session, batch_org_id, batch_user_id, batch.ulid, file_bytes,
                              part_facts(list_meta, run_meta(batch)))
    # The material the list names is priced as that grade; one ScaleCAD can't
    # price leaves the part checked and not priced (never priced as another).
    material_name = list_meta.get("material") if list_meta.get("material_grade") else None
    unpriced = bool(list_meta.get("material")) and not list_meta.get("material_class")
    geometry_invalid: str | None = None
    decision_id = None
    # A file of several bodies isn't priced as one block: each body shape becomes
    # a part of its own on the board (services/catalog_bodies.py).
    split = None
    part_type = analysis_run.result.get("part_type") if isinstance(analysis_run.result, dict) else None
    if isinstance(part_type, dict) and not unpriced:
        from src.services.catalog_bodies import check_file_bodies

        try:
            split = await check_file_bodies(
                session, user=user, org_id=batch_org_id, file_bytes=file_bytes, filename=item_filename,
                quantities=qty, material_class=item_material_class, owned=owned, part_type=part_type,
                material_name=material_name,
            )
        except Exception:
            logger.warning("BatchItem %s: body by body check failed; priced as one file", item_ulid, exc_info=True)
            split = None
    if split is None and not unpriced:
        try:
            report = await _run_cost_decision(
                file=upload,
                qty=qty,
                region=None,
                cavities=1,
                complexity="moderate",
                material_class=item_material_class or "polymer",
                owned_processes=owned or None,
                user=user,
                session=session,
                material_name=material_name,
                org_id=batch_org_id,
            )
            saved = (report or {}).get("saved") or {}
            if saved.get("id"):
                decision_id = (await session.execute(
                    select(CostDecision.id).where(CostDecision.ulid == saved["id"])
                )).scalar_one_or_none()
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if exc.status_code == 400 and detail.get("code") == "GEOMETRY_INVALID":
                geometry_invalid = str(detail.get("message") or "the geometry needs repair")
            elif _timed_out(exc):
                raise CatalogPartTimedOut("pricing ran past the time limit") from exc
            else:
                message = detail.get("message") if detail else exc.detail
                raise RuntimeError(f"Pricing didn't finish: {message}") from exc
    duration_ms = round((time.time() - start) * 1000, 1)

    # The analysis or a deduplicated decision may have rolled the session back.
    await session.refresh(item)
    await session.refresh(batch)
    if item.status != "processing":
        logger.info("BatchItem %s finished its catalog check after becoming %s; result not linked", item_ulid, item.status)
        return {}

    item.status = "completed"
    item.analysis_id = analysis_id
    item.cost_decision_id = decision_id
    item.error_message = (GEOMETRY_INVALID_PREFIX + geometry_invalid)[:500] if geometry_invalid else None
    item.duration_ms = duration_ms
    item.completed_at = datetime.now(timezone.utc)
    item.lease_started_at = None
    await batch_service.update_batch_counters(session, batch_id, "completed_items")
    batch_service.touch_batch_heartbeat(batch)
    if split is not None:
        from src.services.catalog_bodies import record_file_bodies

        await record_file_bodies(batch_org_id, batch.ulid, split)
    if free_run:
        from src.auth.validation_caps import SAMPLE_PART_SHA256
        import hashlib

        # One file is one part of the free run, however many bodies it holds.
        if hashlib.sha256(file_bytes).hexdigest() not in SAMPLE_PART_SHA256:
            await count_completed_part(session, batch_user_id, batch_id, item_id, file_identity(item_filename, file_bytes))
    await session.commit()
    logger.info(
        "BatchItem %s catalog check completed: analysis_id=%s decision=%s duration=%.1fms",
        item_ulid, analysis_id, decision_id, duration_ms,
    )
    return {}


# ---------------------------------------------------------------------------
# Item processor task
# ---------------------------------------------------------------------------


async def _resolve_transient_batch_item_failure(
    item_ulid: str,
    *,
    stopped_before: bool = False,
) -> tuple[str, int]:
    """Persist retry, exhaustion, or terminal-parent state in a fresh session.

    ``stopped_before``: an earlier try of this item was stopped part way (a
    worker restart or out-of-memory kill, a reclaimed lease). Then the tries
    weren't all spent on storage or database failures, and an item that runs
    out of them says it was stopped (``batch_service.exhausted_reason``); the
    note stays on the item across this retry so the next try knows it too.
    """

    from src.services import batch_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        item = (
            await session.execute(
                select(BatchItem)
                .where(BatchItem.ulid == item_ulid)
                .with_for_update()
            )
        ).scalars().first()
        if item is None:
            return "missing", 0
        batch = (
            await session.execute(
                select(Batch)
                .where(Batch.id == item.batch_id)
                .with_for_update()
            )
        ).scalars().first()
        if batch is None:
            return "missing", _item_attempt_count(item)
        attempts = _item_attempt_count(item)

        if item.status in {"completed", "failed", "skipped", "cancelled"}:
            return "terminal", attempts
        now = datetime.now(timezone.utc)
        if batch.status in _TERMINAL_BATCH_STATUSES:
            item.status = "skipped"
            item.completed_at = now
            item.lease_started_at = None
            await session.commit()
            return "terminal", attempts

        stopped_before = stopped_before or (item.error_message or "").startswith(
            batch_service.STOPPED_MID_CHECK)
        if attempts >= BATCH_ITEM_MAX_ATTEMPTS:
            item.status = "failed"
            # What spent the tries: the storage/database wording only when no
            # earlier try was stopped part way.
            item.error_message = batch_service.exhausted_reason(item, stopped=stopped_before)
            item.completed_at = now
            item.lease_started_at = None
            await batch_service.update_batch_counters(
                session, batch.id, "failed_items"
            )
            batch_service.touch_batch_heartbeat(batch)
            await session.commit()
            return "failed", attempts

        # ARQ retries the same job directly, bypassing the coordinator. Persist
        # the next delivery attempt and a queue lease before asking ARQ to retry.
        attempts += 1
        item.attempt_count = attempts
        item.status = "queued"
        item.started_at = None
        item.completed_at = None
        item.lease_started_at = now
        item.error_message = batch_service.STOPPED_MID_CHECK if stopped_before else None
        await session.commit()
        return "retry", attempts


async def run_batch_item(ctx: dict, item_ulid: str) -> None:
    """Process a single batch item.

    DFM batches (``job_type='dfm'``) run ``analysis_service.run_analysis``; cost
    batches (``job_type='cost'``) run the should-cost path via ``_run_cost_item``.
    Updates item status and batch counters atomically and fires the item-level
    webhook if the batch has one.
    """
    from src.services import analysis_service, batch_service, webhook_service

    # The compute-room waits below are measured from the job's own start.
    _JOB_STARTED.set(time.monotonic())
    session_factory = get_session_factory()

    async with session_factory() as session:
        # Load item and batch
        item = (
            await session.execute(
                select(BatchItem)
                .where(BatchItem.ulid == item_ulid)
                .with_for_update()
            )
        ).scalars().first()
        if item is None:
            logger.error("BatchItem %s not found", item_ulid)
            return

        batch = (
            await session.execute(
                select(Batch).where(Batch.id == item.batch_id)
            )
        ).scalars().first()
        if batch is None:
            logger.error("Batch not found for item %s", item_ulid)
            return

        # Analysis de-duplication may roll this session back when concurrent
        # items race on the same geometry. A rollback expires every ORM object
        # in the identity map, so retain the immutable routing values before
        # any analysis work and explicitly refresh mutable rows afterwards.
        batch_id = batch.id
        batch_ulid = batch.ulid
        batch_user_id = batch.user_id
        batch_org_id = batch.org_id
        batch_api_key_id = batch.api_key_id or 0
        batch_input_mode = batch.input_mode
        batch_job_type = batch.job_type
        batch_release_fault = (batch.manifest_json or {}).get("release_test_fault")
        item_filename = item.filename
        item_process_types = item.process_types
        item_rule_pack = item.rule_pack

        # ARQ delivery is at-least-once. The row lock plus durable state makes
        # duplicates no-ops. A higher ``job_try`` may reclaim the same job's
        # processing row only when a DB outage prevented its retry-state cleanup.
        try:
            job_try = max(1, int(ctx.get("job_try", 1)))
        except (TypeError, ValueError):
            job_try = 1
        attempts = _item_attempt_count(item)
        retry_reclaim = item.status == "processing" and job_try > attempts
        if item.status != "queued" and not retry_reclaim:
            logger.info(
                "BatchItem %s already %s; duplicate task ignored",
                item_ulid,
                item.status,
            )
            return
        if batch.status in _TERMINAL_BATCH_STATUSES:
            item.status = "skipped"
            item.completed_at = datetime.now(timezone.utc)
            item.lease_started_at = None
            await session.commit()
            logger.info(
                "BatchItem %s skipped because batch %s is %s",
                item_ulid,
                batch.ulid,
                batch.status,
            )
            return
        # Claim one bounded delivery attempt. Coordinator publication normally
        # sets this first; max(..., 1) supports legacy/test rows already queued.
        attempts = min(
            BATCH_ITEM_MAX_ATTEMPTS,
            max(attempts, job_try, 1),
        )
        item.status = "processing"
        item.attempt_count = attempts
        item.started_at = datetime.now(timezone.utc)
        item.lease_started_at = item.started_at
        # A note from a stopped earlier try isn't this try's outcome, but it is
        # part of why the tries ran out if this one fails on storage or the
        # database too. A processing row this delivery reclaims was left by a
        # try that stopped before it could record anything.
        stopped_before = retry_reclaim or (item.error_message or "").startswith(
            batch_service.STOPPED_MID_CHECK)
        item.error_message = None

        # Cost items carry engine-number webhook extras; DFM items carry none.
        webhook_extra: dict | None = None

        try:
            await session.commit()
            if batch_release_fault == "batch_delay":
                # Bounded, record-scoped delay for proving refresh/cancellation
                # behavior against a real worker. The API can persist this marker
                # only after a secret-authorized release-evidence request.
                await asyncio.sleep(1.5)

            if batch_job_type == "cost":
                # W3: should-cost this item (mirror POST /validate/cost). The
                # coordinator/DFM paths are untouched.
                webhook_extra = await _run_cost_item(session, batch, item)
            elif batch_job_type == "catalog":
                # A catalog part: its DFM analysis and its cost decision with
                # the org's machines, exactly as a single-part check.
                webhook_extra = await _run_catalog_item(session, batch, item) or None
            else:
                start = time.time()

                # Read file bytes
                if batch_input_mode == "zip":
                    try:
                        file_bytes = await asyncio.to_thread(
                            batch_service.read_batch_blob,
                            batch_ulid,
                            item_filename,
                        )
                    except Exception as exc:
                        raise BatchStorageReadError(
                            "batch artifact could not be read from durable storage"
                        ) from exc
                elif batch_input_mode == "s3":
                    raise RuntimeError(
                        "S3 batch item fetch is unsupported on this server; upload a ZIP batch or import a manifest CSV."
                    )
                else:
                    raise ValueError(f"Unknown input_mode: {batch_input_mode}")

                # Construct AuthedUser for analysis service
                user = AuthedUser(
                    user_id=batch_user_id,
                    api_key_id=batch_api_key_id,
                    key_prefix="batch",
                )

                # Run analysis, holding room in the compute budget for it (the
                # wait isn't part of its time; past the job's wait it goes back).
                async with compute_budget.hold(
                    compute_budget.need_for_data(file_bytes, item_filename),
                    wait=_item_wait_seconds(2 * _cost_timeout_sec()), label="batch analysis item",
                ):
                    start = time.time()
                    analysis_run = await analysis_service.run_analysis(
                        file_bytes=file_bytes,
                        filename=item_filename,
                        processes=item_process_types,
                        rule_pack=item_rule_pack,
                        user=user,
                        session=session,
                        org_id=batch_org_id,
                        return_persisted_id=True,
                    )
                if not isinstance(analysis_run, analysis_service.AnalysisRun):
                    raise RuntimeError(
                        "Analysis did not return its durable persistence receipt"
                    )
                analysis_id = analysis_run.analysis_id
                if analysis_id is None:
                    raise RuntimeError(
                        "Analysis completed without a durable persisted record"
                    )

                duration_ms = round((time.time() - start) * 1000, 1)

                # run_analysis deliberately rolls back on a concurrent cache
                # insert race, expiring item/batch. Refresh through the async
                # session before touching either object; implicit lazy loads in
                # an arq coroutine otherwise raise MissingGreenlet and strand
                # the item forever in `processing`.
                await session.refresh(item)
                await session.refresh(batch)
                if item.status != "processing":
                    logger.info(
                        "BatchItem %s finished analysis after becoming %s; result not linked",
                        item_ulid,
                        item.status,
                    )
                    return

                # Success
                item.status = "completed"
                item.analysis_id = analysis_id
                item.duration_ms = duration_ms
                item.completed_at = datetime.now(timezone.utc)
                item.lease_started_at = None
                await batch_service.update_batch_counters(session, batch_id, "completed_items")
                # Liveness from work, not just the coordinator (F-ARCH-6/#2 follow-up):
                # a batch under arq pool saturation may go many ticks without the
                # coordinator itself running, but items are still actively finishing.
                # Refresh the same heartbeat the coordinator writes so the sweeper
                # sees the batch as alive whenever there is real progress, from
                # either source.
                batch_service.touch_batch_heartbeat(batch)
                await session.commit()

                logger.info(
                    "BatchItem %s completed: analysis_id=%s duration=%.1fms",
                    item_ulid, analysis_id, duration_ms,
                )

        except asyncio.CancelledError:
            # Cancellation is a BaseException, so the ordinary failure handler
            # below cannot release this durable `processing` claim. Shield a
            # fresh-session cleanup, then preserve cancellation semantics so arq
            # can retry. If the process dies before cleanup, the coordinator's
            # stale lease reclaims the row after the hard timeout boundary.
            try:
                await asyncio.shield(_release_cancelled_item_lease(item_ulid))
            except Exception:
                logger.exception(
                    "Failed to release cancelled lease for BatchItem %s",
                    item_ulid,
                )
            raise
        except compute_budget.ComputeBusy as exc:
            # No room within the wait its job allows: back in the run, try not
            # spent. Meshing that ran out of time on a saturated box: back too,
            # that try counted.
            await _put_back_for_room(session, item_ulid, count_try=isinstance(exc, compute_budget.MeshBusy))
            return
        except Exception as exc:
            if is_transient_batch_item_error(exc):
                logger.warning(
                    "BatchItem %s hit retryable infrastructure failure on attempt %d",
                    item_ulid,
                    attempts,
                    exc_info=True,
                )
                try:
                    await session.rollback()
                except Exception:
                    logger.exception(
                        "Could not roll back failed attempt for BatchItem %s",
                        item_ulid,
                    )
                try:
                    action, next_attempt = await _resolve_transient_batch_item_failure(
                        item_ulid, stopped_before=stopped_before
                    )
                except Exception:
                    # The database may still be unavailable. Preserve ARQ retry
                    # semantics; the durable lease sweeper is the final backstop.
                    logger.exception(
                        "Could not persist retry state for BatchItem %s",
                        item_ulid,
                    )
                    raise Retry(defer=_transient_retry_delay(attempts)) from exc
                if action == "retry":
                    raise Retry(
                        defer=_transient_retry_delay(next_attempt)
                    ) from exc
                return

            logger.exception("BatchItem %s failed with terminal error", item_ulid)
            # A failed flush leaves AsyncSession unusable until rollback, and a
            # rollback expires ORM attributes. Recover the durable rows before
            # recording the terminal item failure so no exception path can
            # leave `processing` work behind.
            await session.rollback()
            await session.refresh(item)
            await session.refresh(batch)
            if item.status in {"completed", "failed", "skipped", "cancelled"}:
                logger.info(
                    "BatchItem %s became %s while its worker failed; preserving terminal state",
                    item_ulid,
                    item.status,
                )
                return
            if batch.status in _TERMINAL_BATCH_STATUSES:
                item.status = "skipped"
            else:
                item.status = "failed"
                await batch_service.update_batch_counters(
                    session, batch_id, "failed_items"
                )
            item.error_message = str(exc)[:500]
            item.completed_at = datetime.now(timezone.utc)
            item.lease_started_at = None
            # Same reasoning as the success path: a failed item is still proof
            # of life for the batch.
            batch_service.touch_batch_heartbeat(batch)
            await session.commit()

        # Fire item webhook if configured
        if batch.webhook_url:
            try:
                payload = {
                    "event": "batch_item.completed",
                    "batch_id": batch.ulid,
                    "item_ulid": item.ulid,
                    "filename": item.filename,
                    "status": item.status,
                    "analysis_id": item.analysis_id,
                    "error_message": item.error_message,
                }
                # Cost items add cost_decision_id + engine numbers (copied
                # straight from report_to_dict; never fabricated here).
                if webhook_extra:
                    payload.update(webhook_extra)
                delivery = await webhook_service.create_webhook_delivery(
                    session, batch.id, "batch_item.completed", payload
                )
                await session.commit()
                pool = ctx.get("redis") or ctx.get("pool")
                if pool is not None:
                    await pool.enqueue_job("dispatch_webhook", delivery.id)
            except Exception:
                logger.exception("Failed to create webhook for item %s", item_ulid)


# ---------------------------------------------------------------------------
# Webhook dispatch task
# ---------------------------------------------------------------------------


async def dispatch_webhook(ctx: dict, delivery_id: int) -> None:
    """Deliver a webhook and schedule retry on failure."""
    from src.services import webhook_service

    session_factory = get_session_factory()

    async with session_factory() as session:
        success = await webhook_service.deliver_webhook(session, delivery_id)
        if not success:
            pool = ctx.get("redis") or ctx.get("pool")
            await webhook_service.schedule_webhook_retry(session, delivery_id, pool)
