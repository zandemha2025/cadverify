"""OpenID Connect Relying Party (Authorization Code + PKCE).

Mounted under /auth/oidc when AUTH_MODE is 'oidc', or when a hybrid deployment
has intentionally supplied OIDC coordinates. Provides an enterprise IdP (Okta /
Entra / Ping) an OIDC SSO path that lands users in the SAME session + org +
group-assignment model that SAML already uses:

  * GET  /auth/oidc/login    → generate state + nonce + PKCE (S256), stash them
                               in the signed session, 302 to the IdP authorize
                               endpoint (read from OIDC discovery).
  * GET  /auth/oidc/callback → verify state (single-use, expiring), exchange the
                               code at the token endpoint (with the PKCE
                               verifier), verify the id_token signature against
                               the IdP JWKS (RS256) and its iss/aud/exp/iat/nonce,
                               fetch userinfo when claims are thin, then provision
                               the user and apply group→role assignment.

Identity binding is immutable: ``(issuer, sub)`` maps through
``auth_identities`` and verified email can bootstrap only a brand-new account;
it cannot silently attach a new subject to an existing email. User/org/key
state, group→role assignment, and audit evidence commit in one transaction
before the session is signed. The per-org ``SamlGroupMapping`` rows still govern
OIDC groups exactly as they govern SAML.

Zero-egress testing: discovery, JWKS, token, and userinfo are plain httpx calls
to the configured issuer. A test stands up a LOCAL mock IdP (in-process RSA
keypair + fixture discovery/JWKS + minted id_tokens) and points OIDC_ISSUER at
it, intercepting the httpx calls — so the whole flow is proven with no network
and NO bypass in this production code.
"""
from __future__ import annotations

from src.config.public_urls import api_origin, dashboard_origin, error_doc_url

import asyncio
import base64
import hashlib
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from joserfc import jwk, jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySetSerialization
from joserfc.jwt import JWTClaimsRegistry

from src.auth.dashboard_session import set_session_cookie
from src.auth.provisioning import (
    FederatedIdentity,
    ProvisionedLogin,
    provision_authenticated_login,
)
from src.config.production import is_production
from src.services.org_saml_service import SamlGroupMappingAmbiguousError
from src.services.url_guard import UnsafeURLError, validate_public_host

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oidc")

# Single-use state entries expire quickly; a stale/replayed callback is rejected.
_STATE_TTL_SECONDS = 600
_SESSION_KEY = "oidc_flows"
_HTTP_TIMEOUT = httpx.Timeout(10.0)


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str | None
    discovery_url: str
    redirect_uri: str
    scopes: str
    groups_claim: str
    email_verified_claim: str
    allowed_endpoint_origins: tuple[str, ...]


def _load_oidc_config() -> OidcConfig:
    """Load env-driven OIDC config (parallel to the SAML settings surface).

    Required: OIDC_ISSUER, OIDC_CLIENT_ID. A misconfigured RP fails closed with
    a clean 500 rather than silently attempting an anonymous flow.
    """
    issuer = (os.getenv("OIDC_ISSUER") or "").strip()
    client_id = (os.getenv("OIDC_CLIENT_ID") or "").strip()
    if not issuer or not client_id:
        raise HTTPException(
            500,
            detail={
                "code": "oidc_not_configured",
                "message": "OIDC_ISSUER and OIDC_CLIENT_ID must be configured.",
                "doc_url": error_doc_url("oidc_not_configured"),
            },
        )
    client_secret = (os.getenv("OIDC_CLIENT_SECRET") or "").strip() or None
    discovery_url = (os.getenv("OIDC_DISCOVERY_URL") or "").strip() or (
        f"{issuer}/.well-known/openid-configuration"
    )
    redirect_uri = (os.getenv("OIDC_REDIRECT_URI") or "").strip() or (
        f"{api_origin()}/auth/oidc/callback"
    )
    raw_groups_claim = os.getenv("OIDC_GROUPS_CLAIM")
    # Unset keeps the interoperable default. Explicitly blank disables optional
    # group-to-org mapping for IdPs that authenticate users without group claims.
    groups_claim = "groups" if raw_groups_claim is None else raw_groups_claim.strip()
    email_verified_claim = (
        os.getenv("OIDC_EMAIL_VERIFIED_CLAIM") or "email_verified"
    ).strip()
    default_scopes = "openid email profile" + (" groups" if groups_claim else "")
    scopes = (os.getenv("OIDC_SCOPES") or default_scopes).strip()
    allowed_endpoint_origins = tuple(
        value
        for value in re.split(
            r"[\s,]+", (os.getenv("OIDC_ALLOWED_ENDPOINT_ORIGINS") or "").strip()
        )
        if value
    )
    return OidcConfig(
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        discovery_url=discovery_url,
        redirect_uri=redirect_uri,
        scopes=scopes,
        groups_claim=groups_claim,
        email_verified_claim=email_verified_claim,
        allowed_endpoint_origins=allowed_endpoint_origins,
    )


