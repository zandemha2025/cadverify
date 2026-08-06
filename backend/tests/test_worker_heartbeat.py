"""Tests for the lightweight arq worker heartbeat (src.jobs.heartbeat)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from src.jobs import heartbeat


@pytest.mark.asyncio
async def test_write_heartbeat_sets_key_with_ttl(monkeypatch):
    monkeypatch.setenv("WORKER_HEARTBEAT_KEY", "test:hb")
    monkeypatch.setenv("WORKER_HEARTBEAT_TTL_SECONDS", "42")
    redis = AsyncMock()
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
    value = await heartbeat.write_heartbeat(redis, now=now)
    assert value == now.isoformat()
    redis.set.assert_awaited_once()
    args, kwargs = redis.set.call_args
    assert args[0] == "test:hb"
    assert args[1] == now.isoformat()
    assert kwargs["ex"] == 42


@pytest.mark.asyncio
async def test_read_heartbeat_age_recent(monkeypatch):
    monkeypatch.setenv("WORKER_HEARTBEAT_KEY", "test:hb")
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
    written = (now - timedelta(seconds=12)).isoformat()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=written)
    age = await heartbeat.read_heartbeat_age(redis, now=now)
    assert age == 12


@pytest.mark.asyncio
async def test_read_heartbeat_age_bytes_value(monkeypatch):
    now = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
    written = (now - timedelta(seconds=3)).isoformat().encode()
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=written)
    age = await heartbeat.read_heartbeat_age(redis, now=now)
    assert age == 3


@pytest.mark.asyncio
async def test_read_heartbeat_age_absent_is_none():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    assert await heartbeat.read_heartbeat_age(redis) is None


@pytest.mark.asyncio
async def test_read_heartbeat_age_unparseable_is_none():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="not-a-timestamp")
    assert await heartbeat.read_heartbeat_age(redis) is None


def test_classify_worker_states():
    # redis down -> unavailable regardless of anything else
    assert heartbeat.classify_worker(
        redis_ok=False, heartbeat_age=1, arq_key_present=True
    ) == "unavailable"
    # fresh heartbeat -> ok
    assert heartbeat.classify_worker(
        redis_ok=True, heartbeat_age=5, arq_key_present=False, stale_seconds=90
    ) == "ok"
    # old heartbeat -> stale (never fabricated ok)
    assert heartbeat.classify_worker(
        redis_ok=True, heartbeat_age=1000, arq_key_present=False, stale_seconds=90
    ) == "stale"
    # no heartbeat but arq key present -> ok (coarse fallback)
    assert heartbeat.classify_worker(
        redis_ok=True, heartbeat_age=None, arq_key_present=True
    ) == "ok"
    # no heartbeat, no arq key -> unknown (honest uncertainty)
    assert heartbeat.classify_worker(
        redis_ok=True, heartbeat_age=None, arq_key_present=False
    ) == "unknown"


@pytest.mark.asyncio
async def test_worker_heartbeat_cron_writes(monkeypatch):
    redis = AsyncMock()
    await heartbeat.worker_heartbeat({"redis": redis})
    redis.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_heartbeat_cron_no_redis_is_safe():
    # Must not raise if redis is missing from ctx.
    await heartbeat.worker_heartbeat({})
