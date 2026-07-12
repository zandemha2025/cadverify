"""OpenID Connect RP — full flow against a LOCAL mock IdP (zero egress).

The mock IdP is a real, in-process OIDC provider: it owns an RSA keypair, serves
a fixture discovery document + JWKS, and mints RS256-signed id_tokens. Its HTTP
surface is reached through the RP's normal httpx calls, intercepted by respx so
nothing touches the network and there is NO bypass in the production code — the
issuer is simply pointed at the mock via ordinary OIDC_* config.

Covers the happy path (authz redirect → callback → token exchange → verified
id_token → provisioned session) and the negative paths (bad state, bad nonce,
expired token, wrong aud, tampered signature, JWKS rotation), replaying both an
Okta-shaped and an Entra-shaped claim set from fixtures.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from joserfc import jwk, jwt
from starlette.middleware.sessions import SessionMiddleware

from src.auth.provisioning import ProvisionedLogin
from src.services.org_saml_service import SamlGroupAssignment

ISSUER = "https://mock-idp.local"
CLIENT_ID = "client-abc"
CLIENT_SECRET = "shhh"
REDIRECT_URI = "https://api.cadverify.com/auth/oidc/callback"

# Realistic fixture claim sets (trimmed to the fields the RP consumes).
OKTA_CLAIMS = {
    "sub": "00u1okta",
    "email": "engineer@okta-enterprise.com",
    "email_verified": True,
    "name": "Okta Engineer",
    "groups": ["Everyone", "cad-engineers"],
}
# Entra's id_token is thin: no email (address is in preferred_username/upn) and
# groups delivered via the userinfo endpoint, exercising the userinfo fallback.
ENTRA_ID_TOKEN_CLAIMS = {
    "sub": "entra-oid-9",
    "preferred_username": "engineer@entra-enterprise.com",
    "name": "Entra Engineer",
}
ENTRA_USERINFO = {
    "sub": "entra-oid-9",
    "preferred_username": "engineer@entra-enterprise.com",
    "email_verified": True,
    "groups": ["11111111-2222-3333-4444-555555555555", "cad-eng"],
}


def _login_result(
    user_id: int,
    assignment: SamlGroupAssignment | None = None,
) -> ProvisionedLogin:
    return ProvisionedLogin(
        user_id=user_id,
        user_email=f"user-{user_id}@example.com",
        session_version=0,
        created=False,
        group_assignment=assignment or SamlGroupAssignment(matched=False),
    )


class MockIdP:
    """A local OIDC provider: keypair + discovery + JWKS + id_token minting."""

    def __init__(self, issuer: str = ISSUER, client_id: str = CLIENT_ID):
        self.issuer = issuer
        self.client_id = client_id
        self._install_key("kid-1")

    def _install_key(self, kid: str) -> None:
        key = jwk.RSAKey.generate_key(2048, private=True)
        self.kid = kid
        self._priv = key
        self._pub = {
            **key.as_dict(private=False),
            "kid": kid,
            "use": "sig",
            "alg": "RS256",
        }

    def rotate(self, kid: str) -> None:
        """Replace the serving key (simulates an IdP key rotation)."""
        self._install_key(kid)

    def discovery(self) -> dict:
        b = self.issuer
        return {
            "issuer": b,
            "authorization_endpoint": f"{b}/authorize",
            "token_endpoint": f"{b}/token",
            "jwks_uri": f"{b}/jwks",
            "userinfo_endpoint": f"{b}/userinfo",
            "response_types_supported": ["code"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    def jwks(self) -> dict:
        return {"keys": [self._pub]}

    def mint(
        self,
        *,
        nonce: str,
        claims: dict,
        aud: str | list[str] | None = None,
        exp_delta: int = 300,
        iat_delta: int = 0,
        omit_claims: set[str] | None = None,
    ) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "aud": aud or self.client_id,
            "sub": "sub-default",
            "nonce": nonce,
            "iat": now + iat_delta,
            "exp": now + exp_delta,
        }
        payload.update(claims)
        for claim in omit_claims or set():
            payload.pop(claim, None)
        return jwt.encode(
            {"alg": "RS256", "kid": self.kid},
            payload,
            self._priv,
            algorithms=["RS256"],
        )


@pytest.fixture
def oidc_env(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("OIDC_SCOPES", "openid email profile groups")
    monkeypatch.setenv("OIDC_GROUPS_CLAIM", "groups")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://cadverify.com")
    yield


@pytest.fixture
def required_audit(monkeypatch):
    from src.services import audit_service

    audit = AsyncMock()
    monkeypatch.setattr(audit_service, "log_action", audit)
    return audit


@pytest.fixture
def app(required_audit):
    del required_audit
    from src.auth.oidc import router as oidc_router

    application = FastAPI()
    application.add_middleware(SessionMiddleware, secret_key="oidc-test-secret")
    application.include_router(oidc_router, prefix="/auth")
    return application


def _wire_idp(router, idp: MockIdP, *, id_token_holder: dict, userinfo: dict | None = None):
    """Route the RP's httpx calls to the in-process mock IdP (no network)."""
    router.get(f"{idp.issuer}/.well-known/openid-configuration").mock(
        side_effect=lambda req: httpx.Response(200, json=idp.discovery())
    )
    router.get(f"{idp.issuer}/jwks").mock(
        side_effect=lambda req: httpx.Response(200, json=idp.jwks())
    )
    router.post(f"{idp.issuer}/token").mock(
        side_effect=lambda req: httpx.Response(
            200,
            json={
                "access_token": "access-token-xyz",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": id_token_holder["id_token"],
            },
        )
    )
    userinfo_route = router.get(f"{idp.issuer}/userinfo").mock(
        side_effect=lambda req: httpx.Response(200, json=userinfo or {})
    )
    return userinfo_route


