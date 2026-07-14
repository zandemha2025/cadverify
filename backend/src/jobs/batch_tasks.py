"""Batch arq tasks -- coordinator, item processor, webhook dispatch.

run_batch_coordinator: Drip-feeds items respecting concurrency limit.
run_batch_item: Runs analysis_service.run_analysis per item.
dispatch_webhook: Delivers webhook with retry scheduling.
"""
from __future__ import annotations

import asyncio
import errno
import logging
import os
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
from src.services.batch_service import BATCH_ITEM_MAX_ATTEMPTS
from src.storage.base import ObjectNotFoundError

logger = logging.getLogger("cadverify.batch_tasks")

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
) -> None:
    """Persist a terminal preparation failure and align parent/item state."""
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
    from src.services import batch_service, direct_upload_service
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
    try:
        configured = int(os.getenv("BATCH_ITEM_LEASE_SECONDS", "660"))
    except (TypeError, ValueError):
        configured = _BATCH_ITEM_LEASE_FLOOR_SECONDS
    return max(_BATCH_ITEM_LEASE_FLOOR_SECONDS, configured)


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


async def run_batch_coordinator(ctx: dict, batch_ulid: str) -> None:
    """Run ONE coordination tick, then re-enqueue itself (F-ARCH-6/#1).

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
      * Recovery is uniform: if a tick is cancelled at ``job_timeout``, crashes,
        or the worker dies, the chain simply stops advancing the heartbeat and the
        heartbeat-based orphan sweeper (F-ARCH-6/#2) reaps the batch. No
        unreachable ``except Exception`` cleanup is relied upon.
    """
    from src.services import batch_service

    session_factory = get_session_factory()
    pool = ctx.get("redis") or ctx.get("pool")
    poll_interval = int(os.getenv("BATCH_POLL_INTERVAL_SECONDS", "2"))

    async with session_factory() as session:
        batch = (
            await session.execute(
                select(Batch).where(Batch.ulid == batch_ulid).with_for_update()
            )
        ).scalars().first()
        if batch is None:
            logger.error("Batch %s not found", batch_ulid)
            return
        batch_id = batch.id

        # Terminal already (cancelled/failed/completed): stop the chain without
        # overwriting the status. Cancellation is driven by the cancel endpoint.
        if batch.status in _TERMINAL_BATCH_STATUSES:
            logger.info(
                "Batch %s already %s; coordinator stopping", batch_ulid, batch.status
            )
            return

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
            return  # terminal -> do NOT re-enqueue; the chain stops here

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
                    item.error_message = (
                        "Temporary storage or database failure persisted after "
                        f"{BATCH_ITEM_MAX_ATTEMPTS} attempts."
                    )
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

    # Re-enqueue the next tick outside the session so no DB connection is pinned
    # across the poll interval. If there is no pool (unit tests), the chain simply
    # does not continue -- one tick still runs and asserts its own behavior.
    if pool is not None:
        await pool.enqueue_job(
            "run_batch_coordinator", batch_ulid, _defer_by=poll_interval
        )


# ---------------------------------------------------------------------------
# Orphan sweeper (F-ARCH-1)
# ---------------------------------------------------------------------------


async def sweep_orphaned_batches(ctx: dict) -> int:
    """arq cron: reap batches stuck in pending/processing past the TTL.

    Backstops the reject-don't-orphan path in POST /batch: if the API crashed
    between committing the batch and enqueuing its coordinator (or the
    coordinator died mid-run), the batch would sit 'pending'/'processing'
    forever. This marks such batches failed with reason 'orphaned'.

    Off-switch: BATCH_ORPHAN_SWEEP_ENABLED=0.
    """
    if not _flag("BATCH_ORPHAN_SWEEP_ENABLED", "1"):
        return 0

    from src.services import batch_service

    session_factory = get_session_factory()
    async with session_factory() as session:
        reaped = await batch_service.sweep_orphaned_batches(session)
        if reaped:
            # Commit while the session context is alive. Committing after
            # __aexit__ silently loses the durable reaping transaction with a
            # real AsyncSession even though a loose mock appears to accept it.
            await session.commit()
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
        else:
            item.status = "pending"
            item.completed_at = None
        item.started_at = None
        item.lease_started_at = None
        item.error_message = None
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

    # ---- parse + cost, bounded by the same timeout the route uses -----------
    timeout = _cost_timeout_sec()
    loop = asyncio.get_event_loop()
    report, suffix = await asyncio.wait_for(
        loop.run_in_executor(
            None, _compute_cost_report, file_bytes, filename, options
        ),
        timeout=timeout,
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
# Item processor task
# ---------------------------------------------------------------------------


async def _resolve_transient_batch_item_failure(
    item_ulid: str,
) -> tuple[str, int]:
    """Persist retry, exhaustion, or terminal-parent state in a fresh session."""

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

        if attempts >= BATCH_ITEM_MAX_ATTEMPTS:
            item.status = "failed"
            item.error_message = (
                "Temporary storage or database failure persisted after "
                f"{BATCH_ITEM_MAX_ATTEMPTS} attempts."
            )
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
        item.error_message = None
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
            else:
                import time

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

                # Run analysis
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
                        item_ulid
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
