"""Batch arq tasks -- coordinator, item processor, webhook dispatch.

run_batch_coordinator: Drip-feeds items respecting concurrency limit.
run_batch_item: Runs analysis_service.run_analysis per item.
dispatch_webhook: Delivers webhook with retry scheduling.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import func, select

from src.auth.require_api_key import AuthedUser
from src.db.engine import get_session_factory
from src.db.models import Batch, BatchItem

logger = logging.getLogger("cadverify.batch_tasks")

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Coordinator task
# ---------------------------------------------------------------------------


async def run_batch_coordinator(ctx: dict, batch_ulid: str) -> None:
    """Coordinate batch processing: drip-feed items up to concurrency limit.

    Polls until all items complete or the batch is cancelled. F-ARCH-6: a batch
    can run for hours, so the coordinator must NOT pin one DB session/connection
    open the whole time. It opens a short-lived session per poll and releases it
    back to the pool during the sleep between polls.
    """
    session_factory = get_session_factory()
    pool = ctx.get("redis") or ctx.get("pool")
    poll_interval = int(os.getenv("BATCH_POLL_INTERVAL_SECONDS", "2"))

    # --- Phase 1: initialise (short session) ---------------------------------
    async with session_factory() as session:
        batch = (
            await session.execute(select(Batch).where(Batch.ulid == batch_ulid))
        ).scalars().first()
        if batch is None:
            logger.error("Batch %s not found", batch_ulid)
            return
        batch_id = batch.id

        batch.status = "processing"
        batch.started_at = datetime.now(timezone.utc)
        total = (
            await session.execute(
                select(func.count(BatchItem.id)).where(BatchItem.batch_id == batch_id)
            )
        ).scalar() or 0
        batch.total_items = total
        await session.commit()

        if total == 0:
            batch.status = "completed"
            batch.completed_at = datetime.now(timezone.utc)
            await session.commit()
            return

    # --- Phase 2 + 3: poll loop, releasing the session between polls ---------
    try:
        cancelled = False
        while True:
            async with session_factory() as session:
                batch = (
                    await session.execute(select(Batch).where(Batch.id == batch_id))
                ).scalars().first()
                if batch is None:
                    logger.error("Batch id=%s vanished mid-coordination", batch_id)
                    return

                if batch.status == "cancelled":
                    logger.info("Batch %s cancelled, exiting coordinator", batch_ulid)
                    cancelled = True
                    break

                done_count = batch.completed_items + batch.failed_items
                if done_count >= batch.total_items:
                    break

                # Count active items (queued + processing)
                active_count = (
                    await session.execute(
                        select(func.count(BatchItem.id)).where(
                            BatchItem.batch_id == batch_id,
                            BatchItem.status.in_(["queued", "processing"]),
                        )
                    )
                ).scalar() or 0

                # Enqueue more items up to concurrency limit
                slots = batch.concurrency_limit - active_count
                if slots > 0:
                    pending_items = (
                        await session.execute(
                            select(BatchItem)
                            .where(
                                BatchItem.batch_id == batch_id,
                                BatchItem.status == "pending",
                            )
                            .order_by(
                                # High priority first
                                BatchItem.priority.desc(),
                                BatchItem.created_at.asc(),
                            )
                            .limit(slots)
                        )
                    ).scalars().all()

                    for item in pending_items:
                        item.status = "queued"
                        defer_by = 0 if item.priority == "high" else 1
                        if pool is not None:
                            await pool.enqueue_job(
                                "run_batch_item", item.ulid, _defer_by=defer_by
                            )

                    if pending_items:
                        await session.commit()
            # session released here -- the connection is NOT held during sleep
            await asyncio.sleep(poll_interval)

        # --- Phase 3: finalise (fresh session) -------------------------------
        async with session_factory() as session:
            batch = (
                await session.execute(select(Batch).where(Batch.id == batch_id))
            ).scalars().first()
            if batch is None:
                return

            if not cancelled and batch.status != "cancelled":
                batch.status = "completed"
                batch.completed_at = datetime.now(timezone.utc)
                await session.commit()

            # Fire batch.completed webhook if configured
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

            logger.info(
                "Batch %s coordinator done: status=%s total=%d completed=%d failed=%d",
                batch_ulid,
                batch.status,
                batch.total_items,
                batch.completed_items,
                batch.failed_items,
            )

    except Exception:
        logger.exception("Batch %s coordinator failed", batch_ulid)
        async with session_factory() as session:
            batch = (
                await session.execute(select(Batch).where(Batch.id == batch_id))
            ).scalars().first()
            if batch is not None and batch.status not in ("completed", "cancelled"):
                batch.status = "failed"
                batch.completed_at = datetime.now(timezone.utc)
                await session.commit()


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
            await session.commit()
    if reaped:
        logger.warning("Orphan sweep reaped %d stuck batch(es)", reaped)
    return reaped


# ---------------------------------------------------------------------------
# Item processor task
# ---------------------------------------------------------------------------


async def run_batch_item(ctx: dict, item_ulid: str) -> None:
    """Process a single batch item: run analysis_service.run_analysis.

    Updates item status and batch counters atomically.
    Fires item-level webhook if batch has webhook_url.
    """
    from src.services import analysis_service, batch_service, webhook_service

    session_factory = get_session_factory()

    async with session_factory() as session:
        # Load item and batch
        item = (
            await session.execute(
                select(BatchItem).where(BatchItem.ulid == item_ulid)
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

        # Set processing status
        item.status = "processing"
        item.started_at = datetime.now(timezone.utc)
        await session.commit()

        try:
            import os
            import time

            start = time.time()

            # Read file bytes
            if batch.input_mode == "zip":
                blob_dir = os.getenv("BATCH_BLOB_DIR", "/data/blobs/batch")
                file_path = os.path.join(blob_dir, batch.ulid, item.filename)
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
            elif batch.input_mode == "s3":
                # S3 fetch placeholder -- would use boto3 in production
                raise NotImplementedError("S3 item fetch not yet implemented")
            else:
                raise ValueError(f"Unknown input_mode: {batch.input_mode}")

            # Construct AuthedUser for analysis service
            user = AuthedUser(
                user_id=batch.user_id,
                api_key_id=batch.api_key_id or 0,
                key_prefix="batch",
            )

            # Run analysis
            result = await analysis_service.run_analysis(
                file_bytes=file_bytes,
                filename=item.filename,
                processes=item.process_types,
                rule_pack=item.rule_pack,
                user=user,
                session=session,
            )

            duration_ms = round((time.time() - start) * 1000, 1)

            # Get analysis ID for linking
            analysis_id = await analysis_service.get_latest_analysis_id(
                session, batch.user_id, analysis_service.compute_mesh_hash(file_bytes)
            )

            # Success
            item.status = "completed"
            item.analysis_id = analysis_id
            item.duration_ms = duration_ms
            item.completed_at = datetime.now(timezone.utc)
            await batch_service.update_batch_counters(session, batch.id, "completed_items")
            await session.commit()

            logger.info(
                "BatchItem %s completed: analysis_id=%s duration=%.1fms",
                item_ulid, analysis_id, duration_ms,
            )

        except Exception as exc:
            logger.exception("BatchItem %s failed", item_ulid)
            item.status = "failed"
            item.error_message = str(exc)[:500]
            item.completed_at = datetime.now(timezone.utc)
            await batch_service.update_batch_counters(session, batch.id, "failed_items")
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
