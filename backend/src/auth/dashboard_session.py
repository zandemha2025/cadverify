"""Dashboard session: HMAC-signed cookie, 30-day rolling.

Full lifecycle (sign / unsign / set / clear / require). Cookie body is
`{user_id}.{issued_at}` HMAC-SHA256'd with DASHBOARD_SESSION_SECRET; the
`iat` field enforces a 30-day hard expiry on unsign.

Token format (JWT-style):  ``<b64url(body)>.<b64url(sig)>``
Body and signature are base64url-encoded *separately* and joined with a
literal ``.``. Because the base64url alphabet never contains ``.``, the dot
is an unambiguous delimiter and a byte in the raw signature can never be
mistaken for the separator.

Backward compatibility — FAIL CLOSED (intentional): the previous format
base64url-encoded ``body + b"." + sig`` as a *single* blob (no dot in the
resulting string). Such legacy cookies contain zero dots, so ``split(".")``
yields one segment and :func:`unsign` returns ``None``. Old cookies cannot be
parsed unambiguously (the old encoding is prefix-ambiguous with a new
``body`` segment), so we do NOT attempt a dual-format parse. Impact: every
session minted before this deploy is invalidated exactly once — affected
users are silently forced to re-login a single time, after which they hold a
new-format cookie. This is a deliberate one-time cost to eliminate the
~6% spurious-rejection bug in the old format.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from src.config.production import is_production

COOKIE_NAME = "dash_session"
MAX_AGE = 30 * 24 * 3600


@dataclass(frozen=True)
class SessionPayload:
    user_id: int
    issued_at: int
    session_version: int = 0


def _secret() -> bytes:
    raw = base64.b64decode(os.environ["DASHBOARD_SESSION_SECRET"])
    if len(raw) < 32:
        raise RuntimeError("DASHBOARD_SESSION_SECRET must decode to >= 32 bytes")
    return raw


def _b64url_encode(raw: bytes) -> str:
    """base64url without padding (URL/cookie-safe, no ``.`` in alphabet)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(seg: str) -> bytes:
    """Inverse of :func:`_b64url_encode`; restores stripped ``=`` padding."""
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def sign(
    user_id: int,
    issued_at: int | None = None,
    *,
    session_version: int = 0,
) -> str:
    iat = issued_at if issued_at is not None else int(time.time())
    body = f"{user_id}.{iat}.{int(session_version)}".encode()
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
    # JWT-style: encode body and sig as SEPARATE base64url segments joined by a
    # literal ".". The base64url alphabet excludes ".", so a raw signature byte
    # (0x2e) can never be confused with the delimiter — the ~6% split-corruption
    # bug of the old single-blob format is structurally impossible here.
    return f"{_b64url_encode(body)}.{_b64url_encode(sig)}"


def unsign_payload(cookie: str) -> SessionPayload | None:
    try:
        # Exactly two segments. Legacy single-blob cookies contain no "." and
        # yield one segment -> rejected (fail closed; see module docstring).
        parts = cookie.split(".")
        if len(parts) != 2:
            return None
        body = _b64url_decode(parts[0])
        sig = _b64url_decode(parts[1])
        expected = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(sig, expected):
            return None
        fields = body.decode().split(".")
        if len(fields) == 2:
            # Current pre-0028 tokens: user_id.iat. Treat as version 0 so the
            # migration does not force a global logout; any explicit revocation
            # bumps the DB version and invalidates these tokens.
            uid_s, iat_s = fields
            version_s = "0"
        elif len(fields) == 3:
            uid_s, iat_s, version_s = fields
        else:
            return None
        iat = int(iat_s)
        if time.time() - iat > MAX_AGE:
            return None
        return SessionPayload(
            user_id=int(uid_s),
            issued_at=iat,
            session_version=int(version_s),
        )
    except Exception:
        return None


def unsign(cookie: str) -> int | None:
    payload = unsign_payload(cookie)
    return None if payload is None else payload.user_id


def session_cookie_domain() -> str | None:
    """Optional shared parent domain; host-only is the safe default.

    Regulated installs commonly use a non-``cadverify.com`` single-host
    ingress, while the commercial Next.js exchange sets its own first-party
    cookie. Operators that intentionally split SSO callback and dashboard
    subdomains may opt into a reviewed parent domain explicitly.
    """
    return os.getenv("SESSION_COOKIE_DOMAIN", "").strip() or None


def set_session_cookie(
    response: Response,
    user_id: int,
    *,
    session_version: int = 0,
) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sign(user_id, session_version=session_version),
        max_age=MAX_AGE,
        domain=session_cookie_domain(),
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        domain=session_cookie_domain(),
        path="/",
    )


async def require_dashboard_session(request: Request) -> int:
    c = request.cookies.get(COOKIE_NAME)
    payload = unsign_payload(c) if c else None
    if payload is None:
        raise HTTPException(
            401,
            detail={
                "code": "dashboard_auth_required",
                "message": "Dashboard session required.",
                "doc_url": "https://docs.cadverify.com/errors#dashboard_auth_required",
            },
        )
    # §39: a deactivated account's existing dashboard session is refused (this is
    # the validator behind /api/v1/keys and /auth/me). The same DB read also
    # checks session_version, giving operators server-side revocation for
    # otherwise stateless HMAC cookies. Released processes fail closed if the
    # authoritative user/session row cannot be read; local unit-test harnesses
    # retain the historical no-database convenience.
    db_unavailable = False
    try:
        from src.auth.models import lookup_session_user

        row = await lookup_session_user(payload.user_id)
    except Exception as exc:
        if is_production():
            raise HTTPException(
                503,
                detail={
                    "code": "auth_dependency_unavailable",
                    "message": "Authentication is temporarily unavailable.",
                    "doc_url": "https://docs.cadverify.com/errors#auth_dependency_unavailable",
                },
            ) from exc
        row = None
        db_unavailable = True
    if row is None and not db_unavailable:
        raise HTTPException(
            401,
            detail={
                "code": "dashboard_auth_required",
                "message": "Dashboard session required.",
                "doc_url": "https://docs.cadverify.com/errors#dashboard_auth_required",
            },
        )
    if row is not None and not row.is_active:
        raise HTTPException(
            403,
            detail={
                "code": "account_deactivated",
                "message": "This account has been deactivated.",
                "doc_url": "https://docs.cadverify.com/errors#account_deactivated",
            },
        )
    if row is not None and row.session_version != payload.session_version:
        raise HTTPException(
            401,
            detail={
                "code": "session_revoked",
                "message": "This session has been revoked. Log in again.",
                "doc_url": "https://docs.cadverify.com/errors#session_revoked",
            },
        )
    return payload.user_id
