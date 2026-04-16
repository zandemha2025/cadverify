"""Tests for /health endpoint with mocked DB/Redis failures."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.mark.asyncio
async def test_health_ok():
    """Both Postgres and Redis reachable -> 200 ok."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("src.db.engine.get_engine") as mock_engine:
            # Mock async context manager for engine.connect()
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_engine.return_value.connect = MagicMock(return_value=mock_cm)

            with patch.dict("os.environ", {"RELEASE": "test-v1"}, clear=False):
                with patch("os.getenv") as mock_getenv:
                    def _getenv(key, default=None):
                        if key == "REDIS_URL":
                            return None
                        if key == "RELEASE":
                            return "test-v1"
                        return default

                    mock_getenv.side_effect = _getenv
                    resp = await client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["postgres"] is True
    assert data["redis"] is True


@pytest.mark.asyncio
async def test_health_degraded_no_db():
    """Postgres unreachable -> 503 degraded."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("src.db.engine.get_engine", side_effect=Exception("no db")):
            with patch("os.getenv") as mock_getenv:
                def _getenv(key, default=None):
                    if key == "REDIS_URL":
                        return None
                    if key == "RELEASE":
                        return "test-v1"
                    return default

                mock_getenv.side_effect = _getenv
                resp = await client.get("/health")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["postgres"] is False


@pytest.mark.asyncio
async def test_health_degraded_no_redis():
    """Redis unreachable -> 503 degraded."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with patch("src.db.engine.get_engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            mock_engine.return_value.connect = MagicMock(return_value=mock_cm)

            with patch("os.getenv") as mock_getenv:
                def _getenv(key, default=None):
                    if key == "REDIS_URL":
                        return "redis://broken:6379"
                    if key == "RELEASE":
                        return "test-v1"
                    return default

                mock_getenv.side_effect = _getenv

                with patch("redis.asyncio.from_url", side_effect=Exception("connection refused")):
                    resp = await client.get("/health")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["redis"] is False
