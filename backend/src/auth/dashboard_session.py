"""Dashboard session: HMAC-signed cookie, 30-day rolling.

Full lifecycle (sign / unsign / set / clear / require). Cookie body is
`{user_id}.{issued_at}` HMAC-SHA256'd with DASHBOARD_SESSION_SECRET; the
`iat` field enforces a 30-day hard expiry on unsign.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request, Response

COOKIE_NAME = "dash_session"
MAX_AGE = 30 * 24 * 3600


def _secret() -> bytes:
    raw = base64.b64decode(os.environ["DASHBOARD_SESSION_SECRET"])
    if len(raw) < 32:
        raise RuntimeError("DASHBOARD_SESSION_SECRET must decode to >= 32 bytes")
    return raw


def sign(user_id: int, issued_at: int | None = None) -> str:
    iat = issued_at if issued_at is not None else int(time.time())
    body = f"{user_id}.{iat}".encode()
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(body + b"." + sig).rstrip(b"=").decode()


def unsign(cookie: str) -> int | None:
    try:
        pad = "=" * (-len(cookie) % 4)
        raw = base64.urlsafe_b64decode(cookie + pad)
        body, sig = raw.rsplit(b".", 1)
        expected = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        uid_s, iat_s = body.decode().split(".", 1)
        iat = int(iat_s)
        if time.time() - iat > MAX_AGE:
            return None
        return int(uid_s)
    except Exception:
        return None


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sign(user_id),
        max_age=MAX_AGE,
        domain=os.getenv("SESSION_COOKIE_DOMAIN", ".cadverify.com"),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        domain=os.getenv("SESSION_COOKIE_DOMAIN", ".cadverify.com"),
        path="/",
    )


async def require_dashboard_session(request: Request) -> int:
    c = request.cookies.get(COOKIE_NAME)
    uid = unsign(c) if c else None
    if uid is None:
        raise HTTPException(
            401,
            detail={
                "code": "dashboard_auth_required",
                "message": "Dashboard session required.",
                "doc_url": "https://docs.cadverify.com/errors#dashboard_auth_required",
            },
        )
    return uid
