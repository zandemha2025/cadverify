"""SAML 2.0 Service Provider authentication via python3-saml.

Mounted under /auth/saml when AUTH_MODE is 'saml' or 'hybrid'.
Provides SSO login, ACS callback, SLO, and SP metadata endpoints.
"""
from __future__ import annotations

from src.config.public_urls import dashboard_origin, error_doc_url

import hashlib
import json
import logging
import os
import re
import secrets
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from src.auth.dashboard_session import clear_session_cookie, set_session_cookie
from src.auth.provisioning import (
    ProvisionedLogin,
    provision_authenticated_login,
)
from src.auth.redis_util import require_redis_url
from src.config.production import is_production
from src.services.org_saml_service import (
    SamlGroupMappingAmbiguousError,
    normalize_saml_attributes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/saml")
_SAML_REQUEST_TTL_SECONDS = 10 * 60
_RELAY_STATE_RE = re.compile(r"^[A-Za-z0-9_-]{40,128}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
_DIGEST_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"

# Lazy import to avoid hard failure when python3-saml is not installed
_OneLogin_Saml2_Auth = None


@lru_cache(maxsize=1)
def _saml_redis() -> aioredis.Redis:
    return aioredis.from_url(require_redis_url(), decode_responses=True)


def _saml_request_key(relay_state: str) -> str:
    digest = hashlib.sha256(relay_state.encode()).hexdigest()
    return f"saml:request:{digest}"


def _state_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status,
        detail={
            "code": code,
            "message": message,
            "doc_url": error_doc_url(code),
        },
    )


async def _store_saml_request(relay_state: str, request_id: str) -> None:
    """Persist one short-lived SP request correlation without exposing its ID."""
    if not request_id:
        raise _state_error(
            503,
            "saml_state_unavailable",
            "Enterprise sign-in is temporarily unavailable.",
        )
    try:
        stored = await _saml_redis().set(
            _saml_request_key(relay_state),
            request_id,
            ex=_SAML_REQUEST_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        raise _state_error(
            503,
            "saml_state_unavailable",
            "Enterprise sign-in is temporarily unavailable.",
        ) from exc
    if not stored:
        raise _state_error(
            503,
            "saml_state_unavailable",
            "Enterprise sign-in is temporarily unavailable.",
        )


async def _consume_saml_request(relay_state: object) -> str | None:
    """Atomically consume the request ID bound to an IdP-echoed RelayState."""
    if not isinstance(relay_state, str) or not _RELAY_STATE_RE.fullmatch(relay_state):
        return None
    try:
        request_id = await _saml_redis().getdel(_saml_request_key(relay_state))
    except Exception as exc:
        raise _state_error(
            503,
            "saml_state_unavailable",
            "Enterprise sign-in is temporarily unavailable.",
        ) from exc
    return str(request_id) if request_id else None


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


def _expand_env(value):
    """Recursively apply os.path.expandvars to every string in a JSON tree.

    Lets the documented ${SAML_SP_ENTITY_ID} / ${SAML_IDP_X509_CERT} style
    placeholders in settings.json resolve from the environment at load time.
    An undefined ${VAR} is left verbatim by expandvars (python3-saml then
    surfaces the misconfiguration), rather than being silently blanked.
    """
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _load_saml_settings() -> dict:
    """Load SAML settings from config directory.

    Reads settings.json and advanced_settings.json from the directory
    specified by SAML_CONFIG_DIR env var (default: 'saml/'). String values
    are passed through os.path.expandvars so ${ENV_VAR} templates resolve.
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

    return _expand_env(settings)


def _https_origin(value: object, field: str) -> tuple[str, str, int]:
    if not isinstance(value, str) or not value or "${" in value:
        raise RuntimeError(f"{field} must be a resolved HTTPS URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port or 443
    except ValueError as exc:
        raise RuntimeError(f"{field} must be a valid HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise RuntimeError(f"{field} must be a credential-free HTTPS URL")
    return parsed.scheme, parsed.hostname.lower(), port


def assert_production_saml_settings() -> None:
    """Fail startup on a weak or incomplete released SAML security profile."""
    if not is_production() or os.getenv("AUTH_MODE", "").strip().lower() not in {
        "saml",
        "hybrid",
    }:
        return

    settings = _load_saml_settings()
    if settings.get("strict") is not True or settings.get("debug") is True:
        raise RuntimeError("production SAML requires strict mode with debug disabled")

    security = settings.get("security") or {}
    if (
        security.get("wantAssertionsSigned") is not True
        or security.get("wantMessagesSigned") is not True
        or security.get("wantNameId", True) is not True
        or security.get("allowSingleLabelDomains", False) is not False
        or security.get("allowRepeatAttributeName", False) is not False
        or security.get("rejectDeprecatedAlgorithm") is not True
        or security.get("signatureAlgorithm") != _RSA_SHA256
        or security.get("digestAlgorithm") != _DIGEST_SHA256
    ):
        raise RuntimeError(
            "production SAML requires signed messages and assertions, strict "
            "attribute/domain handling, deprecated-algorithm rejection, and "
            "SHA-256 algorithms"
        )

    sp = settings.get("sp") or {}
    sp_origins = {
        _https_origin(sp.get("entityId"), "SAML SP entityId"),
        _https_origin(
            (sp.get("assertionConsumerService") or {}).get("url"),
            "SAML SP ACS URL",
        ),
        _https_origin(
            (sp.get("singleLogoutService") or {}).get("url"),
            "SAML SP SLO URL",
        ),
    }
    if len(sp_origins) != 1:
        raise RuntimeError("production SAML SP URLs must share one HTTPS origin")

    idp = settings.get("idp") or {}
    entity_id = idp.get("entityId")
    if not isinstance(entity_id, str) or not entity_id.strip() or "${" in entity_id:
        raise RuntimeError("production SAML requires a resolved IdP entityId")
    _https_origin(
        (idp.get("singleSignOnService") or {}).get("url"),
        "SAML IdP SSO URL",
    )
    signing_certs: list[object] = [idp.get("x509cert")]
    signing_certs.extend((idp.get("x509certMulti") or {}).get("signing") or [])
    if not any(
        isinstance(cert, str)
        and "${" not in cert
        and len(re.sub(r"\s", "", cert)) >= 256
        for cert in signing_certs
    ):
        raise RuntimeError("production SAML requires a real IdP signing certificate")

    # Run the toolkit's own schema/URL/certificate-presence validation now, not
    # on the first customer's login request.
    from onelogin.saml2.settings import OneLogin_Saml2_Settings

    OneLogin_Saml2_Settings(settings=settings)


def _build_auth(request: Request, request_data: dict):
    """Construct a OneLogin_Saml2_Auth instance."""
    AuthClass = _get_saml2_auth_class()
    settings = _load_saml_settings()
    return AuthClass(request_data, old_settings=settings)


async def _saml_provision_login(
    email: str, attributes: dict[str, list[str]] | None = None
) -> ProvisionedLogin:
    """Provision, group-map, key, and audit a SAML login atomically."""
    email = email.strip()
    if len(email) > 320 or not _EMAIL_RE.fullmatch(email):
        raise _state_error(
            400,
            "saml_email_invalid",
            "The identity provider did not supply a valid email NameID.",
        )

    login = await provision_authenticated_login(
        email=email,
        provider="saml",
        key_name="SAML Default",
        default_role="viewer",
        group_attributes=attributes,
        group_detail_key="saml_group_assignment",
    )
    logger.info("SAML user provisioned: user_id=%d", login.user_id)
    return login


def _extract_saml_attributes(auth) -> dict[str, list[str]]:
    getter = getattr(auth, "get_attributes", None)
    if getter is None:
        return {}
    try:
        return normalize_saml_attributes(getter())
    except Exception:
        logger.warning("failed to read SAML assertion attributes", exc_info=True)
        return {}


@router.get("/login")
async def saml_login(request: Request):
    """Initiate SAML SSO login -- redirect user to IdP."""
    request_data = _build_request_data(request)
    auth = _build_auth(request, request_data)
    if is_production():
        relay_state = secrets.token_urlsafe(32)
        sso_url = auth.login(return_to=relay_state)
        await _store_saml_request(relay_state, str(auth.get_last_request_id() or ""))
    else:
        sso_url = auth.login()
    return RedirectResponse(url=sso_url, status_code=302)


@router.post("/acs")
async def saml_acs(request: Request):
    """Assertion Consumer Service -- process IdP response after login."""
    request_data = await _build_request_data_with_post(request)
    auth = _build_auth(request, request_data)
    if is_production():
        request_id = await _consume_saml_request(
            request_data.get("post_data", {}).get("RelayState")
        )
        if request_id is None:
            raise _state_error(
                400,
                "saml_state_invalid",
                "Enterprise sign-in request is missing, expired, or already used.",
            )
        auth.process_response(request_id=request_id)
    else:
        auth.process_response()

    errors = auth.get_errors()
    if errors:
        logger.error("SAML ACS validation failed: errors=%s", errors)
        raise HTTPException(
            400,
            detail={
                "code": "saml_auth_failed",
                "message": f"SAML authentication failed: {', '.join(errors)}",
                "doc_url": error_doc_url("saml_auth_failed"),
            },
        )

    if not auth.is_authenticated():
        raise HTTPException(
            401,
            detail={
                "code": "saml_not_authenticated",
                "message": "SAML assertion was not authenticated.",
                "doc_url": error_doc_url("saml_not_authenticated"),
            },
        )

    email = auth.get_nameid()
    if not email:
        raise HTTPException(
            400,
            detail={
                "code": "saml_no_email",
                "message": "SAML response did not contain a NameID (email).",
                "doc_url": error_doc_url("saml_no_email"),
            },
        )

    saml_attributes = _extract_saml_attributes(auth)
    try:
        login = await _saml_provision_login(email, saml_attributes or None)
    except SamlGroupMappingAmbiguousError as exc:
        logger.warning(
            "SAML group mapping matched multiple orgs org_count=%d", len(exc.org_ids)
        )
        raise HTTPException(
            403,
            detail={
                "code": "saml_group_mapping_ambiguous",
                "message": (
                    "SAML assertion matched group mappings in multiple organizations. "
                    "Ask an administrator to correct the mapping."
                ),
                "doc_url": error_doc_url("saml_group_mapping_ambiguous"),
            },
        ) from exc

    dashboard_url = dashboard_origin()
    resp = RedirectResponse(url=f"{dashboard_url}/dashboard", status_code=303)
    set_session_cookie(
        resp,
        login.user_id,
        session_version=login.session_version,
    )
    return resp


@router.get("/logout")
async def saml_logout(request: Request):
    """Initiate SAML SLO -- redirect user to IdP for logout."""
    request_data = _build_request_data(request)
    auth = _build_auth(request, request_data)
    if is_production():
        relay_state = secrets.token_urlsafe(32)
        slo_url = auth.logout(return_to=relay_state)
        await _store_saml_request(relay_state, str(auth.get_last_request_id() or ""))
    else:
        slo_url = auth.logout()
    return RedirectResponse(url=slo_url, status_code=302)


@router.api_route("/sls", methods=["GET", "POST"])
async def saml_sls(request: Request):
    """Single Logout Service for Redirect or POST-bound IdP messages."""
    request_data = await _build_request_data_with_post(request)
    auth = _build_auth(request, request_data)
    message_data = (
        request_data.get("post_data", {})
        if request.method.upper() == "POST"
        else request_data.get("get_data", {})
    )
    if is_production() and "SAMLResponse" in message_data:
        request_id = await _consume_saml_request(message_data.get("RelayState"))
        if request_id is None:
            raise _state_error(
                400,
                "saml_logout_state_invalid",
                "Enterprise logout request is missing, expired, or already used.",
            )
        redirect_url = auth.process_slo(request_id=request_id)
    else:
        # IdP-initiated, signed LogoutRequest. The production security profile
        # requires signed SAML messages, while SP-initiated responses are also
        # correlated above to the one-time request ID.
        redirect_url = auth.process_slo()

    errors = auth.get_errors()
    if errors:
        logger.error("SAML SLS errors: %s", errors)
        raise _state_error(
            400,
            "saml_logout_failed",
            "SAML logout response validation failed.",
        )

    login_url = f"{dashboard_origin()}/login"
    resp = RedirectResponse(url=redirect_url or login_url, status_code=302)
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
