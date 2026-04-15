"""Google OAuth via authlib.

Mounted under /auth:
  GET /google/start    → 302 to Google with state + nonce
  GET /google/callback → validates state, upserts user, mints API key,
                          303 to /dashboard/keys?new=1 with cv_mint_once cookie
"""
from __future__ import annotations

import os

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.auth.dashboard_session import set_session_cookie
from src.auth.disposable import normalize_email
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import create_api_key, upsert_user
from src.auth.signup_limits import per_ip_signup_limit

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID", "dummy"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "dummy"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter()


def _api_origin() -> str:
    """Derive API origin from DASHBOARD_ORIGIN for the OAuth redirect URI."""
    dash = os.environ["DASHBOARD_ORIGIN"]
    return dash.replace("cadverify.com", "api.cadverify.com")


@router.get("/google/start")
async def google_start(request: Request):
    # AUTH-08: per-IP signup limit applies to OAuth start too (3/hr/IP).
    # Per-email limit is NOT applied here — it would lock out legitimate
    # re-sign-ins; applied only at magic-link start where one email = one
    # fresh signup intent.
    await per_ip_signup_limit(request)
    redirect_uri = f"{_api_origin()}/auth/google/callback"
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
                "doc_url": "https://docs.cadverify.com/errors#oauth_failed",
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
                "doc_url": "https://docs.cadverify.com/errors#oauth_no_email",
            },
        )
    email_norm = normalize_email(email)
    user_id = await upsert_user(email, sub, email_norm)
    full_token, prefix, secret_hash = mint_token()
    await create_api_key(
        user_id, "Default", prefix, hmac_index(full_token), secret_hash
    )
    resp = RedirectResponse(
        url=f"/dashboard/keys?new=1&prefix={prefix}", status_code=303
    )
    # 30-day dashboard session cookie (HMAC-signed, HttpOnly, Secure, SameSite=Lax).
    set_session_cookie(resp, user_id)
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
