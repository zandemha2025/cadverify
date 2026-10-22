"""Google OAuth via authlib.

Mounted under /auth:
  GET /google/start    → 302 to Google with state + nonce
  GET /google/callback → validates state, upserts user, mints API key,
                          303 to /settings/developer?new=1 with cv_mint_once cookie
"""
from __future__ import annotations

from src.config.public_urls import api_origin, error_doc_url

import os

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.auth.dashboard_session import session_cookie_domain, set_session_cookie
from src.auth.disposable import normalize_email
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import (
    create_api_key,
    get_user_session_version,
    upsert_user,
    user_has_active_api_key,
)
from src.auth.signup_limits import ip_signup_limit_enabled, per_ip_signup_limit

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID", "dummy"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "dummy"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter()


@router.get("/google/start")
async def google_start(request: Request):
    # AUTH-08: the per-IP signup limit applies to OAuth start too (office-sized,
    # SIGNUPS_PER_IP_PER_HOUR, default 60 an hour).
    # Per-email limit is NOT applied here — it would lock out legitimate
    # re-sign-ins; applied only at magic-link start where one email = one
    # fresh signup intent.
    #
    # Gated behind REDIS_URL exactly like the password-signup path
    # (src/auth/password.py::_run_abuse_controls) — deploy-gated: no rate
    # limiting in local/dev without Redis configured. Previously this call
    # was unconditional, so it raised KeyError (os.environ["REDIS_URL"]) on
    # any environment without Redis instead of degrading gracefully.
    if ip_signup_limit_enabled():
        await per_ip_signup_limit(request)
    redirect_uri = f"{api_origin()}/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception:
        raise HTTPException(
            400,
            detail={
                "code": "oauth_failed",
                "message": "Google sign-in failed.",
                "doc_url": error_doc_url("oauth_failed"),
            },
        )
    info = token.get("userinfo") or {}
    email = info.get("email")
    sub = info.get("sub")
    if not email or not sub:
        raise HTTPException(
            400,
            detail={
                "code": "oauth_no_email",
                "message": "Google did not return a verified email.",
                "doc_url": error_doc_url("oauth_no_email"),
            },
        )
    # Only an address Google itself has verified may create or reach an
    # account; an unverified one could name someone else's existing account.
    verified = info.get("email_verified")
    if not (verified is True or (isinstance(verified, str) and verified.strip().lower() == "true")):
        raise HTTPException(
            403,
            detail={
                "code": "oauth_email_unverified",
                "message": "Google has not verified this email address.",
                "doc_url": error_doc_url("oauth_email_unverified"),
            },
        )
    email_norm = normalize_email(email)
    user_id = await upsert_user(email, sub, email_norm, auth_provider="google")

    # Google is a consumer sign-in, not the organization's identity provider:
    # an account with two-step on (or in an org that requires it) is asked for
    # its code exactly as after a password. No session and no key until then.
    from src.auth.two_step import CHALLENGE_TTL, make_challenge, sign_in_requirement_for

    two_step = await sign_in_requirement_for(user_id)
    if two_step is not None:
        from src.config.public_urls import dashboard_origin

        resp = RedirectResponse(url=f"{dashboard_origin()}/login/two-step", status_code=303)
        resp.set_cookie(
            "cv_two_step",
            make_challenge(user_id, await get_user_session_version(user_id), two_step, "google"),
            max_age=CHALLENGE_TTL,
            secure=True,
            httponly=True,
            samesite="lax",
            domain=session_cookie_domain(),
            path="/",
        )
        return resp

    # The sign-in row: where it came from (the browser comes back from Google
    # straight to the API, so the verified proxy IP or else the direct peer) and
    # the browser. Never Google's tokens or subject. A sign-in that owes a
    # two-step code is recorded when the code is checked (two_step_routes).
    from src.auth.client_ip import client_ip, client_user_agent
    from src.services.audit_service import log_action

    await log_action(
        user_id=user_id,
        user_email=email_norm,
        action="auth.login",
        resource_type="session",
        detail={"auth_provider": "google"},
        ip_address=client_ip(request),
        user_agent=client_user_agent(request),
    )

    # Mint a key only when the account has none active (S3). A returning user
    # keeps their existing key(s) — logging in must not spawn a fresh key nor
    # attempt a one-time reveal of a secret we can no longer show.
    if await user_has_active_api_key(user_id):
        resp = RedirectResponse(url="/settings/developer", status_code=303)
        set_session_cookie(
            resp,
            user_id,
            session_version=await get_user_session_version(user_id),
        )
        return resp

    full_token, prefix, secret_hash = mint_token()
    await create_api_key(
        user_id, "Default", prefix, hmac_index(full_token), secret_hash
    )
    resp = RedirectResponse(
        url=f"/settings/developer?new=1&prefix={prefix}", status_code=303
    )
    # 30-day dashboard session cookie (HMAC-signed, HttpOnly, Secure, SameSite=Lax).
    set_session_cookie(
        resp,
        user_id,
        session_version=await get_user_session_version(user_id),
    )
    resp.set_cookie(
        "cv_mint_once",
        full_token,
        max_age=60,
        secure=True,
        httponly=False,
        samesite="lax",
        domain=session_cookie_domain(),
        path="/settings/developer",
    )
    return resp
