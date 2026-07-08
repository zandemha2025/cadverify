from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services import ops_health_service as svc


def _batch(*, created_age: int, heartbeat_age: int | None):
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    manifest = (
        {"heartbeat_at": (now - timedelta(seconds=heartbeat_age)).isoformat()}
        if heartbeat_age is not None
        else None
    )
    return SimpleNamespace(
        created_at=now - timedelta(seconds=created_age),
        started_at=None,
        manifest_json=manifest,
    )


def test_batch_liveness_separates_fresh_stale_and_missing_heartbeats():
    now = datetime(2026, 7, 7, tzinfo=timezone.utc)
    summary = svc.summarize_batch_liveness(
        [
            _batch(created_age=1000, heartbeat_age=5),
            _batch(created_age=1000, heartbeat_age=700),
            _batch(created_age=30, heartbeat_age=None),
            _batch(created_age=30_000, heartbeat_age=None),
        ],
        now=now,
        heartbeat_stale_seconds=600,
        orphan_ttl_seconds=3600,
    )

    assert summary["active_count"] == 4
    assert summary["fresh_heartbeat_count"] == 1
    assert summary["stale_heartbeat_count"] == 1
    assert summary["missing_heartbeat_count"] == 2
    assert summary["no_heartbeat_old_count"] == 1
    assert summary["oldest_active_age_seconds"] == 30_000
    assert summary["oldest_heartbeat_age_seconds"] == 700


@pytest.mark.asyncio
async def test_probe_async_tier_without_redis_is_honest_unavailable(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    result = await svc.probe_async_tier()
    assert result["redis_configured"] is False
    assert result["redis"] is False
    assert result["worker"] == "unavailable"


@pytest.mark.asyncio
async def test_probe_async_tier_with_worker_heartbeat(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    redis = AsyncMock()
    redis.ping = AsyncMock()
    redis.exists = AsyncMock(return_value=1)
    redis.aclose = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=redis):
        result = await svc.probe_async_tier()

    assert result["redis_configured"] is True
    assert result["redis"] is True
    assert result["worker"] == "ok"
    redis.exists.assert_awaited_once()


@pytest.mark.asyncio
async def test_probe_async_tier_with_no_worker_heartbeat(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    redis = AsyncMock()
    redis.ping = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    redis.aclose = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=redis):
        result = await svc.probe_async_tier()

    assert result["redis"] is True
    assert result["worker"] == "unknown"