def _require_valid_url(value: str, field: str, *, require_https: bool) -> None:
    """Reject malformed OIDC URLs; released deployments additionally require HTTPS."""
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{field} must be a valid HTTP(S) URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise RuntimeError(f"{field} must be a credential-free HTTP(S) URL")
    if require_https and parsed.scheme != "https":
        raise RuntimeError(f"{field} must use HTTPS in production")


def _url_origin(value: str) -> str:
    """Return a canonical scheme/host/port origin for an already-valid URL."""
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme.lower()}://{host}{port_suffix}"


def _approved_provider_origins(
    cfg: OidcConfig, *, require_https: bool
) -> frozenset[str]:
    """Return the issuer origin plus explicitly reviewed extra IdP origins."""
    approved = {_url_origin(cfg.issuer)}
    for value in cfg.allowed_endpoint_origins:
        field = "OIDC_ALLOWED_ENDPOINT_ORIGINS"
        _require_valid_url(value, field, require_https=require_https)
        parsed = urlsplit(value)
        if parsed.path not in {"", "/"} or parsed.query:
            raise RuntimeError(f"{field} entries must be bare origins")
        approved.add(_url_origin(value))
    return frozenset(approved)


def _validate_oidc_config(cfg: OidcConfig, *, require_https: bool) -> None:
    """Validate local coordinates; only released deployments mandate HTTPS."""
    _require_valid_url(cfg.issuer, "OIDC_ISSUER", require_https=require_https)
    _require_valid_url(
        cfg.discovery_url,
        "OIDC_DISCOVERY_URL",
        require_https=require_https,
    )
    _require_valid_url(
        cfg.redirect_uri,
        "OIDC_REDIRECT_URI",
        require_https=require_https,
    )
    if urlsplit(cfg.issuer).query:
        raise RuntimeError("OIDC_ISSUER must not contain a query string")
    approved = _approved_provider_origins(cfg, require_https=require_https)
    if _url_origin(cfg.discovery_url) not in approved:
        raise RuntimeError(
            "OIDC_DISCOVERY_URL origin must match OIDC_ISSUER or be listed in "
            "OIDC_ALLOWED_ENDPOINT_ORIGINS"
        )
    if "openid" not in cfg.scopes.split():
        raise RuntimeError("OIDC_SCOPES must include 'openid'")


def oidc_provider_enabled(auth_mode: str | None = None) -> bool:
    """Return whether this deployment intentionally exposes the OIDC RP.

    ``oidc`` is explicit and therefore enabled even before validation. ``hybrid``
    predates OIDC and remains Google+SAML-compatible unless at least one OIDC
    coordinate is supplied; a partial opt-in is enabled so production validation
    can reject it instead of silently ignoring an operator typo.
    """
    mode = (auth_mode if auth_mode is not None else os.getenv("AUTH_MODE", ""))
    mode = mode.strip().lower()
    if mode == "oidc":
        return True
    if mode != "hybrid":
        return False
    return any(
        (os.getenv(name) or "").strip()
        for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID")
    )


@router.get("/status", include_in_schema=False)
async def oidc_status() -> dict:
    """Local-only capability probe; validates config without contacting the IdP."""
    try:
        cfg = _load_oidc_config()
        _validate_oidc_config(cfg, require_https=is_production())
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(
            500,
            detail={
                "code": "oidc_invalid_config",
                "message": str(exc),
                "doc_url": error_doc_url("oidc_invalid_config"),
            },
        ) from exc
    return {"enabled": True}


def assert_production_oidc_settings() -> None:
    """Fail startup before a released OIDC/hybrid login can be misconfigured."""
    if not is_production() or not oidc_provider_enabled():
        return

    try:
        cfg = _load_oidc_config()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        message = detail.get("message") or "OIDC configuration is incomplete."
        raise RuntimeError(f"production OIDC configuration invalid: {message}") from exc

    try:
        _validate_oidc_config(cfg, require_https=True)
    except RuntimeError as exc:
        raise RuntimeError(f"production OIDC configuration invalid: {exc}") from exc


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256 (RFC 7636)."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