def _start_login(client: TestClient) -> tuple[str, str]:
    """Drive /login and return (state, nonce) parsed from the authorize redirect."""
    resp = client.get("/auth/oidc/login", follow_redirects=False)
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize")
    q = parse_qs(urlparse(location).query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == [CLIENT_ID]
    assert q["code_challenge_method"] == ["S256"]
    assert q["redirect_uri"] == [REDIRECT_URI]
    assert q.get("code_challenge")  # PKCE challenge present
    return q["state"][0], q["nonce"][0]


def test_oidc_group_mapping_can_be_explicitly_disabled(oidc_env, monkeypatch):
    import src.auth.oidc as oidc

    monkeypatch.setenv("OIDC_GROUPS_CLAIM", "   ")
    monkeypatch.delenv("OIDC_SCOPES")

    config = oidc._load_oidc_config()

    assert config.groups_claim == ""
    assert config.scopes == "openid email profile"
    assert oidc._claim_groups({"groups": ["cad-engineers"]}, config.groups_claim) == []


def test_hybrid_oidc_is_optional_but_partial_opt_in_fails_closed(monkeypatch):
    import src.auth.oidc as oidc

    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("AUTH_MODE", "hybrid")
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    monkeypatch.delenv("OIDC_CLIENT_ID", raising=False)

    assert oidc.oidc_provider_enabled() is False
    oidc.assert_production_oidc_settings()

    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    assert oidc.oidc_provider_enabled() is True
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_ID"):
        oidc.assert_production_oidc_settings()


def test_oidc_status_is_a_no_egress_capability_probe(app, oidc_env):
    with respx.mock(assert_all_called=False) as router:
        response = TestClient(app).get("/auth/oidc/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": True}
    assert len(router.calls) == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OIDC_ISSUER", "not-a-url"),
        ("OIDC_DISCOVERY_URL", "not-a-url"),
        ("OIDC_REDIRECT_URI", "not-a-url"),
    ],
)
def test_oidc_status_rejects_malformed_local_urls(app, oidc_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    response = TestClient(app).get("/auth/oidc/status")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "oidc_invalid_config"
    assert name in response.json()["detail"]["message"]


def test_oidc_status_allows_http_coordinates_outside_production(app, oidc_env, monkeypatch):
    monkeypatch.setenv("RELEASE", "dev")
    monkeypatch.setenv("OIDC_ISSUER", "http://localhost:9000")
    monkeypatch.setenv(
        "OIDC_DISCOVERY_URL",
        "http://localhost:9000/.well-known/openid-configuration",
    )
    monkeypatch.setenv(
        "OIDC_REDIRECT_URI",
        "http://localhost:3000/auth/oidc/callback",
    )

    response = TestClient(app).get("/auth/oidc/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_oidc_status_requires_https_in_production(app, oidc_env, monkeypatch):
    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("OIDC_ISSUER", "http://localhost:9000")

    response = TestClient(app).get("/auth/oidc/status")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "oidc_invalid_config"
    assert "HTTPS in production" in response.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_discovery_requires_exact_nonempty_issuer(oidc_env, monkeypatch):
    import src.auth.oidc as oidc

    cfg = oidc._load_oidc_config()
    document = MockIdP().discovery()
    document.pop("issuer")
    monkeypatch.setattr(
        oidc, "_fetch_json", AsyncMock(return_value=document)
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(HTTPException) as exc_info:
            await oidc._discovery(client, cfg)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "oidc_issuer_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "endpoint"),
    [
        ("token_endpoint", "https://attacker.example/token"),
        ("jwks_uri", "https://user:password@mock-idp.local/jwks"),
        ("userinfo_endpoint", "file:///etc/passwd"),
    ],
)
async def test_discovery_rejects_unapproved_or_credentialed_endpoints(
    oidc_env, monkeypatch, field, endpoint
):
    import src.auth.oidc as oidc

    cfg = oidc._load_oidc_config()
    document = {**MockIdP().discovery(), field: endpoint}
    monkeypatch.setattr(
        oidc, "_fetch_json", AsyncMock(return_value=document)
    )

    async with httpx.AsyncClient() as client:
        with pytest.raises(HTTPException) as exc_info:
            await oidc._discovery(client, cfg)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "oidc_discovery_unsafe"


@pytest.mark.asyncio
async def test_production_discovery_rejects_private_allowed_origin(
    oidc_env, monkeypatch
):
    import src.auth.oidc as oidc

    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv(
        "OIDC_ALLOWED_ENDPOINT_ORIGINS", "https://127.0.0.1"
    )
    cfg = oidc._load_oidc_config()

    with pytest.raises(HTTPException) as exc_info:
        await oidc._validate_provider_endpoint(
            cfg,
            "https://127.0.0.1/token",
            field="token_endpoint",
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "oidc_discovery_unsafe"


# ══════════════════════════════════════════════════════════════════════════
# Happy path — Okta-shaped id_token with groups in the id_token
# ══════════════════════════════════════════════════════════════════════════


def test_oidc_happy_path_okta_shaped(app, oidc_env, monkeypatch):
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    assignment = SamlGroupAssignment(
        matched=True, org_id="org1", org_role="member", created=True
    )
    provision = AsyncMock(return_value=_login_result(42, assignment))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)

    idp = MockIdP()
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(nonce=nonce, claims=OKTA_CLAIMS)

        resp = client.get(f"/auth/oidc/callback?code=authz-code-1&state={state}")

    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "https://cadverify.com/dashboard"
    assert "dash_session" in resp.headers.get("set-cookie", "")
    provision.assert_awaited_once_with(
        email="engineer@okta-enterprise.com",
        email_verified=True,
        issuer=ISSUER,
        subject="00u1okta",
        groups={"groups": ["Everyone", "cad-engineers"]},
    )


def test_oidc_disabled_group_mapping_skips_userinfo(app, oidc_env, monkeypatch):
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    monkeypatch.setenv("OIDC_GROUPS_CLAIM", "   ")
    monkeypatch.delenv("OIDC_SCOPES")
    provision = AsyncMock(return_value=_login_result(43))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)

    idp = MockIdP()
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        userinfo_route = _wire_idp(router, idp, id_token_holder=holder)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(
            nonce=nonce,
            claims={
                "sub": "no-groups",
                "email": "engineer@example.com",
                "email_verified": True,
            },
        )

        resp = client.get(f"/auth/oidc/callback?code=no-groups&state={state}")

    assert resp.status_code == 303, resp.text
    assert userinfo_route.called is False
    provision.assert_awaited_once_with(
        email="engineer@example.com",
        email_verified=True,
        issuer=ISSUER,
        subject="no-groups",
        groups=None,
    )


# ══════════════════════════════════════════════════════════════════════════
# Happy path — Entra-shaped: thin id_token, email + groups via userinfo fallback
# ══════════════════════════════════════════════════════════════════════════


def test_oidc_happy_path_entra_shaped_userinfo_fallback(app, oidc_env, monkeypatch):
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=_login_result(7))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)

    idp = MockIdP()
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder, userinfo=ENTRA_USERINFO)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(nonce=nonce, claims=ENTRA_ID_TOKEN_CLAIMS)

        resp = client.get(f"/auth/oidc/callback?code=code-e&state={state}")

    assert resp.status_code == 303, resp.text
    # Email derived from preferred_username; groups pulled from userinfo.
    provision.assert_awaited_once_with(
        email="engineer@entra-enterprise.com",
        email_verified=True,
        issuer=ISSUER,
        subject="entra-oid-9",
        groups={"groups": ["11111111-2222-3333-4444-555555555555", "cad-eng"]},
    )


