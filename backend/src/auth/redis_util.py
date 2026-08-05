"""Shared guard: fail loud (not KeyError) when a Redis-required feature runs
without REDIS_URL configured.

magic_link, disposable_list, and signup_limits all HARD-require Redis. Before
this helper they did ``os.environ["REDIS_URL"]`` and raised a bare ``KeyError``
(surfacing as an opaque 500) when it was unset. That is a silent failure mode:
the caller can't tell the async tier is simply not deployed. This helper raises
a clear, self-describing error instead.
"""
from __future__ import annotations

import inspect
import logging
import os
import threading
from collections.abc import Callable
from typing import Any


_CLIENTS: dict[int, tuple[Any, Callable[[], None]]] = {}
_CLIENTS_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


class RedisRequiredError(RuntimeError):
    """REDIS_URL is required for this feature but is not configured.

    Carries a stable ``code`` so callers/handlers can surface it consistently.
    """

    code = "ASYNC_TIER_UNAVAILABLE"


def require_redis_url() -> str:
    """Return REDIS_URL, or raise RedisRequiredError with a clear message.

    Treats an unset value and the sentinel ``memory://`` (used elsewhere as the
    "no real Redis" fallback) as "not configured".
    """
    url = os.getenv("REDIS_URL")
    if not url or url == "memory://":
        raise RedisRequiredError(
            "This feature requires a Redis instance but REDIS_URL is not "
            "configured (unset or 'memory://'). Magic-link signup, signup rate "
            "limits, and the disposable-domain cache all need Redis. Set "
            "REDIS_URL to a real Redis instance, or disable these features."
        )
    return url


def register_redis_client(client: Any, cache_clear: Callable[[], None]) -> Any:
    """Keep an owned Redis client until deterministic application teardown.

    ``functools.lru_cache.cache_clear`` drops its only strong reference without
    closing the async pool. If that happens after the owning event loop closes,
    redis-py's destructor attempts to close a socket on a dead loop and emits an
    unraisable exception. Registering the cache owner lets shutdown clear and
    close every auth pool while its loop is still alive.
    """
    with _CLIENTS_LOCK:
        _CLIENTS[id(client)] = (client, cache_clear)
    return client


async def close_registered_redis_clients() -> None:
    """Clear and close all process-local auth Redis clients exactly once."""
    with _CLIENTS_LOCK:
        entries = list(_CLIENTS.values())
        _CLIENTS.clear()

    # Clear caches while the registry still owns each strong reference. This
    # prevents a destructor from racing ahead of the awaited pool close.
    for _, cache_clear in entries:
        try:
            cache_clear()
        except Exception:
            logger.exception("failed to clear an auth Redis client cache")
    for client, _ in entries:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is None:
            continue
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception:
            # Every registered pool is independent. One broken close must not
            # prevent the remaining sockets from being released.
            logger.exception("failed to close an auth Redis client")
