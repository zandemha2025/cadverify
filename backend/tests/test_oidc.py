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
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from authlib.jose import JsonWebKey, JsonWebToken
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.services.org_saml_service import SamlGroupAssignment

ISSUER = "https://mock-idp.local"
CLIENT_ID = "client-abc"
CLIENT_SECRET = "shhh"
REDIRECT_URI = "https://api.cadverify.com/auth/oidc/callback"

_JWT = JsonWebToken(["RS256"])

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
    "groups": ["11111111-2222-3333-4444-555555555555", "cad-eng"],
}


class MockIdP:
    """A local OIDC provider: keypair + discovery + JWKS + id_token minting."""

    def __init__(self, issuer: str = ISSUER, client_id: str = CLIENT_ID):
        self.issuer = issuer
        self.client_id = client_id
        self._install_key("kid-1")

    def _install_key(self, kid: str) -> None:
        key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        self.kid = kid
        self._priv = {**key.as_dict(is_private=True), "kid": kid}
        self._pub = {**key.as_dict(is_private=False), "kid": kid, "use": "sig", "alg": "RS256"}

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
        aud: str | None = None,
        exp_delta: int = 300,
        iat_delta: int = 0,
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
        token = _JWT.encode({"alg": "RS256", "kid": self.kid}, payload, self._priv)
        return token.decode() if isinstance(token, bytes) else token


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
def app():
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
    router.get(f"{idp.issuer}/userinfo").mock(
        side_effect=lambda req: httpx.Response(200, json=userinfo or {})
    )


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


# ══════════════════════════════════════════════════════════════════════════
# Happy path — Okta-shaped id_token with groups in the id_token
# ══════════════════════════════════════════════════════════════════════════


def test_oidc_happy_path_okta_shaped(app, oidc_env, monkeypatch):
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=42)
    assign = AsyncMock(return_value=SamlGroupAssignment(matched=True, org_id="org1", org_role="member", created=True))
    monkeypatch.setattr(oidc, "_oidc_provision_user", provision)
    monkeypatch.setattr(oidc, "_apply_oidc_group_assignment_for_login", assign)
    monkeypatch.setattr(oidc, "get_user_session_version", AsyncMock(return_value=0))

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
    provision.assert_awaited_once_with("engineer@okta-enterprise.com")
    # Group→role assignment reuses the SAML path with the OIDC groups claim.
    assign.assert_awaited_once_with(42, {"groups": ["Everyone", "cad-engineers"]})


# ══════════════════════════════════════════════════════════════════════════
# Happy path — Entra-shaped: thin id_token, email + groups via userinfo fallback
# ══════════════════════════════════════════════════════════════════════════


def test_oidc_happy_path_entra_shaped_userinfo_fallback(app, oidc_env, monkeypatch):
    from unittest.mock import AsyncMock

    import src.auth.oidc as oidc

    provision = AsyncMock(return_value=7)
    assign = AsyncMock(return_value=SamlGroupAssignment(matched=False))
    monkeypatch.setattr(oidc, "_oidc_provision_user", provision)
    monkeypatch.setattr(oidc, "_apply_oidc_group_assignment_for_login", assign)
    monkeypatch.setattr(oidc, "get_user_session_version", AsyncMock(return_value=0))

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
    provision.assert_awaited_once_with("engineer@entra-enterprise.com")
    assign.assert_awaited_once_with(
        7, {"groups": ["11111111-2222-3333-4444-555555555555", "cad-eng"]}
    )


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

    provision = AsyncMock(return_value=99)
    monkeypatch.setattr(oidc, "_oidc_provision_user", provision)
    monkeypatch.setattr(oidc, "_apply_oidc_group_assignment_for_login", AsyncMock())
    monkeypatch.setattr(oidc, "get_user_session_version", AsyncMock(return_value=0))

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

    provision = AsyncMock(return_value=55)
    monkeypatch.setattr(oidc, "_oidc_provision_user", provision)
    monkeypatch.setattr(oidc, "_apply_oidc_group_assignment_for_login", AsyncMock(
        return_value=SamlGroupAssignment(matched=False)))
    monkeypatch.setattr(oidc, "get_user_session_version", AsyncMock(return_value=0))

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
                claims={"sub": f"oidc-{tag}", "email": email, "groups": [group_value]},
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
