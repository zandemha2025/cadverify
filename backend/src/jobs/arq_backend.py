"""arq-based implementation of the JobQueue protocol."""
from __future__ import annotations

import logging
import os
import inspect
from datetime import datetime, timedelta, timezone
from typing import Optional

from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy import select

from src.db.engine import get_session_factory
from src.db.models import Job
from src.jobs.protocols import JobInfo, JobQueue, JobStatus

logger = logging.getLogger("cadverify.jobs.arq_backend")

# Module-level singleton pool
_pool: Optional[ArqRedis] = None

# Explicit job_type -> arq task-name registry. enqueue() honors the caller's
# job_type via this map instead of hardcoding a single task; an unknown
# job_type raises loudly rather than silently running the wrong task.
_JOB_TYPE_TO_TASK: dict[str, str] = {
    "sam3d": "run_sam3d_job",
    "reconstruction": "run_reconstruction_job",
    "design_generation": "run_design_generation_job",
}


async def get_arq_pool() -> ArqRedis:
    """Return (and lazily create) the arq Redis connection pool."""
    global _pool
    if _pool is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _pool = await create_pool(RedisSettings.from_dsn(redis_url))
    return _pool


async def close_arq_pool() -> None:
    """Close and forget the API-side enqueue pool during ASGI shutdown.

    ARQ owns the worker's Redis connection, but API routes create a separate
    lazy singleton for enqueueing. Closing it avoids leaked sockets/event-loop
    warnings during deploy shutdowns and test process teardown.
    """
    global _pool
    pool, _pool = _pool, None
    if pool is None:
        return
    close = getattr(pool, "aclose", None) or getattr(pool, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


class ArqJobQueue(JobQueue):
    """arq-backed job queue with DB-driven status tracking."""

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, job_type: str, params: dict, idempotency_key: str) -> str:
        """Publish one already-persisted job to ARQ.

        The database row is durable *intent*, not evidence that Redis received
        the task.  Every queued row is therefore offered to ARQ.  ARQ's
        deterministic ``_job_id`` is the publication idempotency boundary: a
        repeated offer returns ``None`` and does not create a second task.
        """
        task_name = _JOB_TYPE_TO_TASK.get(job_type)
        if task_name is None:
            raise ValueError(
                f"Unknown job_type {job_type!r}; expected one of "
                f"{sorted(_JOB_TYPE_TO_TASK)}"
            )

        # The caller must commit the row before publishing so a fast worker can
        # always resolve it.  Existing queued rows still need publication; the
        # historical implementation returned here and silently lost every SAM
        # task created by the validate route.
        async with get_session_factory()() as session:
            persisted = (
                await session.execute(
                    select(Job).where(
                        Job.ulid == idempotency_key,
                    )
                )
            ).scalars().first()

        if persisted is None:
            raise ValueError(
                f"Job {idempotency_key!r} must be committed before publication"
            )
        if persisted.job_type != job_type:
            raise ValueError(
                f"Job {idempotency_key!r} is {persisted.job_type!r}, not {job_type!r}"
            )
        if persisted.status in {"running", "done", "partial", "failed"}:
            logger.info(
                "Skipping publication for job=%s status=%s",
                idempotency_key,
                persisted.status,
            )
            return persisted.ulid
        if persisted.status != "queued":
            raise ValueError(
                f"Job {idempotency_key!r} has unsupported status {persisted.status!r}"
            )

        # Preserve the reconstruction ID used by already-released publishers so
        # an in-flight job cannot be duplicated during a rolling deploy.
        arq_job_id = (
            f"recon_{idempotency_key}"
            if job_type == "reconstruction"
            else idempotency_key
        )
        published = await self._pool.enqueue_job(
            task_name,
            idempotency_key,
            _job_id=arq_job_id,
        )
        logger.info(
            "%s job type=%s task=%s key=%s arq_id=%s",
            "Published" if published is not None else "Publication already present for",
            job_type,
            task_name,
            idempotency_key,
            arq_job_id,
        )
        return idempotency_key

    async def get_status(self, job_id: str) -> JobInfo:
        """Get current job status from the database."""
        async with get_session_factory()() as session:
            job = (
                await session.execute(
                    select(Job).where(Job.ulid == job_id)
                )
            ).scalars().first()

            if job is None:
                return JobInfo(job_id=job_id, status=JobStatus.FAILED, result={"error": "not_found"})

            try:
                status = JobStatus(job.status)
            except ValueError:
                status = JobStatus.QUEUED

            return JobInfo(
                job_id=job.ulid,
                status=status,
                result=job.result_json,
            )

    async def cancel(self, job_id: str) -> bool:
        """Cancel a queued job. Returns True if cancelled."""
        async with get_session_factory()() as session:
            job = (
                await session.execute(
                    select(Job).where(Job.ulid == job_id)
                )
            ).scalars().first()

            if job is None:
                return False

            if job.status in ("running", "done", "partial"):
                return False

            job.status = "failed"
            job.result_json = {"error": "cancelled"}
            await session.commit()

        # Best-effort abort in arq
        try:
            await self._pool.abort_job(job_id)
        except Exception:
            logger.debug("arq abort_job failed for %s (may already be dequeued)", job_id)

        logger.info("Cancelled job %s", job_id)
        return True


async def get_job_queue() -> ArqJobQueue:
    """FastAPI dependency returning the ArqJobQueue singleton."""
    pool = await get_arq_pool()
    return ArqJobQueue(pool)


async def reconcile_queued_jobs(ctx: dict) -> dict[str, int]:
    """Re-offer durable SAM/reconstruction intents that missed publication.

    ARQ runs this cron inside every live worker. Deterministic ARQ IDs make each
    offer safe when the task was already published but its API acknowledgement
    was lost. A short grace period avoids racing the request that created it.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=30)
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Job.ulid, Job.job_type)
                .where(
                    Job.status == "queued",
                    Job.job_type.in_(("sam3d", "reconstruction")),
                    Job.created_at <= cutoff,
                )
                .order_by(Job.created_at.asc())
                .limit(100)
            )
        ).all()

    pool = ctx.get("redis")
    if pool is None:
        pool = await get_arq_pool()
    queue = ArqJobQueue(pool)
    offered = 0
    failed = 0
    for job_ulid, job_type in rows:
        try:
            await queue.enqueue(job_type, {}, job_ulid)
            offered += 1
        except Exception:
            failed += 1
            logger.exception("Queued-job reconciliation failed for %s", job_ulid)
    if rows:
        logger.info(
            "Queued-job reconciliation scanned=%d offered=%d failed=%d",
            len(rows),
            offered,
            failed,
        )
    return {"scanned": len(rows), "offered": offered, "failed": failed}
