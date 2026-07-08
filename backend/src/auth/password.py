"""Email + password authentication router.

The only login method that works end-to-end locally with zero external infra.
Reuses the existing primitives:
  - dashboard_session.sign / require_dashboard_session  (30-day HMAC session)
  - hashing.hash_password / verify_password             (Argon2id)
  - the users table + auth/models helpers
  - disposable classification + (deploy-gated) abuse controls

Session transport: signup/login return the signed token in the JSON body. The
Next.js server (never the browser JS) reads it and sets the first-party httpOnly
`dash_session` cookie; every later request is verified by `require_dashboard_session`
/ `require_api_key` reading that cookie. We never store, log, or return the
plaintext password or the Argon2 hash.
"""
from __future__ import annotations

import asyncio
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from src.auth.dashboard_session import (
    clear_session_cookie,
    require_dashboard_session,
    sign,
)
from src.auth.disposable import classify, normalize_email
from src.auth.hashing import hash_password, password_needs_rehash, verify_password
from src.auth.rate_limit import limiter
from src.auth.models import (
    bump_session_version,
    create_password_user,
    get_user_session_version,
    get_login_credentials,
    get_user_public,
    update_password_hash,
)

router = APIRouter(tags=["auth"])

# A deliberately permissive email shape check (real validation happens at send
# time for magic-link). Matches the existing project posture of plain-str emails
# (no email-validator dependency). Trims surrounding whitespace before checking.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_PASSWORD_MIN = 8
_PASSWORD_MAX = 128


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "code": code,
            "message": message,
            "doc_url": f"https://docs.cadverify.com/errors#{code}",
        },
    )


class SignupIn(BaseModel):
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


def _clean_email(raw: str) -> str:
    """Trim + lowercase the domain; raise 400 invalid_email on a bad shape."""
    email = (raw or "").strip()
    if not _EMAIL_RE.match(email):
        raise _err(400, "invalid_email", "Enter a valid email address.")
    return email


def _validate_password(password: str) -> None:
    """Server-side password policy. Raises 400 weak_password on failure.

    Policy: 8-128 chars, at least one letter AND at least one digit.
    """
    if not isinstance(password, str):
        raise _err(400, "weak_password", "Password is required.")
    if len(password) < _PASSWORD_MIN:
        raise _err(
            400,
            "weak_password",
            f"Password must be at least {_PASSWORD_MIN} characters.",
        )
    if len(password) > _PASSWORD_MAX:
        raise _err(
            400,
            "weak_password",
            f"Password must be at most {_PASSWORD_MAX} characters.",
        )
    if not any(c.isalpha() for c in password):
        raise _err(400, "weak_password", "Password must contain at least one letter.")
    if not any(c.isdigit() for c in password):
        raise _err(400, "weak_password", "Password must contain at least one digit.")


async def _run_abuse_controls(request: Request, email_norm: str) -> str:
    """Disposable hard-reject (always on) + Redis limits (only if REDIS_URL).

    Returns the disposable verdict ('ok' | 'soft_flag' | 'hard_reject' handled
    inline as a 400). Locally (no REDIS_URL) only the in-process disposable list
    runs — no captcha, no rate limiter — so signup works with zero infra.
    """
    # Per-IP throttle: only when Redis is configured (deploy-gated). The local
    # E2E launcher intentionally creates many throwaway accounts from 127.0.0.1;
    # allow that only outside production so repeated proof runs stay deterministic.
    from src.auth.signup_limits import ip_signup_limit_enabled, per_ip_signup_limit

    if ip_signup_limit_enabled():
        await per_ip_signup_limit(request)

    # Disposable classification. Soft-flag set lives in Redis; use an empty set
    # locally so the pure in-process hard-reject list still applies.
    soft_set: set[str] = set()
    verdict = classify(email_norm, soft_set)
    if verdict == "hard_reject":
        raise _err(
            400,
            "email_domain_blocked",
            "Disposable email addresses are not allowed. Use a permanent address.",
        )
    return verdict


