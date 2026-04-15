"""Per-IP + per-email signup rate limits backed by Redis.

AUTH-08:
- per_ip_signup_limit: 3 attempts per IP per hour (INCR + EXPIRE window).
- per_email_signup_limit: 1 per normalized email per 24h; 1/7d if soft_flagged
  (per D-11 override — disposable domains are soft-flagged into a stricter
  cap rather than hard-rejected).
"""
from __future__ import annotations

import os

import redis.asyncio as aioredis
from fastapi import HTTPException, Request


def _r() -> aioredis.Redis:
    return aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)


def _err(code: str, msg: str, retry: int) -> HTTPException:
    return HTTPException(
        429,
        headers={"Retry-After": str(retry)},
        detail={
            "code": code,
            "message": msg,
            "doc_url": f"https://docs.cadverify.com/errors#{code}",
        },
    )


async def per_ip_signup_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
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