def test_oidc_rejects_userinfo_for_a_different_subject(app, oidc_env, monkeypatch):
    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=_login_result(7))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)
    idp = MockIdP()
    holder: dict = {}
    mismatched = {**ENTRA_USERINFO, "sub": "attacker-subject"}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder, userinfo=mismatched)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(nonce=nonce, claims=ENTRA_ID_TOKEN_CLAIMS)
        resp = client.get(f"/auth/oidc/callback?code=code-e&state={state}")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_userinfo_subject_mismatch"
    provision.assert_not_awaited()


def test_oidc_rejects_userinfo_without_a_subject(app, oidc_env, monkeypatch):
    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=_login_result(7))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)
    idp = MockIdP()
    holder: dict = {}
    missing_subject = {
        key: value for key, value in ENTRA_USERINFO.items() if key != "sub"
    }
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(
            router, idp, id_token_holder=holder, userinfo=missing_subject
        )
        client = TestClient(
            app, follow_redirects=False, raise_server_exceptions=False
        )
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(
            nonce=nonce, claims=ENTRA_ID_TOKEN_CLAIMS
        )
        resp = client.get(f"/auth/oidc/callback?code=code-e&state={state}")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_userinfo_subject_mismatch"
    provision.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════
# Negative paths
# ══════════════════════════════════════════════════════════════════════════