def _fire_audit(**kwargs) -> None:
    """Best-effort audit log; never breaks the auth path if the DB/audit fails."""
    try:
        from src.services.audit_service import fire_and_forget_audit

        asyncio.create_task(fire_and_forget_audit(**kwargs))
    except Exception:
        pass


@router.post("/signup")
async def signup(body: SignupIn, request: Request) -> dict:
    email = _clean_email(body.email)
    _validate_password(body.password)

    email_norm = normalize_email(email)
    verdict = await _run_abuse_controls(request, email_norm)

    password_hash = hash_password(body.password)
    uid = await create_password_user(
        email=email,
        email_lower=email_norm,
        password_hash=password_hash,
        disposable_flag=(verdict == "soft_flag"),
    )
    if uid is None:
        raise _err(
            409,
            "email_taken",
            "An account with this email already exists. Log in instead.",
        )

    _fire_audit(
        user_id=uid,
        user_email=email,
        action="auth.signup",
        resource_type="user",
        resource_id=str(uid),
    )
    return {
        "user": {"id": uid, "email": email, "role": "analyst"},
        "session": sign(uid),
    }


@router.post("/login")
# Per-IP brute-force throttle. Failed AND successful attempts both count, so a
# password-guessing bot from one source is capped hard while a human fumbling a
# password still has ample headroom. Enterprise tenants authenticate via
# SAML/OIDC (their own IdP throttles), so shared-NAT contention on this route is
# not the enterprise path. Keyed by IP for unauthenticated callers (see
# rate_limit._api_key_id). Requires REDIS_URL in production to be effective
# across replicas (fail-loud enforced by _resolve_storage_uri).
@limiter.limit("10/minute;100/hour")
async def login(body: LoginIn, request: Request, response: Response) -> dict:
    # `response` is unused by the handler but required so slowapi can inject the
    # X-RateLimit-* headers on the success path (headers_enabled=True).
    email = _clean_email(body.email)
    email_norm = normalize_email(email)

    creds = await get_login_credentials(email_norm)
    # Identical generic failure for: no such user, no password set (OAuth/SAML
    # account), or wrong password. No user enumeration, no provider leak.
    if (
        creds is None
        or creds[1] is None
        or not verify_password(creds[1], body.password)
    ):
        raise _err(401, "invalid_credentials", "Invalid email or password.")

    user_id, password_hash, role = creds

    # §39: refuse a deactivated account — but only AFTER the password check
    # above passed, so an outsider guessing emails still gets the generic
    # invalid_credentials (no account-existence enumeration); only the real
    # offboarded user (correct password) sees account_deactivated.
    from src.auth.models import user_is_active

    if not await user_is_active(user_id):
        raise _err(403, "account_deactivated", "This account has been deactivated.")

    # Opportunistic re-hash if Argon2 parameters were upgraded.
    if password_hash is not None and password_needs_rehash(password_hash):
        try:
            await update_password_hash(user_id, hash_password(body.password))
        except Exception:
            pass

    _fire_audit(
        user_id=user_id,
        user_email=email,
        action="auth.login",
        resource_type="user",
        resource_id=str(user_id),
    )
    return {
        "user": {"id": user_id, "email": email, "role": role},
        "session": sign(
            user_id,
            session_version=await get_user_session_version(user_id),
        ),
    }


@router.post("/logout")
async def logout(response: Response) -> dict:
    # Single-browser logout clears the cookie. Use /logout-all or the admin
    # revoke-sessions route to bump users.session_version and invalidate every
    # outstanding dashboard cookie for the account.
    clear_session_cookie(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(
    response: Response,
    user_id: int = Depends(require_dashboard_session),
) -> dict:
    """Revoke every dashboard session for the current user."""
    version = await bump_session_version(user_id)
    clear_session_cookie(response)
    return {"ok": True, "session_version": version}


@router.get("/me")
async def me(user_id: int = Depends(require_dashboard_session)) -> dict:
    row = await get_user_public(user_id)
    if row is None:
        # Valid signature but the user no longer exists.
        raise _err(401, "dashboard_auth_required", "Dashboard session required.")
    email, role, auth_provider = row
    return {
        "id": user_id,
        "email": email,
        "role": role,
        "auth_provider": auth_provider,
    }
