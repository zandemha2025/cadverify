"""Magic-link signup flow.

Endpoints (mounted under /auth):
  POST /magic/start  → verify Turnstile, classify email, send Resend email
  POST /magic/exchange → consume token and return a server-to-server session
  GET  /magic/verify → compatibility callback for older emailed links

Tokens are HMAC-SHA256 signed with MAGIC_LINK_SECRET (distinct from the
API_KEY_PEPPER). Single-use enforced by Redis GETDEL on the sha256(token)
key; hard TTL of 15 minutes (D-03).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

import redis.asyncio as aioredis
import resend
from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from src.auth.client_ip import client_ip, require_auth_proxy_if_enabled
from src.auth.dashboard_session import session_cookie_domain, set_session_cookie, sign
from src.auth.disposable import classify, normalize_email
from src.auth.disposable_list import get_soft_flag_set
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import (
    create_api_key,
    get_user_session_version,
    upsert_user,
    user_has_active_api_key,
)
from src.auth.redis_util import require_redis_url
from src.auth.signup_limits import (
    ip_signup_limit_enabled,
    per_email_signup_limit,
    per_ip_signup_limit,
)
from src.auth.turnstile import verify_turnstile

router = APIRouter()
TTL = 15 * 60  # 15 minutes per D-03
logger = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status,
        detail={
            "code": code,
            "message": message,
            "doc_url": f"https://docs.cadverify.com/errors#{code}",
        },
    )


class MagicExchangeIn(BaseModel):
    token: str = Field(min_length=32, max_length=4096)


@dataclass(frozen=True)
class MagicLogin:
    user_id: int
    session_version: int
    redirect: str
    key_prefix: str | None = None
    mint_once: str | None = None


def _secret() -> bytes:
    return base64.b64decode(os.environ["MAGIC_LINK_SECRET"])


@lru_cache(maxsize=1)
def _r() -> aioredis.Redis:
    """One Redis pool per process; auth requests must not create pool leaks."""
    return aioredis.from_url(require_redis_url(), decode_responses=True)


def _mint(email_norm: str) -> str:
    nonce = secrets.token_urlsafe(16)
    exp = int(time.time()) + TTL
    payload = f"{email_norm}|{nonce}|{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return (
        base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).rstrip(b"=").decode()
    )


def _verify(token: str) -> str | None:
    try:
        pad = "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(token + pad).decode()
        email_norm, nonce, exp_s, sig = decoded.rsplit("|", 3)
        expected = hmac.new(
            _secret(), f"{email_norm}|{nonce}|{exp_s}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        if int(exp_s) < int(time.time()):
            return None
        return email_norm
    except Exception:
        return None


def _token_key(token: str) -> str:
    return f"magic_link:{hashlib.sha256(token.encode()).hexdigest()}"


def _dashboard_url(path: str) -> str:
    return f"{os.environ['DASHBOARD_ORIGIN'].rstrip('/')}{path}"


async def _consume(token: str) -> MagicLogin:
    """Atomically consume a token and provision its user/session once."""
    email_norm = _verify(token)
    if email_norm is None:
        raise _err(400, "magic_link_invalid", "Magic link invalid or expired.")

    r = _r()
    key = _token_key(token)
    remaining_ttl = await r.ttl(key)
    stored = await r.getdel(key)
    if stored is None:
        raise _err(400, "magic_link_used", "Magic link has already been used.")
    if not hmac.compare_digest(str(stored), email_norm):
        raise _err(400, "magic_link_invalid", "Magic link invalid or expired.")

    try:
        user_id = await upsert_user(
            stored, None, stored, auth_provider="magic_link"
        )
        if await user_has_active_api_key(user_id):
            return MagicLogin(
                user_id=user_id,
                session_version=await get_user_session_version(user_id),
                redirect="/verify",
            )

        full_token, prefix, secret_hash = mint_token()
        await create_api_key(
            user_id, "Default", prefix, hmac_index(full_token), secret_hash
        )
        return MagicLogin(
            user_id=user_id,
            session_version=await get_user_session_version(user_id),
            redirect=f"/settings/developer?new=1&prefix={quote(prefix)}",
            key_prefix=prefix,
            mint_once=full_token,
        )
    except HTTPException:
        # Account deactivation is intentional and must not make the token
        # reusable. Other validation failures happen before consumption.
        raise
    except Exception:
        # A transient DB failure must not burn a still-valid emailed token.
        # NX preserves single-use if another actor somehow recreated the key.
        if remaining_ttl > 0:
            try:
                await r.set(key, stored, ex=remaining_ttl, nx=True)
            except Exception:
                logger.warning("Could not restore magic-link token after failure")
        raise


@router.post("/magic/start")
async def magic_start(
    request: Request,
    email: str = Form(..., max_length=320),
    cf_turnstile_response: str = Form(..., min_length=1, max_length=4096),
):
    # AUTH-08: cheapest check first (per-IP window), then Turnstile, then
    # per-email window. Hard-reject throwaway domains; soft-flag disposables
    # into a tighter 1/7d cap (D-11 override).
    email_clean = (email or "").strip()
    if len(email_clean) > 320 or not _EMAIL_RE.match(email_clean):
        raise _err(400, "invalid_email", "Enter a valid email address.")
    if ip_signup_limit_enabled():
        await per_ip_signup_limit(request)
    await verify_turnstile(
        cf_turnstile_response,
        client_ip(request),
    )
    email_norm = normalize_email(email_clean)
    soft_set = await get_soft_flag_set()
    verdict = classify(email_norm, soft_set)
    if verdict == "hard_reject":
        raise HTTPException(
            400,
            detail={
                "code": "email_domain_blocked",
                "message": "Signups from this email domain are not allowed.",
                "doc_url": "https://docs.cadverify.com/errors#email_domain_blocked",
            },
        )
    await per_email_signup_limit(email_norm, soft_flagged=(verdict == "soft_flag"))
    token = _mint(email_norm)
    key = _token_key(token)
    r = _r()
    await r.setex(key, TTL, email_norm)
    resend.api_key = os.environ["RESEND_API_KEY"]
    # Keep the bearer token in the URL fragment: browsers do not send fragments
    # to the web server or in referrers. The landing page requires a deliberate
    # button press, so basic corporate email scanners do not burn the token.
    link = _dashboard_url(f"/magic/verify#token={token}")
    payload: resend.Emails.SendParams = {
        "from": os.environ.get("RESEND_FROM", "login@cadverify.com"),
        "to": email_clean,
        "subject": "Your CadVerify login link",
        "html": (
            f'<a href="{html.escape(link, quote=True)}">'
            "Sign in to CadVerify (expires in 15 minutes)</a>"
        ),
        "text": f"Sign in to CadVerify (expires in 15 minutes): {link}",
    }
    try:
        # The Resend SDK is synchronous; keep network I/O off the event loop.
        await asyncio.to_thread(resend.Emails.send, payload)
    except Exception:
        # Let the person retry after provider failure. Keep the IP attempt (it
        # still consumed resources), but roll back both the unusable token and
        # per-email send window without logging the email or bearer token.
        try:
            await r.delete(key, f"signup:email:{email_norm}")
        except Exception:
            logger.warning("Could not roll back magic-link send state")
        logger.warning("Magic-link email provider failed")
        raise _err(
            503,
            "email_delivery_unavailable",
            "Email delivery is temporarily unavailable. Please try again.",
        )
    return {"status": "sent"}


@router.post("/magic/exchange")
async def magic_exchange(
    body: MagicExchangeIn, request: Request, response: Response
) -> dict:
    """Exchange a one-time token without putting a session in browser JS."""
    require_auth_proxy_if_enabled(request)
    result = await _consume(body.token)
    response.headers["Cache-Control"] = "no-store"
    return {
        "session": sign(
            result.user_id,
            session_version=result.session_version,
        ),
        "redirect": result.redirect,
        "key_prefix": result.key_prefix,
        "mint_once": result.mint_once,
    }


@router.get("/magic/verify")
async def magic_verify(
    token: str = Query(..., min_length=32, max_length=4096),
):
    """Compatibility for pre-deploy ``?token=`` emails.

    New links land on the dashboard fragment flow and call POST exchange. This
    endpoint remains for already-delivered links and explicit API clients.
    """
    if os.getenv("PRODUCTION_AUTH_PROXY_REQUIRED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        # Old links carried the token in a backend query string. With host-only
        # first-party cookies, consuming it here would set a cookie on the API
        # host and then redirect an unauthenticated browser to the dashboard.
        # Preserve compatibility by moving the still-unconsumed token into the
        # dashboard fragment, where the signed server-to-server exchange owns
        # session establishment.
        return RedirectResponse(
            url=_dashboard_url(f"/magic/verify#token={quote(token, safe='')}"),
            status_code=303,
        )

    result = await _consume(token)
    resp = RedirectResponse(
        url=_dashboard_url(result.redirect), status_code=303
    )
    set_session_cookie(
        resp,
        result.user_id,
        session_version=result.session_version,
    )
    if result.mint_once is not None:
        resp.set_cookie(
            "cv_mint_once",
            result.mint_once,
            max_age=60,
            secure=True,
            httponly=False,
            samesite="lax",
            domain=session_cookie_domain(),
            path="/settings/developer",
        )
    return resp
