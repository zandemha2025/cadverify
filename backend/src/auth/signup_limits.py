"""Per-IP + per-email signup rate limits backed by Redis.

AUTH-08:
- per_ip_signup_limit: sign-ups, email-link sends and Google sign-in starts
  from one address, 60 an hour by default (SIGNUPS_PER_IP_PER_HOUR, 10 to
  1000). That is office-sized: a team of 30 to 60 behind one address can sign
  up and sign in in the same hour. It was 3, which one shared office used up.
- per_email_magic_link_limit: the main guard for email links: 5 links an hour
  to one email, plus a short resend window (MAGIC_LINK_RESEND_SECONDS), so an
  existing user is never locked out for a day after one delayed or lost email.
- per_email_signup_limit: 1 per normalized email per 24h; 1/7d if soft_flagged
  (per D-11 override — disposable domains are soft-flagged into a stricter
  cap rather than hard-rejected).

Only attempts that go ahead count: a request over a limit is refused before
anything is counted, and a caller gives its slot back (``release_slots``) when
a later check refuses the request or the email never goes out. A refusal says
how long until the limit that refused it frees up ("Try again in 37 minutes"),
in its message, ``retry_after_seconds`` and ``Retry-After``. Limits are fixed
one-hour windows from the first counted attempt. Turnstile and the disposable
email checks are unchanged.
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

import os
from functools import lru_cache

import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from src.auth.client_ip import client_ip
from src.auth.magic_keys import magic_hourly_key, magic_send_key
from src.auth.redis_util import register_redis_client, require_redis_url

_TRUTHY = {"1", "true", "yes", "on"}
# (limit, window seconds)
IP_SIGNUP_LIMIT = (60, 3600)
EMAIL_LINKS_PER_HOUR = (5, 3600)
_WHO = {
    "ip": "Too many sign-in and sign-up attempts from this network.",
    "email": "Too many sign-in links sent to this email.",
}


def ip_signup_limit() -> tuple[int, int]:
    """The per-IP limit: ``SIGNUPS_PER_IP_PER_HOUR`` (10 to 1000), default 60."""
    try:
        configured = int(os.getenv("SIGNUPS_PER_IP_PER_HOUR", "").strip() or IP_SIGNUP_LIMIT[0])
    except ValueError:
        configured = IP_SIGNUP_LIMIT[0]
    return max(10, min(1000, configured)), IP_SIGNUP_LIMIT[1]


@lru_cache(maxsize=1)
def _r() -> aioredis.Redis:
    """Reuse one async Redis pool per process across signup attempts."""
    client = aioredis.from_url(require_redis_url(), decode_responses=True)
    return register_redis_client(client, _r.cache_clear)


def ip_signup_limit_enabled() -> bool:
    """Return True when the per-IP signup throttle should run.

    The bypass is for deterministic local/CI proof runs only. Production ignores
    SIGNUP_RATE_LIMIT_DISABLED whenever RELEASE is set.
    """
    disabled = os.getenv("SIGNUP_RATE_LIMIT_DISABLED", "0").strip().lower() in _TRUTHY
    return bool(os.getenv("REDIS_URL")) and not (disabled and not os.getenv("RELEASE"))


def _err(code: str, msg: str, retry: int) -> HTTPException:
    return HTTPException(
        429,
        headers={"Retry-After": str(retry)},
        detail={
            "code": code,
            "message": msg,
            "doc_url": error_doc_url(code),
        },
    )


def _limited(code: str, name: str, wait_seconds: int, message: str | None = None) -> HTTPException:
    from src.auth.two_step import wait_words

    wait = max(1, int(wait_seconds))
    return HTTPException(
        429,
        headers={"Retry-After": str(wait)},
        detail={
            "code": code,
            "message": f"{message or _WHO[name]} Try again in {wait_words(wait)}.",
            "limit": name,
            "retry_after_seconds": wait,
            "doc_url": error_doc_url(code),
        },
    )


async def _wait(r, key: str, window: int) -> int:
    ttl = int(await r.ttl(key))
    return ttl if ttl > 0 else window


async def _reserve(code: str, name: str, key: str, limit: int, window: int) -> str:
    """Count one attempt against ``key``, or refuse without counting.

    Two racing requests can both pass the read; whichever pushes the counter
    past the limit gives its count back and is refused.
    """
    r = _r()
    if int(await r.get(key) or 0) >= limit:
        raise _limited(code, name, await _wait(r, key, window))
    n = int(await r.incr(key))
    if n == 1 or int(await r.ttl(key)) < 0:
        await r.expire(key, window)
    if n > limit:
        await release_slots([key])
        raise _limited(code, name, await _wait(r, key, window))
    return key


async def release_slots(keys) -> None:
    """Give back attempts that didn't go ahead (refused later, or not sent)."""
    keys = [k for k in (keys or ()) if isinstance(k, str) and k]
    if not keys:
        return
    try:
        r = _r()
        for key in keys:
            if int(await r.get(key) or 0) > 0:
                await r.decr(key)
    except Exception:  # best effort: the window still expires on its own
        pass


def ip_signup_key(request: Request) -> str:
    return f"signup:ip:{client_ip(request)}"


async def per_ip_signup_limit(request: Request) -> str:
    """Count this sign-up or sign-in from the caller's address; returns the
    counted key for ``release_slots`` if the request is refused later."""
    limit, window = ip_signup_limit()
    return await _reserve("signup_rate_limited", "ip", ip_signup_key(request), limit, window)


async def per_email_signup_limit(email_normalized: str, soft_flagged: bool) -> None:
    ttl = 7 * 24 * 3600 if soft_flagged else 24 * 3600
    key = f"signup:email:{email_normalized}"
    r = _r()
    # SETNX + EX: first attempt wins; subsequent attempts reject.
    if await r.set(key, "1", nx=True, ex=ttl):
        return
    remaining = await r.ttl(key)
    raise _err(
        "signup_email_limited",
        "This email has already requested a signup recently. Check your inbox.",
        max(remaining, 60),
    )


def _magic_link_resend_seconds(soft_flagged: bool) -> int:
    """Return a short, bounded resend window (default 60s; soft domains 5m)."""
    try:
        configured = int(os.getenv("MAGIC_LINK_RESEND_SECONDS", "60"))
    except ValueError:
        configured = 60
    base = min(900, max(30, configured))
    return max(base, 300) if soft_flagged else base


async def per_email_magic_link_limit(
    email_normalized: str, soft_flagged: bool
) -> str:
    """Throttle delivery without applying the 24h/7d signup lockout.

    The main guard for email links: at most 5 links an hour to one email, and
    none within the short resend window of the last one. Neither expires slowly
    enough to lock out a person whose mail was delayed or lost. Returns the
    counted hourly key for ``release_slots`` if the email never goes out.
    """
    ttl = _magic_link_resend_seconds(soft_flagged)
    key = magic_send_key(email_normalized)
    r = _r()
    if int(await r.exists(key)):
        raise _limited("magic_link_resend_limited", "email", await _wait(r, key, ttl),
                       "A sign-in link was just sent to this email.")
    hourly = await _reserve("magic_link_limited", "email", magic_hourly_key(email_normalized), *EMAIL_LINKS_PER_HOUR)
    if await r.set(key, "1", nx=True, ex=ttl):
        return hourly
    # A racing request for the same email set the window first.
    await release_slots([hourly])
    raise _limited("magic_link_resend_limited", "email", await _wait(r, key, ttl),
                   "A sign-in link was just sent to this email.")
