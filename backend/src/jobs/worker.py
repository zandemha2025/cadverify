"""arq worker settings and startup hooks."""
from __future__ import annotations

import logging
import os

from arq.connections import RedisSettings

from src.jobs.batch_tasks import dispatch_webhook, run_batch_coordinator, run_batch_item
from src.jobs.tasks import run_sam3d_job

logger = logging.getLogger("cadverify.worker")


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

    # Eagerly initialise DB engine + session factory so worker sessions work
    from src.db.engine import init_engine

    await init_engine()
    ctx["db_engine"] = True


async def shutdown(ctx: dict) -> None:
    """Worker shutdown: dispose DB engine."""
    from src.db.engine import dispose_engine

    await dispose_engine()


class WorkerSettings:
    functions = [run_sam3d_job, run_batch_coordinator, run_batch_item, dispatch_webhook]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    max_jobs = 12
    job_timeout = 600  # 10 min visibility timeout (SAM-07)
    health_check_interval = 30
    retry_jobs = True
    max_tries = 2
