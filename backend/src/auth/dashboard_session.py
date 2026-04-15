"""Dashboard session cookie verification. Fully wired in 02.D.

Provides a minimal HMAC-signed cookie body (user_id) used by dashboard routes.
02.D will extend with TTL, rotation, logout-clear, and sign-in issuance.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from fastapi import HTTPException, Request


def _secret() -> bytes:
    return base64.b64decode(os.environ["DASHBOARD_SESSION_SECRET"])


def sign(user_id: int) -> str:
    body = str(user_id).encode()
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(body + b"." + sig).rstrip(b"=").decode()


def unsign(token: str) -> int | None:
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad)
        body, sig = raw.rsplit(b".", 1)
        expected = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        return int(body)
    except Exception:
        return None


async def require_dashboard_session(request: Request) -> int:
    cookie = request.cookies.get("dash_session")
    uid = unsign(cookie) if cookie else None
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