def _run_callback_expecting_failure(
    app, monkeypatch, *, mutate_token=None, wrong_state=False, rotate_before_callback=None,
    mint_kwargs=None, code_state_override=None,
):
    """Shared driver: login, mint an id_token, tamper as configured, expect 4xx."""
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=_login_result(99))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)

    idp = MockIdP()
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        token = idp.mint(nonce=nonce, **(mint_kwargs or {"claims": OKTA_CLAIMS}))
        if mutate_token:
            token = mutate_token(token)
        holder["id_token"] = token
        if rotate_before_callback:
            idp.rotate(rotate_before_callback)  # JWKS no longer has the token's kid
        use_state = "not-the-issued-state" if wrong_state else state
        if code_state_override is not None:
            resp = client.get(f"/auth/oidc/callback{code_state_override}")
        else:
            resp = client.get(f"/auth/oidc/callback?code=c&state={use_state}")
    return resp, provision


def test_oidc_rejects_bad_state(app, oidc_env, monkeypatch):
    resp, provision = _run_callback_expecting_failure(app, monkeypatch, wrong_state=True)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_bad_state"
    assert "dash_session" not in resp.headers.get("set-cookie", "")
    provision.assert_not_awaited()


def test_oidc_rejects_bad_nonce(app, oidc_env, monkeypatch):
    # Mint with a nonce that does NOT match the one stored at /login.
    resp, provision = _run_callback_expecting_failure(
        app, monkeypatch, mint_kwargs={"claims": {**OKTA_CLAIMS, "nonce": "attacker-nonce"}},
    )
    # Note: mint() sets nonce= from the kw; override via claims wins last.
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_bad_nonce"
    provision.assert_not_awaited()


