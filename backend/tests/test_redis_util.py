"""Redis-required auth features must fail loud (clear error), not KeyError.

magic_link, signup_limits, and disposable_list hard-require REDIS_URL. When it
is unset/memory:// they now raise RedisRequiredError with a clear message
instead of a bare KeyError (F-ARCH-2 reconciliation).
"""
from __future__ import annotations

import pytest

from unittest.mock import AsyncMock, Mock

from src.auth.redis_util import (
    RedisRequiredError,
    close_registered_redis_clients,
    register_redis_client,
    require_redis_url,
)


def test_require_redis_url_returns_when_configured(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://host:6379")
    assert require_redis_url() == "redis://host:6379"


def test_require_redis_url_raises_when_unset(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(RedisRequiredError) as exc:
        require_redis_url()
    assert exc.value.code == "ASYNC_TIER_UNAVAILABLE"


def test_require_redis_url_raises_when_memory_sentinel(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "memory://")
    with pytest.raises(RedisRequiredError):
        require_redis_url()


def test_signup_limits_r_raises_clear_error(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from src.auth.signup_limits import _r

    _r.cache_clear()
    try:
        with pytest.raises(RedisRequiredError):
            _r()
    finally:
        _r.cache_clear()


def test_magic_link_r_raises_clear_error(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from src.auth.magic_link import _r

    _r.cache_clear()
    try:
        with pytest.raises(RedisRequiredError):
            _r()
    finally:
        _r.cache_clear()


def test_disposable_list_r_raises_clear_error(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    from src.auth.disposable_list import _r

    _r.cache_clear()
    try:
        with pytest.raises(RedisRequiredError):
            _r()
    finally:
        _r.cache_clear()


@pytest.mark.asyncio
async def test_registered_redis_clients_clear_cache_before_awaited_close():
    client = Mock()
    client.aclose = AsyncMock()
    cache_clear = Mock()
    assert register_redis_client(client, cache_clear) is client

    await close_registered_redis_clients()

    cache_clear.assert_called_once_with()
    client.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_one_broken_redis_close_does_not_skip_the_rest():
    broken = Mock()
    broken.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
    healthy = Mock()
    healthy.aclose = AsyncMock()
    register_redis_client(broken, Mock())
    register_redis_client(healthy, Mock())

    await close_registered_redis_clients()

    broken.aclose.assert_awaited_once_with()
    healthy.aclose.assert_awaited_once_with()