async def _fetch_json(client: httpx.AsyncClient, url: str, *, what: str) -> dict:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(f"OIDC {what} must be a JSON object")
        return payload
    except Exception as exc:  # noqa: BLE001 - map any transport/parse error to 502
        logger.error("OIDC %s fetch failed url=%s err=%s", what, url, exc)
        raise HTTPException(
            502,
            detail={
                "code": "oidc_discovery_failed",
                "message": f"Failed to fetch OIDC {what}.",
                "doc_url": error_doc_url("oidc_discovery_failed"),
            },
        ) from exc


async def _validate_provider_endpoint(
    cfg: OidcConfig,
    value: object,
    *,
    field: str,
) -> str:
    """Validate one discovered endpoint before any redirect or server egress."""
    if not isinstance(value, str) or not value.strip():
        raise _bad_callback(
            "oidc_discovery_failed",
            f"OIDC discovery has no {field}.",
            502,
        )
    endpoint = value.strip()
    production = is_production()
    try:
        _require_valid_url(endpoint, field, require_https=production)
        if _url_origin(endpoint) not in _approved_provider_origins(
            cfg, require_https=production
        ):
            raise RuntimeError(
                "origin is not the configured issuer or an explicitly allowed origin"
            )
        if production:
            host = urlsplit(endpoint).hostname or ""
            await asyncio.to_thread(validate_public_host, host)
    except (RuntimeError, UnsafeURLError) as exc:
        logger.warning("Rejected unsafe OIDC %s: %s", field, exc)
        raise _bad_callback(
            "oidc_discovery_unsafe",
            f"OIDC discovery returned an unsafe {field}.",
            502,
        ) from exc
    return endpoint


async def _discovery(client: httpx.AsyncClient, cfg: OidcConfig) -> dict:
    try:
        _validate_oidc_config(cfg, require_https=is_production())
    except RuntimeError as exc:
        logger.error("OIDC runtime configuration rejected: %s", exc)
        raise _bad_callback(
            "oidc_invalid_config",
            "OIDC configuration is invalid.",
            500,
        ) from exc
    await _validate_provider_endpoint(
        cfg,
        cfg.discovery_url,
        field="discovery endpoint",
    )
    doc = await _fetch_json(client, cfg.discovery_url, what="discovery document")
    # RFC 8414: the discovery issuer MUST equal the configured issuer.
    doc_issuer = doc.get("issuer")
    if not isinstance(doc_issuer, str) or not doc_issuer or doc_issuer != cfg.issuer:
        raise HTTPException(
            502,
            detail={
                "code": "oidc_issuer_mismatch",
                "message": "OIDC discovery issuer does not match configuration.",
                "doc_url": error_doc_url("oidc_issuer_mismatch"),
            },
        )
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        doc[field] = await _validate_provider_endpoint(
            cfg,
            doc.get(field),
            field=field,
        )
    userinfo_endpoint = doc.get("userinfo_endpoint")
    if userinfo_endpoint is not None:
        doc["userinfo_endpoint"] = await _validate_provider_endpoint(
            cfg,
            userinfo_endpoint,
            field="userinfo_endpoint",
        )
    return doc


def _stash_flow(request: Request, state: str, nonce: str, verifier: str) -> None:
    flows = request.session.get(_SESSION_KEY)
    if not isinstance(flows, dict):
        flows = {}
    now = int(time.time())
    # Drop expired entries so the session cookie does not grow unbounded.
    flows = {
        s: v
        for s, v in flows.items()
        if isinstance(v, dict) and now - int(v.get("ts", 0)) < _STATE_TTL_SECONDS
    }
    flows[state] = {"nonce": nonce, "verifier": verifier, "ts": now}
    request.session[_SESSION_KEY] = flows


def _pop_flow(request: Request, state: str) -> dict | None:
    flows = request.session.get(_SESSION_KEY)
    if not isinstance(flows, dict):
        return None
    entry = flows.pop(state, None)  # single-use: consumed on pop (replay-safe)
    request.session[_SESSION_KEY] = flows
    if not isinstance(entry, dict):
        return None
    if int(time.time()) - int(entry.get("ts", 0)) >= _STATE_TTL_SECONDS:
        return None
    return entry


def _bad_callback(code: str, message: str, status: int = 400) -> HTTPException:
    return HTTPException(
        status,
        detail={
            "code": code,
            "message": message,
            "doc_url": error_doc_url(code),
        },
    )