def test_oidc_rejects_expired_token(app, oidc_env, monkeypatch):
    resp, provision = _run_callback_expecting_failure(
        app, monkeypatch, mint_kwargs={"claims": OKTA_CLAIMS, "exp_delta": -30},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


def test_oidc_rejects_wrong_aud(app, oidc_env, monkeypatch):
    resp, provision = _run_callback_expecting_failure(
        app, monkeypatch, mint_kwargs={"claims": OKTA_CLAIMS, "aud": "some-other-client"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


def test_oidc_rejects_wrong_issuer(app, oidc_env, monkeypatch):
    resp, provision = _run_callback_expecting_failure(
        app,
        monkeypatch,
        mint_kwargs={
            "claims": {**OKTA_CLAIMS, "iss": "https://attacker-idp.invalid"}
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "exp", "iat"])
def test_oidc_rejects_missing_required_claim(
    app, oidc_env, monkeypatch, claim
):
    resp, provision = _run_callback_expecting_failure(
        app,
        monkeypatch,
        mint_kwargs={"claims": OKTA_CLAIMS, "omit_claims": {claim}},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


@pytest.mark.parametrize(
    "mint_kwargs",
    [
        {"claims": OKTA_CLAIMS, "iat_delta": 3600},
        {"claims": {**OKTA_CLAIMS, "nbf": int(time.time()) + 3600}},
    ],
)
def test_oidc_rejects_not_yet_valid_token(
    app, oidc_env, monkeypatch, mint_kwargs
):
    resp, provision = _run_callback_expecting_failure(
        app, monkeypatch, mint_kwargs=mint_kwargs
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


def test_oidc_accepts_multi_audience_with_client_id(app, oidc_env, monkeypatch):
    from src.auth import oidc

    provision = AsyncMock(return_value=_login_result(57))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)

    idp = MockIdP()
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(
            nonce=nonce,
            claims=OKTA_CLAIMS,
            aud=["resource-api", CLIENT_ID],
        )
        resp = client.get(f"/auth/oidc/callback?code=c&state={state}")

    assert resp.status_code == 303, resp.text
    assert "dash_session" in resp.headers.get("set-cookie", "")


def test_oidc_transactional_provisioning_failure_blocks_session_issuance(
    app, oidc_env, monkeypatch
):
    from src.auth import oidc

    monkeypatch.setattr(
        oidc,
        "_oidc_provision_login",
        AsyncMock(side_effect=RuntimeError("audit ledger unavailable")),
    )

    idp = MockIdP()
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(nonce=nonce, claims=OKTA_CLAIMS)
        resp = client.get(f"/auth/oidc/callback?code=c&state={state}")

    assert resp.status_code == 500
    assert "dash_session" not in resp.headers.get("set-cookie", "")


def test_oidc_rejects_tampered_signature(app, oidc_env, monkeypatch):
    def _tamper(token: str) -> str:
        header, payload, sig = token.split(".")
        flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
        return ".".join([header, payload, flipped])

    resp, provision = _run_callback_expecting_failure(app, monkeypatch, mutate_token=_tamper)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


def test_oidc_rejects_when_jwks_rotated_away(app, oidc_env, monkeypatch):
    # Token is signed by kid-1, then the IdP rotates so its JWKS only serves
    # kid-2: the RP re-fetches JWKS, finds no matching key, and rejects.
    resp, provision = _run_callback_expecting_failure(
        app, monkeypatch, rotate_before_callback="kid-2",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_invalid_token"
    provision.assert_not_awaited()


def test_oidc_verifies_after_key_rotation(app, oidc_env, monkeypatch):
    """Positive rotation: a token minted with the CURRENT (rotated) key verifies
    because the RP fetches JWKS fresh on each callback."""
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=_login_result(55))
    monkeypatch.setattr(oidc, "_oidc_provision_login", provision)

    idp = MockIdP()
    idp.rotate("kid-rotated")  # IdP is now serving a new signing key
    holder: dict = {}
    with respx.mock(assert_all_called=False) as router:
        _wire_idp(router, idp, id_token_holder=holder)
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        state, nonce = _start_login(client)
        holder["id_token"] = idp.mint(nonce=nonce, claims=OKTA_CLAIMS)
        resp = client.get(f"/auth/oidc/callback?code=c&state={state}")

    assert resp.status_code == 303, resp.text
    provision.assert_awaited_once()


def test_oidc_rejects_idp_authz_error(app, oidc_env, monkeypatch):
    resp, provision = _run_callback_expecting_failure(
        app, monkeypatch, code_state_override="?error=access_denied&state=x",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "oidc_authz_error"
    provision.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════════
# Live-Postgres end-to-end: REAL provisioning + group→role assignment through
# the SAME SamlGroupMapping table SAML uses (no provisioning mocks).
# ══════════════════════════════════════════════════════════════════════════

_PG_URL = os.environ.get("DATABASE_URL", "")
_requires_pg = pytest.mark.skipif(
    not _PG_URL.startswith("postgresql"),
    reason="requires local Postgres (set DATABASE_URL=postgresql://...)",
)


@pytest.fixture
def _loop_hermetic_engine():
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None
    try:
        yield
    finally:
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None


async def _pg(sql: str, *args, fetch: bool = False):
    import asyncpg

    conn = await asyncpg.connect(_PG_URL)
    try:
        if fetch:
            return await conn.fetch(sql, *args)
        await conn.execute(sql, *args)
        return None
    finally:
        await conn.close()


@_requires_pg
def test_oidc_end_to_end_real_provisioning_and_group_role_pg(app, oidc_env, monkeypatch):
    """Full OIDC callback against a real DB: the user is provisioned via the SAME
    ``upsert_user`` path SAML uses, a default API key is minted, and the OIDC
    ``groups`` claim grants an org role through the shared ``SamlGroupMapping``.
    """
    from ulid import ULID

    tag = uuid.uuid4().hex[:10]
    org_id = str(ULID())
    email = f"oidc-e2e-{tag}@example.com"
    email_lower = email.lower()
    group_value = f"cad-engineers-{tag}"

    # Seed: an org + a group→role mapping (attribute 'groups' -> member).
    asyncio.run(
        _pg(
            "INSERT INTO organizations (id, name, slug, created_at) "
            "VALUES ($1,$2,$3, now())",
            org_id, f"OIDC Org {tag}", f"oidc-org-{tag}",
        )
    )
    asyncio.run(
        _pg(
            "INSERT INTO saml_group_mappings (org_id, attribute_name, group_value, org_role) "
            "VALUES ($1,'groups',$2,'member')",
            org_id, group_value,
        )
    )

    # Reset the engine singleton so it binds to the TestClient portal loop.
    import src.db.engine as _eng

    _eng._ENGINE = None
    _eng._SESSION_FACTORY = None

    idp = MockIdP()
    holder: dict = {}
    try:
        with respx.mock(assert_all_called=False) as router:
            _wire_idp(router, idp, id_token_holder=holder)
            client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
            state, nonce = _start_login(client)
            holder["id_token"] = idp.mint(
                nonce=nonce,
                claims={
                    "sub": f"oidc-{tag}",
                    "email": email,
                    "email_verified": True,
                    "groups": [group_value],
                },
            )
            resp = client.get(f"/auth/oidc/callback?code=c&state={state}")

        assert resp.status_code == 303, resp.text
        assert "dash_session" in resp.headers.get("set-cookie", "")

        # Reset again so verification queries run on a clean engine/loop.
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None

        rows = asyncio.run(
            _pg(
                "SELECT id, auth_provider FROM users WHERE email_lower=$1",
                email_lower, fetch=True,
            )
        )
        assert len(rows) == 1, "user should be provisioned exactly once"
        user_id = int(rows[0]["id"])
        assert rows[0]["auth_provider"] == "oidc"

        # Group→role: membership in the mapped org at role 'member'.
        mrows = asyncio.run(
            _pg(
                "SELECT org_role FROM memberships WHERE user_id=$1 AND org_id=$2",
                user_id, org_id, fetch=True,
            )
        )
        assert len(mrows) == 1 and mrows[0]["org_role"] == "member"

        # A default API key was minted for the new SSO account.
        krows = asyncio.run(
            _pg(
                "SELECT 1 FROM api_keys WHERE user_id=$1 AND revoked_at IS NULL",
                user_id, fetch=True,
            )
        )
        assert len(krows) >= 1
    finally:
        # Collect every org the user touched (incl. the auto-provisioned personal
        # org) so cleanup is complete, then tear down.
        rows = asyncio.run(
            _pg("SELECT id FROM users WHERE email_lower=$1", email_lower, fetch=True)
        )
        if rows:
            uid = int(rows[0]["id"])
            orgs = asyncio.run(
                _pg("SELECT DISTINCT org_id FROM memberships WHERE user_id=$1", uid, fetch=True)
            )
            org_ids = list({org_id, *[r["org_id"] for r in orgs]})
            asyncio.run(_pg("DELETE FROM api_keys WHERE user_id=$1", uid))
            asyncio.run(_pg("DELETE FROM audit_log WHERE user_id=$1", uid))
            asyncio.run(_pg("DELETE FROM auth_identities WHERE user_id=$1", uid))
            asyncio.run(_pg("DELETE FROM scim_identities WHERE user_id=$1", uid))
            asyncio.run(_pg("DELETE FROM memberships WHERE user_id=$1", uid))
            asyncio.run(_pg("DELETE FROM users WHERE id=$1", uid))
            for oid in org_ids:
                asyncio.run(_pg("DELETE FROM saml_group_mappings WHERE org_id=$1", oid))
                asyncio.run(_pg("DELETE FROM organizations WHERE id=$1", oid))
        else:
            asyncio.run(_pg("DELETE FROM saml_group_mappings WHERE org_id=$1", org_id))
            asyncio.run(_pg("DELETE FROM organizations WHERE id=$1", org_id))
        _eng._ENGINE = None
        _eng._SESSION_FACTORY = None
