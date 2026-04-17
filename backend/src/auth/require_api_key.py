"""require_api_key: per-route FastAPI dependency returning AuthedUser."""
from __future__ import annotations

import asyncio

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel

from src.auth.hashing import hmac_index, verify_token
from src.auth.models import lookup_api_key, lookup_user_role, touch_last_used


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


async def require_api_key(
    request: Request,
    authorization: str | None = Header(None),
) -> AuthedUser:
    if not authorization or not authorization.startswith("Bearer cv_live_"):
        raise _401(
            "auth_missing",
            "Authorization: Bearer cv_live_... header required",
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
    role = await lookup_user_role(row.user_id)
    user = AuthedUser(
        user_id=row.user_id, api_key_id=row.id, key_prefix=row.prefix, role=role
    )
    request.state.authed_user = user
    asyncio.create_task(touch_last_used(row.id))
    return user
