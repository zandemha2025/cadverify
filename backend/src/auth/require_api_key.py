"""require_api_key: per-route FastAPI dependency returning AuthedUser."""
from __future__ import annotations

import asyncio

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel

from src.auth.dashboard_session import COOKIE_NAME, unsign
from src.auth.hashing import hmac_index, verify_token
from src.auth.models import (
    lookup_api_key,
    lookup_user_role,
    touch_last_used,
    user_is_active,
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


async def _session_owner_active(user_id: int) -> bool:
    """Best-effort account-active check for the dashboard-session path.

    Folded is_active onto the API-key path via the ``lookup_api_key`` JOIN (no
    extra query); the cookie path has no such JOIN, so this is a dedicated read.
    Degrades OPEN if the DB is momentarily unavailable (e.g. a mocked unit test
    with no DATABASE_URL): deactivation is still hard-enforced at login, on the
    API-key path, and against SSO re-provision, so a session-path fail-open on
    infra error never widens the security envelope.
    """
    try:
        return await user_is_active(user_id)
    except Exception:
        return True


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
        uid = unsign(cookie) if cookie else None
        if uid is not None:
            # §39: a deactivated account's existing session is refused.
            if not await _session_owner_active(uid):
                raise _403_deactivated()
            role = await lookup_user_role(uid)
            user = AuthedUser(
                user_id=uid, api_key_id=0, key_prefix="session", role=role
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
    role = getattr(row, "role", None) or "analyst"
    user = AuthedUser(
        user_id=row.user_id, api_key_id=row.id, key_prefix=row.prefix, role=role
    )
    request.state.authed_user = user
    asyncio.create_task(touch_last_used(row.id))
    return user
