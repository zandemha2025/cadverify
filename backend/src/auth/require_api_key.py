"""require_api_key: per-route FastAPI dependency returning AuthedUser."""
from __future__ import annotations

from src.config.public_urls import error_doc_url

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
from src.config.production import is_production


class AuthedUser(BaseModel):
    user_id: int
    api_key_id: int
    key_prefix: str
    role: str = "analyst"
    # Present only for bearer API-key auth. Dashboard sessions intentionally
    # resolve their mutable active org at the route/service boundary.
    org_id: str | None = None
    # What this credential may do: "read" (GET/HEAD/OPTIONS only) or
    # "read_write". A dashboard session is "read_write"; the org-role gates
    # still decide what its person may change.
    scope: str = "read_write"


# Methods a read-only key may use. Everything else changes data (including
# starting a check, which reserves one and stores a record).
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SCOPE_READ = "read"
SCOPE_READ_WRITE = "read_write"


def effective_key_scope(stored_scope: str | None, owner_org_role: str | None) -> str:
    """A key's scope as enforced: a viewer's key is read only, whatever it says.

    ``None`` is a key made before scopes existed (0061): read and write.
    """
    if owner_org_role == "viewer" or stored_scope == SCOPE_READ:
        return SCOPE_READ
    return SCOPE_READ_WRITE


def _date_words(value: object) -> str | None:
    strftime = getattr(value, "strftime", None)
    if strftime is None:
        return None
    return f"{strftime('%b')} {value.day}, {value.year}"


def _401_expired(expires_at: object) -> HTTPException:
    when = _date_words(expires_at)
    return HTTPException(
        status_code=401,
        detail={
            "code": "api_key_expired",
            "message": (
                (f"This API key expired on {when}. " if when else "This API key has expired. ")
                + "Create a new key in Account, API and keys."
            ),
            "doc_url": error_doc_url("api_key_expired"),
        },
    )


def _403_read_only(owner_org_role: str | None, method: str) -> HTTPException:
    if owner_org_role == "viewer":
        message = (
            "This API key belongs to a viewer, so it is read only: it can open "
            "parts and records but not change them or check new parts."
        )
    else:
        message = (
            "This API key is read only: it can open parts and records but not "
            "change them or check new parts. Use a read-and-write key."
        )
    return HTTPException(
        status_code=403,
        detail={
            "code": "api_key_read_only",
            "message": message,
            "method": method,
            "doc_url": error_doc_url("api_key_read_only"),
        },
    )


def _403_two_step_required() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "api_key_two_step_required",
            "message": (
                "This organization requires two-step sign-in. Set it up in "
                "Account › Security, and this key works again."
            ),
            "doc_url": error_doc_url("api_key_two_step_required"),
        },
    )


def _401(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": code,
            "message": message,
            "doc_url": error_doc_url(code),
        },
    )


def _403_deactivated() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "account_deactivated",
            "message": "This account has been deactivated.",
            "doc_url": error_doc_url("account_deactivated"),
        },
    )


async def _session_owner_state(user_id: int):
    """Account/session-version check for dashboard-cookie auth.

    API-key auth already gets owner state through the ``lookup_api_key`` JOIN.
    Cookie auth has no stored session row, so it validates against the user row's
    active flag + session_version. A released process fails closed (503) when
    that row cannot be read, exactly like ``require_dashboard_session``; only a
    local/unit-test harness without a database keeps the no-DB convenience.
    """
    try:
        return await lookup_session_user(user_id), False
    except Exception as exc:
        if is_production():
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "auth_dependency_unavailable",
                    "message": "Authentication is temporarily unavailable.",
                    "doc_url": error_doc_url("auth_dependency_unavailable"),
                },
            ) from exc
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
                org_id=None,
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
                "doc_url": error_doc_url("server_config"),
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
    key_org_id = getattr(row, "org_id", None)
    active_org_id = getattr(row, "active_org_id", None)
    if not key_org_id:
        # Every released api_keys row has a non-null org_id. Missing tenant
        # identity is an invalid credential, never permission to fall back to
        # the user's mutable current organization.
        raise _401("auth_invalid", "Invalid or revoked API key")
    if active_org_id != key_org_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "api_key_org_mismatch",
                "message": (
                    "This API key is bound to a different organization. "
                    "Use a dashboard session to select its issuing organization "
                    "or use a key issued for the active organization."
                ),
                "doc_url": error_doc_url("api_key_org_mismatch"),
            },
        )
    # 0061: an expired key is refused with the date it stopped working. The
    # comparison ran on the database clock in ``lookup_api_key``.
    if getattr(row, "expired", False):
        raise _401_expired(getattr(row, "expires_at", None))
    # The org requires two-step sign-in and the key's owner hasn't set it up:
    # refused, not revoked, so it works again once they have (R1-4). Read in the
    # same ``lookup_api_key`` query.
    if getattr(row, "two_step_owed", False):
        raise _403_two_step_required()
    role = getattr(row, "role", None)
    if role is None:
        role = await lookup_user_role(row.user_id)
    role = role or "analyst"
    owner_org_role = getattr(row, "key_org_role", None)
    scope = effective_key_scope(getattr(row, "scope", None), owner_org_role)
    user = AuthedUser(
        user_id=row.user_id,
        api_key_id=row.id,
        key_prefix=row.prefix,
        role=role,
        org_id=key_org_id,
        scope=scope,
    )
    request.state.authed_user = user
    asyncio.create_task(touch_last_used(row.id))
    method = (getattr(request, "method", None) or "GET").upper()
    if scope == SCOPE_READ and method not in READ_METHODS:
        # Every route that takes a key authenticates here, so a read-only key
        # (or any viewer's key) can never reach a write, whatever the route.
        await _record_read_only_refusal(request, user, owner_org_role, method)
        raise _403_read_only(owner_org_role, method)
    return user


async def _record_read_only_refusal(
    request: Request, user: AuthedUser, owner_org_role: str | None, method: str
) -> None:
    """Log the refused write in the org's audit log; never blocks the refusal."""
    try:
        from src.services.audit_service import record_refusal

        path = getattr(getattr(request, "url", None), "path", "") or ""
        await record_refusal(
            user_id=user.user_id,
            org_id=user.org_id,
            method=method,
            path=path,
            org_role=owner_org_role,
            reason="api_key_read_only",
            key_prefix=user.key_prefix,
        )
    except Exception:  # pragma: no cover - logging must not change the answer
        pass
