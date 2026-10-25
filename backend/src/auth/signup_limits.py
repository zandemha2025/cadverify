"""Per-IP + per-email signup rate limits backed by Redis.

AUTH-08:
- per_ip_signup_limit: 3 attempts per IP per hour (INCR + EXPIRE window).
- per_email_signup_limit: 1 per normalized email per 24h; 1/7d if soft_flagged
  (per D-11 override — disposable domains are soft-flagged into a stricter
  cap rather than hard-rejected).
- per_email_magic_link_limit: short delivery resend window, separate from
  account-creation abuse limits so existing users are never locked out for a
  day after one delayed or lost email.
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

import os
from functools import lru_cache

import redis.asyncio as aioredis
from fastapi import HTTPException, Request

from src.auth.client_ip import client_ip
from src.auth.magic_keys import magic_send_key
from src.auth.redis_util import register_redis_client, require_redis_url

_TRUTHY = {"1", "true", "yes", "on"}


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


async def per_ip_signup_limit(request: Request) -> None:
    ip = client_ip(request)
    key = f"signup:ip:{ip}"
    r = _r()
    n = await r.incr(key)
    if n == 1:
        await r.expire(key, 3600)  # 1-hour window
    if n > 3:
        ttl = await r.ttl(key)
        raise _err(
            "signup_rate_limited",
            "Too many signup attempts from this IP.",
            max(ttl, 60),
        )


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
) -> None:
    """Throttle delivery without applying the 24h/7d signup lockout.

    The IP+Turnstile controls still cap abuse. This key only prevents resend
    storms and deliberately expires quickly enough for delayed/lost mail.
    """
    ttl = _magic_link_resend_seconds(soft_flagged)
    key = magic_send_key(email_normalized)
    r = _r()
    if await r.set(key, "1", nx=True, ex=ttl):
        return
    remaining = await r.ttl(key)
    raise _err(
        "magic_link_resend_limited",
        "A sign-in link was just sent. Wait briefly, then request another.",
        max(remaining, 30),
    )