@router.get("/login")
async def oidc_login(request: Request):
    """Begin OIDC Authorization Code + PKCE: 302 to the IdP authorize endpoint."""
    cfg = _load_oidc_config()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        discovery = await _discovery(client, cfg)
    authorize_endpoint = discovery["authorization_endpoint"]

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    _stash_flow(request, state, nonce, verifier)

    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "scope": cfg.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    sep = "&" if "?" in authorize_endpoint else "?"
    return RedirectResponse(url=f"{authorize_endpoint}{sep}{params}", status_code=302)


@router.get("/callback")
async def oidc_callback(request: Request):
    """Complete the flow: verify state, exchange code, verify id_token, provision."""
    cfg = _load_oidc_config()
    query = request.query_params

    if query.get("error"):
        raise _bad_callback(
            "oidc_authz_error",
            f"IdP returned an authorization error: {query.get('error')}.",
        )

    state = query.get("state")
    code = query.get("code")
    if not state or not code:
        raise _bad_callback("oidc_bad_request", "Missing 'state' or 'code'.")

    flow = _pop_flow(request, state)
    if flow is None:
        # Unknown/expired/replayed state — fail closed (CSRF + replay guard).
        raise _bad_callback("oidc_bad_state", "Unknown, expired, or replayed state.")
    nonce = flow["nonce"]
    verifier = flow["verifier"]

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        discovery = await _discovery(client, cfg)
        token_endpoint = discovery["token_endpoint"]
        jwks_uri = discovery["jwks_uri"]
        userinfo_endpoint = discovery.get("userinfo_endpoint")

        token_resp = await _exchange_code(client, cfg, token_endpoint, code, verifier)
        id_token = token_resp.get("id_token")
        access_token = token_resp.get("access_token")
        if not id_token:
            raise _bad_callback("oidc_no_id_token", "Token response had no id_token.")

        jwks = await _fetch_json(client, jwks_uri, what="JWKS")
        claims = _verify_id_token(id_token, cfg, jwks, nonce)

        email = _claim_email(claims)
        email_verified = _claim_email_verified(claims, cfg.email_verified_claim)
        groups = _claim_groups(claims, cfg.groups_claim)

        # Userinfo is a fallback only for claims this deployment actually needs.
        # When group mapping is disabled, an empty group list is intentional and
        # must not add an avoidable provider request to every successful login.
        needs_group_fallback = bool(cfg.groups_claim) and not groups
        if (not email or needs_group_fallback) and access_token and userinfo_endpoint:
            userinfo = await _fetch_userinfo(client, userinfo_endpoint, access_token)
            userinfo_sub = str(userinfo.get("sub") or "").strip()
            id_token_sub = str(claims.get("sub") or "").strip()
            if not userinfo_sub or userinfo_sub != id_token_sub:
                raise _bad_callback(
                    "oidc_userinfo_subject_mismatch",
                    "userinfo must carry the verified id_token subject.",
                )
            userinfo_email = _claim_email(userinfo)
            userinfo_verified = _claim_email_verified(
                userinfo, cfg.email_verified_claim
            )
            if not email:
                email = userinfo_email
                email_verified = userinfo_verified
            elif (
                userinfo_email
                and userinfo_email.strip().casefold() == email.strip().casefold()
            ):
                # A userinfo verification flag may corroborate the same address
                # carried as preferred_username in a thin Entra id_token.
                email_verified = email_verified or userinfo_verified
            if needs_group_fallback:
                groups = _claim_groups(userinfo, cfg.groups_claim)

    try:
        login = await _oidc_provision_login(
            email=email,
            email_verified=email_verified,
            issuer=cfg.issuer,
            subject=str(claims.get("sub") or ""),
            groups={cfg.groups_claim: groups} if groups else None,
        )
    except SamlGroupMappingAmbiguousError as exc:
        logger.warning(
            "OIDC group mapping matched multiple orgs org_count=%d", len(exc.org_ids)
        )
        raise HTTPException(
            403,
            detail={
                "code": "oidc_group_mapping_ambiguous",
                "message": (
                    "OIDC groups matched mappings in multiple organizations. "
                    "Ask an administrator to correct the mapping."
                ),
                "doc_url": error_doc_url("oidc_group_mapping_ambiguous"),
            },
        ) from exc

    dashboard_url = dashboard_origin()
    resp = RedirectResponse(url=f"{dashboard_url}/dashboard", status_code=303)
    set_session_cookie(resp, login.user_id, session_version=login.session_version)
    return resp


