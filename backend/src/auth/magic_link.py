"""Magic-link signup flow.

Endpoints (mounted under /auth):
  POST /magic/start  → verify Turnstile, classify email, send Resend email
  GET  /magic/verify → single-use HMAC check via Redis GETDEL, mint API key

Tokens are HMAC-SHA256 signed with MAGIC_LINK_SECRET (distinct from the
API_KEY_PEPPER). Single-use enforced by Redis GETDEL on the sha256(token)
key; hard TTL of 15 minutes (D-03).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

import redis.asyncio as aioredis
import resend
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.auth.disposable import classify, normalize_email
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import create_api_key, upsert_user
from src.auth.turnstile import verify_turnstile

router = APIRouter()
TTL = 15 * 60  # 15 minutes per D-03


def _secret() -> bytes:
    return base64.b64decode(os.environ["MAGIC_LINK_SECRET"])


def _r() -> aioredis.Redis:
    return aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)


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


@router.post("/magic/start")
async def magic_start(
    request: Request,
    email: str = Form(...),
    cf_turnstile_response: str = Form(...),
):
    await verify_turnstile(
        cf_turnstile_response,
        request.client.host if request.client else None,
    )
    email_norm = normalize_email(email)
    verdict = classify(email_norm, set())  # 02.D wires soft_flag_set from Redis
    if verdict == "hard_reject":
        raise HTTPException(
            400,
            detail={
                "code": "email_domain_blocked",
                "message": "Signups from this email domain are not allowed.",
                "doc_url": "https://docs.cadverify.com/errors#email_domain_blocked",
            },
        )
    token = _mint(email_norm)
    key = f"magic_link:{hashlib.sha256(token.encode()).hexdigest()}"
    await _r().setex(key, TTL, email_norm)
    resend.api_key = os.environ["RESEND_API_KEY"]
    link = f"{os.environ['DASHBOARD_ORIGIN']}/magic/verify?token={token}"
    resend.Emails.send(
        {
            "from": os.environ.get("RESEND_FROM", "login@cadverify.com"),
            "to": email,
            "subject": "Your CadVerify login link",
            "html": f'<a href="{link}">Sign in (expires in 15 minutes)</a>',
        }
    )
    return {"status": "sent"}


@router.get("/magic/verify")
async def magic_verify(token: str):
    email_norm = _verify(token)
    if email_norm is None:
        raise HTTPException(
            400,
            detail={
                "code": "magic_link_invalid",
                "message": "Magic link invalid or expired.",
                "doc_url": "https://docs.cadverify.com/errors#magic_link_invalid",
            },
        )
    r = _r()
    key = f"magic_link:{hashlib.sha256(token.encode()).hexdigest()}"
    stored = await r.getdel(key)  # single-use
    if stored is None:
        raise HTTPException(
            400,
            detail={
                "code": "magic_link_used",
                "message": "Magic link has already been used.",
                "doc_url": "https://docs.cadverify.com/errors#magic_link_used",
            },
        )
    user_id = await upsert_user(stored, None, stored)
    full_token, prefix, secret_hash = mint_token()
    await create_api_key(
        user_id, "Default", prefix, hmac_index(full_token), secret_hash
    )
    resp = RedirectResponse(
        url=f"/dashboard/keys?new=1&prefix={prefix}", status_code=303
    )
    # Transient reveal cookie; 02.D will add dash_session separately.
    resp.set_cookie(
        "cv_mint_once",
        full_token,
        max_age=60,
        secure=True,
        httponly=False,
        samesite="lax",
        domain=".cadverify.com",
        path="/dashboard/keys",
    )
    return resp
