"""Operational queue and worker posture summaries.

This service backs the admin-only ops health endpoint. It reports counts,
staleness, and async-tier liveness without returning customer identifiers,
filenames, webhook payloads, URLs, or user PII.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Batch, BatchItem, Job, WebhookDelivery
from src.services.batch_service import (
    BATCH_HEARTBEAT_STALE_SECONDS,
    BATCH_ORPHAN_TTL_SECONDS,
)

JOB_ACTIVE = {"queued", "running"}
BATCH_ACTIVE = {"pending", "processing"}
BATCH_ITEM_ACTIVE = {"pending", "queued", "processing"}
WEBHOOK_RETRY_ACTIVE = {"pending"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_seconds(dt: Optional[datetime], now: datetime) -> Optional[int]:
    dt = _aware(dt)
    if dt is None:
        return None
    return max(0, int((now - dt).total_seconds()))


def _parse_heartbeat(manifest_json: Optional[dict[str, Any]]) -> Optional[datetime]:
    if not manifest_json:
        return None
    raw = manifest_json.get("heartbeat_at")
    if not raw:
        return None
    try:
        return _aware(datetime.fromisoformat(str(raw)))
    except (TypeError, ValueError):
        return None


def _status_from_counts(counts: dict[str, int], active_statuses: set[str]) -> int:
    return sum(counts.get(status, 0) for status in active_statuses)


def summarize_batch_liveness(
    batches: list[Batch],
    *,
    now: datetime,
    heartbeat_stale_seconds: int = BATCH_HEARTBEAT_STALE_SECONDS,
    orphan_ttl_seconds: int = BATCH_ORPHAN_TTL_SECONDS,
) -> dict[str, Any]:
    """Classify active batches by heartbeat posture.

    This mirrors the orphan-sweeper's contract but does not mutate rows.
    """
    stale_heartbeat = 0
    no_heartbeat_old = 0
    fresh_heartbeat = 0
    missing_heartbeat = 0
    oldest_active_age: Optional[int] = None
    oldest_heartbeat_age: Optional[int] = None

    for batch in batches:
        anchor = _aware(batch.started_at) or _aware(batch.created_at)
        age = _age_seconds(anchor, now)
        if age is not None:
            oldest_active_age = age if oldest_active_age is None else max(oldest_active_age, age)

        heartbeat = _parse_heartbeat(batch.manifest_json)
        hb_age = _age_seconds(heartbeat, now)
        if hb_age is None:
            missing_heartbeat += 1
            if age is not None and age >= orphan_ttl_seconds:
                no_heartbeat_old += 1
        else:
            oldest_heartbeat_age = hb_age if oldest_heartbeat_age is None else max(oldest_heartbeat_age, hb_age)
            if hb_age >= heartbeat_stale_seconds:
                stale_heartbeat += 1
            else:
                fresh_heartbeat += 1

    return {
        "active_count": len(batches),
        "fresh_heartbeat_count": fresh_heartbeat,
        "stale_heartbeat_count": stale_heartbeat,
        "missing_heartbeat_count": missing_heartbeat,
        "no_heartbeat_old_count": no_heartbeat_old,
        "oldest_active_age_seconds": oldest_active_age,
        "oldest_heartbeat_age_seconds": oldest_heartbeat_age,
        "heartbeat_stale_seconds": heartbeat_stale_seconds,
        "orphan_ttl_seconds": orphan_ttl_seconds,
    }


async def _counts_by_status(
    session: AsyncSession,
    model,
    *,
    org_id: Optional[str] = None,
) -> dict[str, int]:
    stmt = (
        select(model.status, func.count())
        .select_from(model)
        .group_by(model.status)
        .order_by(model.status.asc())
    )
    if org_id is not None:
        stmt = stmt.where(model.org_id == org_id)
    rows = (await session.execute(stmt)).all()
    return {str(status): int(count) for status, count in rows}


async def _oldest_age_for_statuses(
    session: AsyncSession,
    model,
    statuses: set[str],
    *,
    org_id: Optional[str],
    now: datetime,
) -> Optional[int]:
    stmt = (
        select(model.created_at)
        .where(model.status.in_(sorted(statuses)))
        .order_by(model.created_at.asc())
        .limit(1)
    )
    if org_id is not None:
        stmt = stmt.where(model.org_id == org_id)
    row = (await session.execute(stmt)).first()
    return _age_seconds(row[0], now) if row else None


async def _active_batches(
    session: AsyncSession,
    *,
    org_id: Optional[str],
) -> list[Batch]:
    stmt = select(Batch).where(Batch.status.in_(sorted(BATCH_ACTIVE)))
    if org_id is not None:
        stmt = stmt.where(Batch.org_id == org_id)
    return list((await session.execute(stmt)).scalars().all())


async def _webhook_retry_summary(
    session: AsyncSession,
    *,
    org_id: Optional[str],
    now: datetime,
) -> dict[str, Any]:
    stmt = select(WebhookDelivery).where(
        WebhookDelivery.status.in_(sorted(WEBHOOK_RETRY_ACTIVE)),
        WebhookDelivery.next_retry_at.is_not(None),
    )
    if org_id is not None:
        stmt = stmt.where(WebhookDelivery.org_id == org_id)
    rows = list((await session.execute(stmt)).scalars().all())

    due = 0
    scheduled = 0
    oldest_due_age: Optional[int] = None
    next_retry_in: Optional[int] = None
    for delivery in rows:
        retry_at = _aware(delivery.next_retry_at)
        if retry_at is None:
            continue
        delta = int((retry_at - now).total_seconds())
        if delta <= 0:
            due += 1
            age = abs(delta)
            oldest_due_age = age if oldest_due_age is None else max(oldest_due_age, age)
        else:
            scheduled += 1
            next_retry_in = delta if next_retry_in is None else min(next_retry_in, delta)

    return {
        "retry_scheduled_count": scheduled,
        "retry_due_count": due,
        "oldest_due_age_seconds": oldest_due_age,
        "next_retry_in_seconds": next_retry_in,
    }


async def probe_async_tier() -> dict[str, Any]:
    """Probe Redis and the arq worker heartbeat without fabricating liveness."""
    redis_url = os.getenv("REDIS_URL")
    redis_configured = bool(redis_url) and redis_url != "memory://"
    health_key = os.getenv("ARQ_HEALTH_KEY", "arq:queue:health-check")
    if not redis_configured:
        return {
            "redis_configured": False,
            "redis": False,
            "worker": "unavailable",
            "health_key": health_key,
        }

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, socket_connect_timeout=2)
        try:
            await r.ping()
            worker_state = "ok" if await r.exists(health_key) else "unknown"
            return {
                "redis_configured": True,
                "redis": True,
                "worker": worker_state,
                "health_key": health_key,
            }
        finally:
            await r.aclose()
    except Exception:
        return {
            "redis_configured": True,
            "redis": False,
            "worker": "unavailable",
            "health_key": health_key,
        }


async def summarize_queue_health(
    session: AsyncSession,
    *,
    org_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build an org-scoped ops health summary for jobs, batches, and webhooks."""
    now = now or _now()
    now = _aware(now) or _now()

    job_counts = await _counts_by_status(session, Job, org_id=org_id)
    batch_counts = await _counts_by_status(session, Batch, org_id=org_id)
    item_counts = await _counts_by_status(session, BatchItem, org_id=org_id)
    webhook_counts = await _counts_by_status(session, WebhookDelivery, org_id=org_id)
    active_batches = await _active_batches(session, org_id=org_id)

    return {
        "generated_at": now.isoformat(),
        "org_id": org_id,
        "async": await probe_async_tier(),
        "jobs": {
            "status_counts": job_counts,
            "active_count": _status_from_counts(job_counts, JOB_ACTIVE),
            "oldest_active_age_seconds": await _oldest_age_for_statuses(
                session, Job, JOB_ACTIVE, org_id=org_id, now=now
            ),
        },
        "batches": {
            "status_counts": batch_counts,
            **summarize_batch_liveness(active_batches, now=now),
        },
        "batch_items": {
            "status_counts": item_counts,
            "active_count": _status_from_counts(item_counts, BATCH_ITEM_ACTIVE),
            "oldest_active_age_seconds": await _oldest_age_for_statuses(
                session, BatchItem, BATCH_ITEM_ACTIVE, org_id=org_id, now=now
            ),
        },
        "webhooks": {
            "status_counts": webhook_counts,
            **await _webhook_retry_summary(session, org_id=org_id, now=now),
        },
    }
