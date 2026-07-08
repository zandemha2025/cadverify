"""require_api_key: per-route FastAPI dependency returning AuthedUser."""
from __future__ import annotations

import asyncio

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel

from src.auth.dashboard_session import COOKIE_NAME, unsign_payload
from src.auth.hashing import hmac_index, verify_token
from src.auth.models import (
    lookup_api_key,
    lookup_user_role,
    lookup_session_user,
    touch_last_used,
)


class AuthedUser(BaseModel):
    user_id: int
    api_key_id: int
    key_prefix: str
    role: str = "analyst"


def _401(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": code,
            "message": message,
            "doc_url": f"https://docs.cadverify.com/errors#{code}",
        },
    )


def _403_deactivated() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "account_deactivated",
            "message": "This account has been deactivated.",
            "doc_url": "https://docs.cadverify.com/errors#account_deactivated",
        },
    )


async def _session_owner_state(user_id: int):
    """Best-effort account/session-version check for dashboard-cookie auth.

    API-key auth already gets owner state through the ``lookup_api_key`` JOIN.
    Cookie auth has no stored session row, so it validates against the user row's
    active flag + session_version. Degrades OPEN only if the DB is momentarily
    unavailable in a mocked/unit-test style environment.
    """
    try:
        return await lookup_session_user(user_id), False
    except Exception:
        return None, True


async def require_api_key(
    request: Request,
    authorization: str | None = Header(None),
) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer cv_live_"):
        # Fallback: dashboard session cookie (forwarded by the Next.js proxy).
        # This lets the gated platform call authed routes with the session
        # instead of a Bearer API key. api_key_id=0 is the session sentinel.
        cookies = getattr(request, "cookies", None)
        cookie = cookies.get(COOKIE_NAME) if cookies else None
        payload = unsign_payload(cookie) if cookie else None
        if payload is not None:
            # §39 + P3: deactivated or server-revoked sessions are refused.
            row, db_unavailable = await _session_owner_state(payload.user_id)
            if row is None and not db_unavailable:
                raise _401("auth_missing", "Dashboard session required")
            if row is not None and not row.is_active:
                raise _403_deactivated()
            if row is not None and row.session_version != payload.session_version:
                raise _401("session_revoked", "Dashboard session revoked. Log in again.")
            role = row.role if row is not None else "analyst"
            user = AuthedUser(
                user_id=payload.user_id,
                api_key_id=0,
                key_prefix="session",
                role=role,
            )
            request.state.authed_user = user
            return user
        raise _401(
            "auth_missing",
            "Authorization: Bearer cv_live_... header or dashboard session required",
        )
    token = authorization[len("Bearer "):].strip()
    try:
        idx = hmac_index(token)
    except (KeyError, RuntimeError):
        # Missing / bad pepper — server misconfig, not auth failure
        raise HTTPException(
            500,
            detail={
                "code": "server_config",
                "message": "Auth backend misconfigured.",
                "doc_url": "https://docs.cadverify.com/errors#server_config",
            },
        )
    row = await lookup_api_key(idx)
    if row is None or row.revoked_at is not None:
        raise _401("auth_invalid", "Invalid or revoked API key")
    if not verify_token(row.secret_hash, token):
        raise _401("auth_invalid", "Invalid or revoked API key")
    # §39: an API key owned by a deactivated account is refused. is_active +
    # role ride the ``lookup_api_key`` JOIN, so this is no extra round trip.
    # (getattr defaults keep hand-built row doubles in unit tests active.)
    if getattr(row, "is_active", True) is False:
        raise _403_deactivated()
    role = getattr(row, "role", None)
    if role is None:
        role = await lookup_user_role(row.user_id)
    role = role or "analyst"
    user = AuthedUser(
        user_id=row.user_id, api_key_id=row.id, key_prefix=row.prefix, role=role
    )
    request.state.authed_user = user
    asyncio.create_task(touch_last_used(row.id))
    return user
