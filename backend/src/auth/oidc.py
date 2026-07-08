"""OpenID Connect Relying Party (Authorization Code + PKCE).

Mounted under /auth/oidc when AUTH_MODE is 'oidc' or 'hybrid'. Provides an
enterprise IdP (Okta / Entra / Ping) an OIDC SSO path that lands users in the
SAME session + org + group-assignment model that SAML already uses:

  * GET  /auth/oidc/login    → generate state + nonce + PKCE (S256), stash them
                               in the signed session, 302 to the IdP authorize
                               endpoint (read from OIDC discovery).
  * GET  /auth/oidc/callback → verify state (single-use, expiring), exchange the
                               code at the token endpoint (with the PKCE
                               verifier), verify the id_token signature against
                               the IdP JWKS (RS256) and its iss/aud/exp/iat/nonce,
                               fetch userinfo when claims are thin, then provision
                               the user and apply group→role assignment.

Identity reuse (non-negotiable: one identity model): provisioning mirrors
``src.auth.saml._saml_provision_user`` (``upsert_user`` with
``auth_provider='oidc'`` + default-key minting) and group→role assignment
reuses ``org_saml_service.apply_saml_group_assignment`` — the OIDC ``groups``
claim is fed in as the assertion-attribute map, so the per-org
``SamlGroupMapping`` rows govern OIDC exactly as they govern SAML. No second
identity model is forked.

Zero-egress testing: discovery, JWKS, token, and userinfo are plain httpx calls
to the configured issuer. A test stands up a LOCAL mock IdP (in-process RSA
keypair + fixture discovery/JWKS + minted id_tokens) and points OIDC_ISSUER at
it, intercepting the httpx calls — so the whole flow is proven with no network
and NO bypass in this production code.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from dataclasses import dataclass

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from src.auth.dashboard_session import set_session_cookie
from src.auth.disposable import normalize_email
from src.auth.hashing import hmac_index, mint_token
from src.auth.models import (
    create_api_key,
    get_user_session_version,
    upsert_user,
    user_has_active_api_key,
)
from src.db.engine import get_session_factory
from src.services.org_saml_service import (
    SamlGroupAssignment,
    SamlGroupMappingAmbiguousError,
    apply_saml_group_assignment,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oidc")

# Single-use state entries expire quickly; a stale/replayed callback is rejected.
_STATE_TTL_SECONDS = 600
_SESSION_KEY = "oidc_flows"
_JWT = JsonWebToken(["RS256"])
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


def _api_origin() -> str:
    """Derive the API origin from DASHBOARD_ORIGIN (mirrors oauth._api_origin)."""
    dash = os.getenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    return dash.replace("cadverify.com", "api.cadverify.com")


def _load_oidc_config() -> OidcConfig:
    """Load env-driven OIDC config (parallel to the SAML settings surface).

    Required: OIDC_ISSUER, OIDC_CLIENT_ID. A misconfigured RP fails closed with
    a clean 500 rather than silently attempting an anonymous flow.
    """
    issuer = (os.getenv("OIDC_ISSUER") or "").strip().rstrip("/")
    client_id = (os.getenv("OIDC_CLIENT_ID") or "").strip()
    if not issuer or not client_id:
        raise HTTPException(
            500,
            detail={
                "code": "oidc_not_configured",
                "message": "OIDC_ISSUER and OIDC_CLIENT_ID must be configured.",
                "doc_url": "https://docs.cadverify.com/errors#oidc_not_configured",
            },
        )
    client_secret = (os.getenv("OIDC_CLIENT_SECRET") or "").strip() or None
    discovery_url = (os.getenv("OIDC_DISCOVERY_URL") or "").strip() or (
        f"{issuer}/.well-known/openid-configuration"
    )
    redirect_uri = (os.getenv("OIDC_REDIRECT_URI") or "").strip() or (
        f"{_api_origin()}/auth/oidc/callback"
    )
    scopes = (os.getenv("OIDC_SCOPES") or "openid email profile groups").strip()
    groups_claim = (os.getenv("OIDC_GROUPS_CLAIM") or "groups").strip()
    return OidcConfig(
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        discovery_url=discovery_url,
        redirect_uri=redirect_uri,
        scopes=scopes,
        groups_claim=groups_claim,
    )


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
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - map any transport/parse error to 502
        logger.error("OIDC %s fetch failed url=%s err=%s", what, url, exc)
        raise HTTPException(
            502,
            detail={
                "code": "oidc_discovery_failed",
                "message": f"Failed to fetch OIDC {what}.",
                "doc_url": "https://docs.cadverify.com/errors#oidc_discovery_failed",
            },
        ) from exc


async def _discovery(client: httpx.AsyncClient, cfg: OidcConfig) -> dict:
    doc = await _fetch_json(client, cfg.discovery_url, what="discovery document")
    # RFC 8414: the discovery issuer MUST equal the configured issuer.
    doc_issuer = str(doc.get("issuer") or "").rstrip("/")
    if doc_issuer and doc_issuer != cfg.issuer:
        raise HTTPException(
            502,
            detail={
                "code": "oidc_issuer_mismatch",
                "message": "OIDC discovery issuer does not match configuration.",
                "doc_url": "https://docs.cadverify.com/errors#oidc_issuer_mismatch",
            },
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
            "doc_url": f"https://docs.cadverify.com/errors#{code}",
        },
    )


@router.get("/login")
async def oidc_login(request: Request):
    """Begin OIDC Authorization Code + PKCE: 302 to the IdP authorize endpoint."""
    cfg = _load_oidc_config()
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        discovery = await _discovery(client, cfg)
    authorize_endpoint = discovery.get("authorization_endpoint")
    if not authorize_endpoint:
        raise _bad_callback(
            "oidc_discovery_failed", "OIDC discovery has no authorization_endpoint.", 502
        )

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
        token_endpoint = discovery.get("token_endpoint")
        jwks_uri = discovery.get("jwks_uri")
        userinfo_endpoint = discovery.get("userinfo_endpoint")
        if not token_endpoint or not jwks_uri:
            raise _bad_callback(
                "oidc_discovery_failed", "OIDC discovery missing token/jwks endpoint.", 502
            )

        token_resp = await _exchange_code(client, cfg, token_endpoint, code, verifier)
        id_token = token_resp.get("id_token")
        access_token = token_resp.get("access_token")
        if not id_token:
            raise _bad_callback("oidc_no_id_token", "Token response had no id_token.")

        jwks = await _fetch_json(client, jwks_uri, what="JWKS")
        claims = _verify_id_token(id_token, cfg, jwks, nonce)

        email = _claim_email(claims)
        groups = _claim_groups(claims, cfg.groups_claim)

        # userinfo fallback when the id_token claims are thin (RFC: the id_token
        # may omit email/groups; the userinfo endpoint carries them).
        if (not email or not groups) and access_token and userinfo_endpoint:
            userinfo = await _fetch_userinfo(client, userinfo_endpoint, access_token)
            email = email or _claim_email(userinfo)
            if not groups:
                groups = _claim_groups(userinfo, cfg.groups_claim)

    if not email:
        raise _bad_callback("oidc_no_email", "No email claim in id_token or userinfo.")

    user_id = await _oidc_provision_user(email)
    group_assignment = SamlGroupAssignment(matched=False)
    if groups:
        group_assignment = await _apply_oidc_group_assignment_for_login(
            user_id, {cfg.groups_claim: groups}
        )

    import asyncio

    from src.services.audit_service import fire_and_forget_audit

    asyncio.create_task(
        fire_and_forget_audit(
            user_id=user_id,
            user_email=email,
            action="auth.login",
            resource_type="session",
            detail={
                "auth_provider": "oidc",
                "oidc_group_assignment": group_assignment.to_audit_detail(),
            },
        )
    )

    dashboard_url = os.getenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    resp = RedirectResponse(url=f"{dashboard_url}/dashboard", status_code=303)
    set_session_cookie(
        resp, user_id, session_version=await get_user_session_version(user_id)
    )
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
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("OIDC token exchange failed err=%s", exc)
        raise _bad_callback("oidc_token_exchange_failed", "Token exchange failed.")


def _verify_id_token(id_token: str, cfg: OidcConfig, jwks: dict, nonce: str) -> dict:
    """Verify the id_token signature (RS256, IdP JWKS) and its standard claims.

    Validates the RSA signature against the fetched JWKS, then iss / aud / exp /
    iat via authlib's claim options + ``validate()``, and finally the nonce
    against the value minted at /login. Any failure is a 400 (never a 500).
    """
    try:
        key_set = JsonWebKey.import_key_set(jwks)
    except Exception as exc:  # noqa: BLE001
        raise _bad_callback("oidc_jwks_invalid", "IdP JWKS could not be parsed.", 502)

    claims_options = {
        "iss": {"essential": True, "value": cfg.issuer},
        "aud": {"essential": True, "value": cfg.client_id},
        "exp": {"essential": True},
        "iat": {"essential": True},
    }
    try:
        claims = _JWT.decode(id_token, key_set, claims_options=claims_options)
        claims.validate()  # exp/iat/nbf + the essential/value options above
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
        return resp.json()
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


def _claim_groups(claims: dict, groups_claim: str) -> list[str]:
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


async def _oidc_provision_user(email: str) -> int:
    """Provision/update an OIDC-authenticated user.

    Mirrors ``src.auth.saml._saml_provision_user`` exactly: normalise the email
    the SAME way as every other auth path, ``upsert_user`` with
    ``auth_provider='oidc'``, and mint a default API key only when the account
    has none active (a returning SSO user keeps their keys).
    """
    email_lower = normalize_email(email)
    user_id = await upsert_user(
        email=email,
        google_sub=None,
        email_lower=email_lower,
        disposable_flag=False,
        auth_provider="oidc",
    )

    if not await user_has_active_api_key(user_id):
        full_token, prefix, secret_hash = mint_token()
        await create_api_key(
            user_id, "OIDC Default", prefix, hmac_index(full_token), secret_hash
        )

    logger.info("OIDC user provisioned: email=%s user_id=%d", email_lower, user_id)

    import asyncio

    from src.services.audit_service import fire_and_forget_audit

    asyncio.create_task(
        fire_and_forget_audit(
            user_id=user_id,
            user_email=email,
            action="user.provisioned",
            resource_type="user",
            resource_id=str(user_id),
            detail={"auth_provider": "oidc", "role": "viewer"},
        )
    )
    return user_id


async def _apply_oidc_group_assignment_for_login(
    user_id: int, attributes: dict[str, list[str]]
) -> SamlGroupAssignment:
    """Reuse the SAML group→org-role assignment for OIDC group claims.

    The OIDC ``groups`` claim is handed to the SAME
    ``apply_saml_group_assignment`` the SAML ACS uses, so the per-org
    ``SamlGroupMapping`` rows drive OIDC identically (no forked mapping model).
    """
    async with get_session_factory()() as session:
        try:
            assignment = await apply_saml_group_assignment(session, user_id, attributes)
            await session.commit()
            return assignment
        except SamlGroupMappingAmbiguousError as exc:
            await session.rollback()
            logger.warning(
                "OIDC group mapping matched multiple orgs for user_id=%s org_count=%d",
                user_id,
                len(exc.org_ids),
            )
            raise HTTPException(
                403,
                detail={
                    "code": "oidc_group_mapping_ambiguous",
                    "message": (
                        "OIDC groups matched mappings in multiple organizations. "
                        "Ask an administrator to correct the mapping."
                    ),
                    "doc_url": "https://docs.cadverify.com/errors#oidc_group_mapping_ambiguous",
                },
            ) from exc
