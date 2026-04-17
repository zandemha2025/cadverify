"""SAML 2.0 Service Provider authentication via python3-saml.

Mounted under /auth/saml when AUTH_MODE is 'saml' or 'hybrid'.
Provides SSO login, ACS callback, SLO, and SP metadata endpoints.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from src.auth.dashboard_session import clear_session_cookie, set_session_cookie
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import create_api_key, upsert_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/saml")

# Lazy import to avoid hard failure when python3-saml is not installed
_OneLogin_Saml2_Auth = None


def _get_saml2_auth_class():
    global _OneLogin_Saml2_Auth
    if _OneLogin_Saml2_Auth is None:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth

        _OneLogin_Saml2_Auth = OneLogin_Saml2_Auth
    return _OneLogin_Saml2_Auth


def _build_request_data(request: Request) -> dict:
    """Extract request data in the format python3-saml expects."""
    url = request.url
    forwarded_proto = request.headers.get("x-forwarded-proto")
    https = "on" if (url.scheme == "https" or forwarded_proto == "https") else "off"

    server_port = url.port
    if server_port is None:
        server_port = 443 if https == "on" else 80

    return {
        "https": https,
        "http_host": request.headers.get("host", url.hostname or "localhost"),
        "server_port": server_port,
        "script_name": "",
        "get_data": dict(request.query_params),
        "post_data": {},
    }


async def _build_request_data_with_post(request: Request) -> dict:
    """Build request data including POST form data."""
    data = _build_request_data(request)
    try:
        form = await request.form()
        data["post_data"] = dict(form)
    except Exception:
        data["post_data"] = {}
    return data


def _load_saml_settings() -> dict:
    """Load SAML settings from config directory.

    Reads settings.json and advanced_settings.json from the directory
    specified by SAML_CONFIG_DIR env var (default: 'saml/').
    """
    config_dir = Path(os.getenv("SAML_CONFIG_DIR", "saml/"))
    settings_path = config_dir / "settings.json"
    advanced_path = config_dir / "advanced_settings.json"

    if not settings_path.exists():
        raise RuntimeError(
            f"SAML settings file not found at {settings_path}. "
            "Copy saml/settings.json.template to saml/settings.json and configure."
        )

    with open(settings_path) as f:
        settings = json.load(f)

    if advanced_path.exists():
        with open(advanced_path) as f:
            advanced = json.load(f)
        settings.update(advanced)

    return settings


def _build_auth(request: Request, request_data: dict):
    """Construct a OneLogin_Saml2_Auth instance."""
    AuthClass = _get_saml2_auth_class()
    settings = _load_saml_settings()
    return AuthClass(request_data, old_settings=settings)


async def _saml_provision_user(email: str) -> int:
    """Provision or update a SAML-authenticated user.

    Creates user row if not exists, mints an API key if none present.
    SAML users default to 'viewer' role.
    """
    email_lower = email.strip().lower()
    user_id = await upsert_user(
        email=email,
        google_sub=None,
        email_lower=email_lower,
        disposable_flag=False,
    )

    # Mint a default API key for new SAML users
    full_token, prefix, secret_hash = mint_token()
    await create_api_key(
        user_id, "SAML Default", prefix, hmac_index(full_token), secret_hash
    )

    logger.info("SAML user provisioned: email=%s user_id=%d", email_lower, user_id)
    return user_id


@router.get("/login")
async def saml_login(request: Request):
    """Initiate SAML SSO login -- redirect user to IdP."""
    request_data = _build_request_data(request)
    auth = _build_auth(request, request_data)
    sso_url = auth.login()
    return RedirectResponse(url=sso_url, status_code=302)


@router.post("/acs")
async def saml_acs(request: Request):
    """Assertion Consumer Service -- process IdP response after login."""
    request_data = await _build_request_data_with_post(request)
    auth = _build_auth(request, request_data)
    auth.process_response()

    errors = auth.get_errors()
    if errors:
        logger.error("SAML ACS errors: %s reason=%s", errors, auth.get_last_error_reason())
        raise HTTPException(
            400,
            detail={
                "code": "saml_auth_failed",
                "message": f"SAML authentication failed: {', '.join(errors)}",
                "doc_url": "https://docs.cadverify.com/errors#saml_auth_failed",
            },
        )

    if not auth.is_authenticated():
        raise HTTPException(
            401,
            detail={
                "code": "saml_not_authenticated",
                "message": "SAML assertion was not authenticated.",
                "doc_url": "https://docs.cadverify.com/errors#saml_not_authenticated",
            },
        )

    email = auth.get_nameid()
    if not email:
        raise HTTPException(
            400,
            detail={
                "code": "saml_no_email",
                "message": "SAML response did not contain a NameID (email).",
                "doc_url": "https://docs.cadverify.com/errors#saml_no_email",
            },
        )

    user_id = await _saml_provision_user(email)

    dashboard_url = os.getenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    resp = RedirectResponse(url=f"{dashboard_url}/dashboard", status_code=303)
    set_session_cookie(resp, user_id)
    return resp


@router.get("/logout")
async def saml_logout(request: Request):
    """Initiate SAML SLO -- redirect user to IdP for logout."""
    request_data = _build_request_data(request)
    auth = _build_auth(request, request_data)
    slo_url = auth.logout()
    return RedirectResponse(url=slo_url, status_code=302)


@router.post("/sls")
async def saml_sls(request: Request):
    """Single Logout Service -- process IdP logout response."""
    request_data = await _build_request_data_with_post(request)
    auth = _build_auth(request, request_data)
    auth.process_slo()

    errors = auth.get_errors()
    if errors:
        logger.error("SAML SLS errors: %s", errors)

    login_url = os.getenv("DASHBOARD_ORIGIN", "https://cadverify.com") + "/login"
    resp = RedirectResponse(url=login_url, status_code=302)
    clear_session_cookie(resp)
    return resp


@router.get("/metadata")
async def saml_metadata(request: Request):
    """Return SP metadata XML for IdP configuration."""
    request_data = _build_request_data(request)
    auth = _build_auth(request, request_data)
    settings = auth.get_settings()
    metadata = settings.get_sp_metadata()

    errors = settings.validate_metadata(metadata)
    if errors:
        raise HTTPException(
            500,
            detail={
                "code": "saml_metadata_invalid",
                "message": f"SP metadata validation failed: {', '.join(errors)}",
            },
        )

    return Response(content=metadata, media_type="application/xml")