async def _exchange_code(
    client: httpx.AsyncClient,
    cfg: OidcConfig,
    token_endpoint: str,
    code: str,
    verifier: str,
) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.redirect_uri,
        "client_id": cfg.client_id,
        "code_verifier": verifier,
    }
    # Confidential clients authenticate at the token endpoint; PKCE-only public
    # clients omit the secret (the verifier is the proof).
    if cfg.client_secret:
        data["client_secret"] = cfg.client_secret
    try:
        resp = await client.post(token_endpoint, data=data)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError("OIDC token response must be a JSON object")
        return payload
    except Exception as exc:  # noqa: BLE001
        logger.error("OIDC token exchange failed err=%s", exc)
        raise _bad_callback("oidc_token_exchange_failed", "Token exchange failed.")


def _verify_id_token(id_token: str, cfg: OidcConfig, jwks: dict, nonce: str) -> dict:
    """Verify the id_token signature (RS256, IdP JWKS) and its standard claims.

    Validates the RSA signature against the fetched JWKS, then iss / aud / exp /
    iat via joserfc's claims registry, and finally the nonce
    against the value minted at /login. Any failure is a 400 (never a 500).
    """
    try:
        key_set = jwk.KeySet.import_key_set(cast(KeySetSerialization, jwks))
    except Exception as exc:  # noqa: BLE001
        raise _bad_callback("oidc_jwks_invalid", "IdP JWKS could not be parsed.", 502)

    try:
        token = jwt.decode(id_token, key_set, algorithms=["RS256"])
        claims_registry = JWTClaimsRegistry(
            iss={"essential": True, "value": cfg.issuer},
            sub={"essential": True},
            aud={"essential": True, "value": cfg.client_id},
            exp={"essential": True},
            iat={"essential": True},
            nbf={"essential": False},
        )
        claims_registry.validate(token.claims)  # iss/aud/exp/iat/nbf
        claims = token.claims
    except JoseError as exc:
        logger.warning("OIDC id_token verification failed: %s", exc)
        raise _bad_callback("oidc_invalid_token", f"id_token rejected: {exc}.")
    except (ValueError, KeyError) as exc:
        # e.g. no JWKS key matches the token's kid (rotation / wrong key).
        logger.warning("OIDC id_token key resolution failed: %s", exc)
        raise _bad_callback("oidc_invalid_token", "id_token signing key not found.")

    if not nonce or claims.get("nonce") != nonce:
        raise _bad_callback("oidc_bad_nonce", "id_token nonce mismatch or missing.")
    return dict(claims)


async def _fetch_userinfo(
    client: httpx.AsyncClient, userinfo_endpoint: str, access_token: str
) -> dict:
    try:
        resp = await client.get(
            userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"}
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:  # noqa: BLE001 - userinfo is a best-effort fallback
        logger.warning("OIDC userinfo fetch failed: %s", exc)
        return {}


def _claim_email(claims: dict) -> str | None:
    email = claims.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip()
    # Entra commonly puts the address in 'preferred_username' / 'upn'.
    for alt in ("preferred_username", "upn"):
        value = claims.get(alt)
        if isinstance(value, str) and "@" in value:
            return value.strip()
    return None


def _claim_email_verified(claims: dict, claim_name: str) -> bool:
    """Accept only an explicit true value from the configured verified claim."""
    if not claim_name:
        return False
    value = claims.get(claim_name)
    return value is True or (
        isinstance(value, str) and value.strip().lower() == "true"
    )


def _claim_groups(claims: dict, groups_claim: str) -> list[str]:
    if not groups_claim:
        return []
    raw = claims.get(groups_claim)
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value:
            out.append(value)
    return out


async def _oidc_provision_login(
    *,
    email: str | None,
    email_verified: bool,
    issuer: str,
    subject: str,
    groups: dict[str, list[str]] | None,
) -> ProvisionedLogin:
    """Single transaction for immutable identity binding, key, groups, and audit."""
    return await provision_authenticated_login(
        email=email,
        provider="oidc",
        key_name="OIDC Default",
        default_role="viewer",
        identity=FederatedIdentity(
            provider="oidc",
            issuer=issuer,
            subject=subject,
            email_verified=email_verified,
        ),
        group_attributes=groups,
        group_detail_key="oidc_group_assignment",
        login_detail={"issuer": issuer},
    )
