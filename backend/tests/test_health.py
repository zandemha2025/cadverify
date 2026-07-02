"""Tests for /health -- honest async-tier reporting (F-ARCH-2).

/health must never claim Redis is healthy when it is absent. When the async
tier is *expected* (real REDIS_URL, or RELEASE set) but unreachable, status is
'degraded' (503). Worker state is probed honestly via the arq health-check key.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app


def _mock_pg_ok():
    """patch() target that makes the Postgres probe succeed."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_cm)
    return patch("src.db.engine.get_engine", return_value=mock_engine)


def _mock_redis(ping_ok=True, worker_key_present=False):
    """patch() target for redis.asyncio.from_url."""
    r = AsyncMock()
    if ping_ok:
        r.ping = AsyncMock()
    else:
        r.ping = AsyncMock(side_effect=Exception("connection refused"))
    r.exists = AsyncMock(return_value=1 if worker_key_present else 0)
    r.aclose = AsyncMock()
    return patch("redis.asyncio.from_url", return_value=r)


async def _get_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


@pytest.mark.asyncio
async def test_health_ok_with_real_redis(monkeypatch):
    """Postgres up + real Redis reachable -> 200 ok, redis true."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(ping_ok=True, worker_key_present=True):
        resp = await _get_health()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["postgres"] is True
    assert data["redis"] is True
    assert data["async"]["redis"] is True
    assert data["async"]["worker"] == "ok"
    assert data["async"]["expected"] is True


@pytest.mark.asyncio
async def test_health_worker_unknown_when_no_heartbeat(monkeypatch):
    """Redis reachable but no arq heartbeat key -> worker 'unknown' (honest)."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(ping_ok=True, worker_key_present=False):
        resp = await _get_health()
    data = resp.json()
    assert resp.status_code == 200
    assert data["async"]["worker"] == "unknown"


@pytest.mark.asyncio
async def test_health_degraded_when_redis_unreachable(monkeypatch):
    """Real REDIS_URL configured but unreachable -> 503 degraded, redis false."""
    monkeypatch.setenv("REDIS_URL", "redis://broken:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok(), _mock_redis(ping_ok=False):
        resp = await _get_health()
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["redis"] is False
    assert data["async"]["redis"] is False
    assert data["async"]["worker"] == "unavailable"


@pytest.mark.asyncio
async def test_health_degraded_no_db(monkeypatch):
    """Postgres unreachable -> 503 degraded."""
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.delenv("RELEASE", raising=False)
    with patch("src.db.engine.get_engine", side_effect=Exception("no db")), \
         _mock_redis(ping_ok=True):
        resp = await _get_health()
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["postgres"] is False


@pytest.mark.asyncio
async def test_health_no_redis_not_expected_is_ok(monkeypatch):
    """No REDIS_URL and no RELEASE -> async tier not expected -> ok, redis false.

    This is the key honesty fix: we no longer claim redis:true when absent, but
    we also don't spuriously flag degraded when the async tier isn't expected.
    """
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RELEASE", raising=False)
    with _mock_pg_ok():
        resp = await _get_health()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["redis"] is False
    assert data["async"]["redis"] is False
    assert data["async"]["worker"] == "unavailable"
    assert data["async"]["expected"] is False


@pytest.mark.asyncio
async def test_health_degraded_when_expected_but_absent_in_production(monkeypatch):
    """RELEASE set (production) but no Redis -> async expected+absent -> degraded."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("RELEASE", "prod-v1")
    with _mock_pg_ok():
        resp = await _get_health()
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["async"]["expected"] is True
    assert data["async"]["redis"] is False


@pytest.mark.asyncio
async def test_health_strict_off_switch(monkeypatch):
    """ASYNC_STRICT_HEALTH=0 makes async-tier absence non-fatal (documented off-switch)."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("RELEASE", "prod-v1")
    monkeypatch.setenv("ASYNC_STRICT_HEALTH", "0")
    with _mock_pg_ok():
        resp = await _get_health()
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # still reported truthfully
    assert data["redis"] is False
    assert data["async"]["expected"] is True
