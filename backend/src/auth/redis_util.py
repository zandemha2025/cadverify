"""Shared guard: fail loud (not KeyError) when a Redis-required feature runs
without REDIS_URL configured.

magic_link, disposable_list, and signup_limits all HARD-require Redis. Before
this helper they did ``os.environ["REDIS_URL"]`` and raised a bare ``KeyError``
(surfacing as an opaque 500) when it was unset. That is a silent failure mode:
the caller can't tell the async tier is simply not deployed. This helper raises
a clear, self-describing error instead.
"""
from __future__ import annotations

import os


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
