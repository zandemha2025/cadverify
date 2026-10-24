"""Email-proven password recovery; bearer links never create a session."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
from functools import lru_cache
from urllib.parse import urlsplit

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from src.auth.client_ip import client_ip, require_auth_proxy_if_enabled
from src.auth.disposable import normalize_email
from src.auth.hashing import hash_password
from src.auth.models import get_login_credentials, set_password_hash, user_is_active
from src.auth.password import _clean_email, _err, _released, _require_password_login, _validate_password
from src.auth.rate_limit import limiter
from src.auth.redis_util import register_redis_client, require_redis_url
from src.auth.turnstile import verify_turnstile

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)
TTL = 15 * 60


class ResetStartIn(BaseModel):
    email: str = Field(max_length=320)
    turnstileToken: str = Field(min_length=1, max_length=4096)


class ResetCompleteIn(BaseModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    password: str = Field(max_length=128)


@lru_cache(maxsize=1)
def _r() -> aioredis.Redis:
    client = aioredis.from_url(require_redis_url(), decode_responses=True)
    return register_redis_client(client, _r.cache_clear)


def _token_key(token: str) -> str:
    return f"password-reset:token:{hashlib.sha256(token.encode()).hexdigest()}"


def _require_delivery_config() -> None:
    origin = urlsplit(os.getenv("DASHBOARD_ORIGIN", ""))
    local_http = not _released() and origin.scheme == "http" and origin.hostname in {"localhost", "127.0.0.1"}
    if (
        not all(os.getenv(name, "").strip() for name in ("RESEND_API_KEY", "RESEND_FROM", "REDIS_URL", "TURNSTILE_SECRET"))
        or os.getenv("REDIS_URL") == "memory://"
        or not origin.hostname
        or origin.username or origin.password or origin.query or origin.fragment
        or origin.path not in {"", "/"}
        or (origin.scheme != "https" and not local_http)
    ):
        raise _err(503, "password_reset_unavailable", "Email recovery is temporarily unavailable. Contact nazeem@scalecad.ai for help.")


async def _deliver_reset(email: str) -> None:
    key = None
    try:
        creds = await get_login_credentials(email)
        if not creds or not creds[1] or not await user_is_active(creds[0]):
            return
        token = secrets.token_urlsafe(32)
        key = _token_key(token)
        await _r().set(key, json.dumps({
            "email": email,
            "user_id": creds[0],
            "credential": hashlib.sha256(creds[1].encode()).hexdigest(),
        }), ex=TTL)
        link = f"{os.environ['DASHBOARD_ORIGIN'].rstrip('/')}/reset-password#token={token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            sent = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                json={
                    "from": os.environ["RESEND_FROM"],
                    "to": [email],
                    "subject": "Reset your ScaleCad password",
                    "text": f"Reset your ScaleCad password (expires in 15 minutes):\n\n{link}\n\nIf you did not request this, ignore this email. Your password has not changed.",
                },
            )
            sent.raise_for_status()
    except Exception:
        # Never expose provider/account differences or log the bearer proof.
        logger.warning("Password-reset email could not be delivered")
        if key:
            try:
                await _r().delete(key)
            except RedisError:
                logger.warning("Password-reset cleanup unavailable; token will expire")


@router.post("/password/reset/start")
@limiter.limit("5/hour;20/day")
async def start_password_reset(
    body: ResetStartIn, request: Request, response: Response, background_tasks: BackgroundTasks,
) -> dict:
    _require_password_login()
    require_auth_proxy_if_enabled(request)
    _require_delivery_config()
    email = normalize_email(_clean_email(body.email))
    await verify_turnstile(body.turnstileToken, client_ip(request))
    cooldown = f"password-reset:send:{hashlib.sha256(email.encode()).hexdigest()}"
    try:
        allowed = await _r().set(cooldown, "1", nx=True, ex=60)
    except RedisError:
        raise _err(503, "password_reset_unavailable", "Email recovery is temporarily unavailable. Please try again.")
    # Account lookup and email delivery happen after the identical public reply.
    if allowed:
        background_tasks.add_task(_deliver_reset, email)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/password/reset/complete")
@limiter.limit("10/minute;100/hour")
async def complete_password_reset(body: ResetCompleteIn, request: Request, response: Response) -> dict:
    _require_password_login()
    require_auth_proxy_if_enabled(request)
    _validate_password(body.password)
    invalid = _err(400, "password_reset_invalid", "This reset link is invalid or expired. Request a new link.")
    try:
        stored = await _r().getdel(_token_key(body.token))
    except RedisError:
        raise _err(503, "password_reset_unavailable", "Password recovery is temporarily unavailable. Please try again.")
    if not stored:
        raise invalid
    proof = json.loads(stored)
    creds = await get_login_credentials(proof["email"])
    if (
        not creds or not creds[1] or creds[0] != proof["user_id"]
        or not hmac.compare_digest(hashlib.sha256(creds[1].encode()).hexdigest(), proof["credential"])
        or not await user_is_active(creds[0])
    ):
        raise invalid
    password_hash = await asyncio.to_thread(hash_password, body.password)
    # The existing compare-and-set audits the write and revokes all sessions in
    # the same DB transaction; a concurrent password change makes this fail.
    version = await set_password_hash(creds[0], password_hash, expected_hash=creds[1])
    if version is None:
        raise invalid
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}
