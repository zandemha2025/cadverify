"""arq-based implementation of the JobQueue protocol."""
from __future__ import annotations

import logging
import os
from typing import Optional

from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy import select

from src.db.engine import get_session_factory
from src.db.models import Job
from src.jobs.protocols import JobInfo, JobQueue, JobStatus

logger = logging.getLogger("cadverify.jobs.arq_backend")

# Module-level singleton pool
_pool: Optional[ArqRedis] = None


async def get_arq_pool() -> ArqRedis:
    """Return (and lazily create) the arq Redis connection pool."""
    global _pool
    if _pool is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _pool = await create_pool(RedisSettings.from_dsn(redis_url))
    return _pool


class ArqJobQueue(JobQueue):
    """arq-backed job queue with DB-driven status tracking."""

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue(self, job_type: str, params: dict, idempotency_key: str) -> str:
        """Enqueue a job. Uses idempotency_key as the arq job ID to prevent duplicates."""
        # Check for existing job with same idempotency key
        async with get_session_factory()() as session:
            existing = (
                await session.execute(
                    select(Job).where(
                        Job.ulid == idempotency_key,
                    )
                )
            ).scalars().first()

            if existing is not None:
                logger.info("Duplicate enqueue for key=%s, returning existing job", idempotency_key)
                return existing.ulid

        # Enqueue to arq with the idempotency key as job ID
        await self._pool.enqueue_job(
            "run_sam3d_job",
            idempotency_key,
            _job_id=idempotency_key,
        )
        logger.info("Enqueued job type=%s key=%s", job_type, idempotency_key)
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
