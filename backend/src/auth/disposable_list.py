"""Redis-cached disposable-email domain list. 24-h TTL.

Fetches the canonical disposable-email-domains list from GitHub raw and
caches it in Redis as a SET. Used by classify() to produce soft_flag
verdicts (per D-11 override: NOT hard_reject — routes to tighter Turnstile
+ 1/7d signup cap instead).
"""
from __future__ import annotations

import os

import httpx
import redis.asyncio as aioredis

SOURCE = (
    "https://raw.githubusercontent.com/disposable-email-domains/"
    "disposable-email-domains/master/disposable_email_blocklist.conf"
)
TTL_S = 24 * 3600
KEY = "disposable_domains"


def _r() -> aioredis.Redis:
    return aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)


async def get_soft_flag_set() -> set[str]:
    """Return set of soft-flag disposable domains. 24-h Redis-cached."""
    r = _r()
    if await r.exists(KEY):
        return set(await r.smembers(KEY))
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            resp = await c.get(SOURCE)
            resp.raise_for_status()
            domains = {
                d.strip().lower() for d in resp.text.splitlines() if d.strip()
            }
    except Exception:
        # Fail-open: hard-reject list in src/auth/disposable.py still guards
        # the dangerous throwaways (mailinator/10minutemail/etc).
        domains = set()
    if domains:
        await r.delete(KEY)
        await r.sadd(KEY, *domains)
        await r.expire(KEY, TTL_S)
    return domains
