"""arq worker settings and startup hooks."""
from __future__ import annotations

import asyncio
import logging
import os

from arq import cron, func
from arq.connections import RedisSettings

from src.jobs.batch_tasks import (
    BATCH_ITEM_MAX_ATTEMPTS,
    DIRECT_UPLOAD_PREP_MAX_TRIES,
    DIRECT_UPLOAD_PREP_TIMEOUT_SECONDS,
    direct_upload_prep_concurrency,
    dispatch_webhook,
    prepare_direct_upload_batch,
    reconcile_terminal_batch_items,
    run_batch_coordinator,
    run_batch_item,
    sweep_expired_direct_uploads,
    sweep_orphaned_batches,
)
from src.jobs.heartbeat import worker_heartbeat, write_heartbeat
from src.jobs.arq_backend import reconcile_queued_jobs
from src.jobs.reconstruction_tasks import run_reconstruction_job
from src.jobs.design_tasks import run_design_generation_job
from src.jobs.tasks import run_sam3d_job
from src.config.production import assert_production_operations

logger = logging.getLogger("cadverify.worker")

# Fail before RedisSettings is constructed so a released worker never connects
# with incomplete storage, observability, or transport-security configuration.
assert_production_operations()


async def startup(ctx: dict) -> None:
    """Worker startup: load SAM-3D model into memory and init DB."""
    from src.segmentation.sam3d.config import SAM3DConfig
    from src.segmentation.sam3d.pipeline import _get_backbone

    config = SAM3DConfig.from_env()
    if config.enabled and config.model_path:
        backbone = _get_backbone(config)
        logger.info("SAM-3D backbone loaded: %s", "ready" if backbone.is_loaded else "unavailable")
    else:
        logger.info("SAM-3D disabled or no model path configured")

    # Pre-load reconstruction engine only when the effective backend is a local
    # model that is actually installed. Default is local-only (zero egress); we
    # never preload -- or silently egress via -- a remote backend at startup.
    from src.services import reconstruction_service

    recon = reconstruction_service.check_reconstruction_availability()
    if recon["available"] and recon["effective_backend"] == "local":
        from src.reconstruction.local_triposr import LocalTripoSR
        ctx["reconstruction_engine"] = LocalTripoSR.load()
        logger.info("TripoSR model loaded for local inference")
    else:
        logger.info(
            "Reconstruction engine not preloaded (available=%s effective_backend=%s)",
            recon["available"],
            recon["effective_backend"],
        )

    # Eagerly initialise DB engine + session factory so worker sessions work
    from src.db.engine import init_engine

    await init_engine()
    ctx["db_engine"] = True
    try:
        design_concurrency = int(os.getenv("DESIGN_GENERATION_CONCURRENCY", "2"))
    except ValueError:
        design_concurrency = 2
    design_concurrency = max(1, min(design_concurrency, 8))
    ctx["design_generation_semaphore"] = asyncio.Semaphore(design_concurrency)
    logger.info("Design generation concurrency=%d", design_concurrency)
    # Separate from batch-item concurrency: each permit may hold one ZIP up to
    # BATCH_MAX_ZIP_BYTES on ephemeral disk. DIRECT_UPLOAD_PREP_CONCURRENCY
    # defaults to one so a 20 GiB Fargate task cannot admit twelve 5 GiB files
    # merely because the general ARQ worker has max_jobs=12.
    direct_prep_concurrency = direct_upload_prep_concurrency()
    ctx["direct_upload_preparation_semaphore"] = asyncio.Semaphore(
        direct_prep_concurrency
    )
    logger.info(
        "Direct-upload preparation concurrency=%d", direct_prep_concurrency
    )

    # Write an initial worker heartbeat so /health/deep can see liveness the
    # moment the worker is up (before the first cron tick fires).
    redis = ctx.get("redis")
    if redis is not None:
        try:
            await write_heartbeat(redis)
            logger.info("worker heartbeat written at startup")
        except Exception:  # pragma: no cover - heartbeat must never block boot
            logger.exception("failed to write startup worker heartbeat")


async def shutdown(ctx: dict) -> None:
    """Worker shutdown: dispose DB engine."""
    from src.db.engine import dispose_engine

    await dispose_engine()


class WorkerSettings:
    functions = [
        run_sam3d_job,
        run_batch_coordinator,
        func(run_batch_item, max_tries=BATCH_ITEM_MAX_ATTEMPTS),
        func(
            prepare_direct_upload_batch,
            timeout=DIRECT_UPLOAD_PREP_TIMEOUT_SECONDS,
            max_tries=DIRECT_UPLOAD_PREP_MAX_TRIES,
        ),
        dispatch_webhook,
        run_reconstruction_job,
        run_design_generation_job,
    ]
    # Periodic orphan sweep (F-ARCH-1): reap batches stuck in pending/processing.
    # Runs every 5 minutes and once at worker startup as a backstop.
    cron_jobs = [
        # Durable DB job rows are publication intent. Re-offer queued SAM and
        # reconstruction rows in case Redis accepted a request whose response
        # was lost, or Redis was unavailable when the API committed the row.
        cron(
            reconcile_queued_jobs,
            minute=set(range(0, 60)),
            second={20},
            run_at_startup=True,
        ),
        cron(
            sweep_orphaned_batches,
            minute=set(range(0, 60, 5)),
            run_at_startup=True,
        ),
        cron(
            reconcile_terminal_batch_items,
            minute=set(range(0, 60, 5)),
            run_at_startup=True,
        ),
        # Completed-but-unattached multipart objects are invisible to S3's
        # incomplete-upload lifecycle rule, so database expiry owns cleanup.
        cron(
            sweep_expired_direct_uploads,
            minute=set(range(0, 60, 5)),
            run_at_startup=True,
        ),
        # Lightweight worker liveness heartbeat (every minute) so /health/deep
        # can report a real last-heartbeat age and degrade honestly when the
        # worker is late or absent.
        cron(
            worker_heartbeat,
            second={0},
            run_at_startup=True,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    max_jobs = 12
    # 10 min per-job ceiling (SAM-07). arq wraps every job in
    # asyncio.wait_for(task, job_timeout) and CANCELS it at the deadline, so no
    # job may be designed to outlive this. run_batch_coordinator is therefore a
    # short self-re-enqueueing *tick* (see batch_tasks.py), not a batch-lifetime
    # loop -- each tick finishes in milliseconds, well inside this ceiling, and a
    # long batch is driven by the chain of ticks. A dead chain is reaped by the
    # heartbeat-based orphan sweeper.
    job_timeout = 600
    health_check_interval = 30
    health_check_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")
    retry_jobs = True
    max_tries = 2
