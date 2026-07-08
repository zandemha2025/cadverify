"""Tests for /health/deep -- strict dependency health with honest degradation.

Same infra-free mocking pattern as test_health.py (patch the Postgres engine
and redis.asyncio.from_url). Asserts:
  * healthy path reports healthy with a real worker heartbeat age + queue depth;
  * a DOWN dependency (Redis unreachable / Postgres down / stale worker) yields
    a structured 503 body -- never a 500, never a fabricated green.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


def _mock_pg_ok():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_cm)
    return patch("src.db.engine.get_engine", return_value=mock_engine)


def _mock_redis(
    *,
    ping_ok=True,
    heartbeat_age_seconds=5,
    arq_key_present=False,
    queue_depth=3,
):
    r = AsyncMock()
    if ping_ok:
        r.ping = AsyncMock()
    else:
        r.ping = AsyncMock(side_effect=Exception("connection refused"))

    if heartbeat_age_seconds is None:
        r.get = AsyncMock(return_value=None)
    else:
        stamp = (
            datetime.now(timezone.utc) - timedelta(seconds=heartbeat_age_seconds)
        ).isoformat()
        r.get = AsyncMock(return_value=stamp)

    r.exists = AsyncMock(return_value=1 if arq_key_present else 0)
    r.zcard = AsyncMock(return_value=queue_depth)
    r.aclose = AsyncMock()
    return patch("redis.asyncio.from_url", return_value=r)


async def _get_deep():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health/deep")


@pytest.mark.asyncio
async def test_deep_healthy_reports_all_deps(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(heartbeat_age_seconds=5, queue_depth=7):
        resp = await _get_deep()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    checks = data["checks"]
    assert checks["postgres"]["ok"] is True
    assert checks["redis"]["ok"] is True
    assert checks["worker"]["state"] == "ok"
    assert checks["worker"]["heartbeat_age_seconds"] == 5
    assert checks["queue"]["depth"] == 7


@pytest.mark.asyncio
async def test_deep_worker_stale_when_heartbeat_old(monkeypatch):
    """A present-but-old heartbeat is 'stale', never 'ok'."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.delenv("WORKER_STRICT_HEALTH", raising=False)
    with _mock_pg_ok(), _mock_redis(heartbeat_age_seconds=100000):
        resp = await _get_deep()
    data = resp.json()
    # Not strict -> still 200 overall, but worker honestly reported stale.
    assert resp.status_code == 200
    assert data["checks"]["worker"]["state"] == "stale"


@pytest.mark.asyncio
async def test_deep_worker_unknown_when_no_heartbeat(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(heartbeat_age_seconds=None, arq_key_present=False):
        resp = await _get_deep()
    data = resp.json()
    assert data["checks"]["worker"]["state"] == "unknown"
    assert data["checks"]["worker"]["heartbeat_age_seconds"] is None


@pytest.mark.asyncio
async def test_deep_worker_strict_degrades_when_stale(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("WORKER_STRICT_HEALTH", "1")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(heartbeat_age_seconds=None):
        resp = await _get_deep()
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["worker"]["state"] == "unknown"
    assert data["checks"]["worker"]["strict"] is True


@pytest.mark.asyncio
async def test_deep_degraded_when_redis_down(monkeypatch):
    """Redis expected but unreachable -> 503 with a structured body (not 500)."""
    monkeypatch.setenv("REDIS_URL", "redis://broken:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(ping_ok=False):
        resp = await _get_deep()
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["redis"]["ok"] is False
    assert data["checks"]["redis"]["error"]  # a reason is reported
    assert data["checks"]["worker"]["state"] == "unavailable"
    assert data["checks"]["queue"]["depth"] is None


@pytest.mark.asyncio
async def test_deep_degraded_when_postgres_down(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with patch("src.db.engine.get_engine", side_effect=Exception("no db")), _mock_redis():
        resp = await _get_deep()
    assert resp.status_code == 503
    data = resp.json()
    assert data["checks"]["postgres"]["ok"] is False
    assert data["checks"]["postgres"]["error"]


@pytest.mark.asyncio
async def test_deep_redis_not_expected_is_ok(monkeypatch):
    """No REDIS_URL, no RELEASE -> async tier not expected -> 200, redis false."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok():
        resp = await _get_deep()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["checks"]["redis"]["ok"] is False
    assert data["checks"]["redis"]["expected"] is False
    assert data["checks"]["worker"]["state"] == "unavailable"
