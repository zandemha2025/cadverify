"""Tests for SAML 2.0 SP authentication.

All python3-saml internals are mocked so tests run without a real IdP
or xmlsec1 installed.
"""
from __future__ import annotations

import importlib
import json
import os
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers to build a test app with specific AUTH_MODE
# ---------------------------------------------------------------------------


def _make_app(auth_mode: str = "hybrid"):
    """Create a fresh FastAPI app with the given AUTH_MODE.

    We patch environment before importing main so the AUTH_MODE gating
    takes effect on router inclusion.
    """
    with patch.dict(os.environ, {"AUTH_MODE": auth_mode}):
        import main

        importlib.reload(main)
        return main.app


def _mock_saml_auth():
    """Return a MagicMock that mimics OneLogin_Saml2_Auth."""
    mock_auth = MagicMock()
    mock_auth.login.return_value = "https://idp.example.com/sso?SAMLRequest=abc"
    mock_auth.logout.return_value = "https://idp.example.com/slo?SAMLRequest=xyz"
    mock_auth.process_response.return_value = None
    mock_auth.process_slo.return_value = None
    mock_auth.get_errors.return_value = []
    mock_auth.is_authenticated.return_value = True
    mock_auth.get_nameid.return_value = "user@enterprise.com"
    mock_auth.get_attributes.return_value = {}

    # Metadata support
    mock_settings = MagicMock()
    mock_settings.get_sp_metadata.return_value = (
        '<?xml version="1.0"?>'
        '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"'
        ' entityID="https://cadverify.com/saml/metadata">'
        "</EntityDescriptor>"
    )
    mock_settings.validate_metadata.return_value = []
    mock_auth.get_settings.return_value = mock_settings

    return mock_auth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("src.auth.saml._build_auth")
def test_saml_metadata_endpoint(mock_build_auth):
    """GET /auth/saml/metadata returns 200 with XML containing EntityDescriptor."""
    mock_build_auth.return_value = _mock_saml_auth()
    app = _make_app("saml")
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/auth/saml/metadata")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers.get("content-type", "")
    assert "<EntityDescriptor" in resp.text


@patch("src.auth.saml._build_auth")
def test_saml_login_redirect(mock_build_auth):
    """GET /auth/saml/login returns 302 redirect to IdP."""
    mock_build_auth.return_value = _mock_saml_auth()
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/saml/login")
    assert resp.status_code == 302
    assert "idp.example.com" in resp.headers.get("location", "")


@patch("src.auth.saml._saml_provision_user", new_callable=AsyncMock)
@patch("src.auth.saml.get_user_session_version", new_callable=AsyncMock)
@patch("src.auth.saml._build_auth")
def test_saml_acs_provisions_user(mock_build_auth, mock_session_version, mock_provision):
    """POST /auth/saml/acs provisions user and sets session cookie."""
    mock_build_auth.return_value = _mock_saml_auth()
    mock_session_version.return_value = 0
    mock_provision.return_value = 42
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False)

    resp = client.post("/auth/saml/acs", data={"SAMLResponse": "base64data"})
    assert resp.status_code == 303
    mock_provision.assert_called_once_with("user@enterprise.com")
    # Session cookie should be set
    assert "dash_session" in resp.headers.get("set-cookie", "")


@patch("src.auth.saml._apply_saml_group_assignment_for_login", new_callable=AsyncMock)
@patch("src.auth.saml._saml_provision_user", new_callable=AsyncMock)
@patch("src.auth.saml.get_user_session_version", new_callable=AsyncMock)
@patch("src.auth.saml._build_auth")
def test_saml_acs_applies_group_assignment(
    mock_build_auth, mock_session_version, mock_provision, mock_assignment
):
    """POST /auth/saml/acs applies IdP group attributes before issuing session."""
    from src.services.org_saml_service import SamlGroupAssignment

    mock_auth = _mock_saml_auth()
    mock_auth.get_attributes.return_value = {
        "memberOf": ["cn=cad-engineers"],
        "department": "AM",
    }
    mock_build_auth.return_value = mock_auth
    mock_session_version.return_value = 0
    mock_provision.return_value = 42
    mock_assignment.return_value = SamlGroupAssignment(
        matched=True, org_id="org_enterprise", org_role="member", created=True
    )
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False)

    resp = client.post("/auth/saml/acs", data={"SAMLResponse": "base64data"})

    assert resp.status_code == 303
    mock_assignment.assert_awaited_once_with(
        42, {"memberOf": ["cn=cad-engineers"], "department": ["AM"]}
    )
    assert "dash_session" in resp.headers.get("set-cookie", "")


@patch("src.auth.saml._apply_saml_group_assignment_for_login", new_callable=AsyncMock)
@patch("src.auth.saml._saml_provision_user", new_callable=AsyncMock)
@patch("src.auth.saml._build_auth")
def test_saml_acs_ambiguous_group_mapping_blocks_session(
    mock_build_auth, mock_provision, mock_assignment
):
    """Ambiguous IdP group mappings fail closed and do not set a session."""
    from fastapi import HTTPException

    mock_auth = _mock_saml_auth()
    mock_auth.get_attributes.return_value = {"memberOf": ["cn=shared-cad"]}
    mock_build_auth.return_value = mock_auth
    mock_provision.return_value = 42
    mock_assignment.side_effect = HTTPException(
        403,
        detail={
            "code": "saml_group_mapping_ambiguous",
            "message": "ambiguous",
        },
    )
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)

    resp = client.post("/auth/saml/acs", data={"SAMLResponse": "base64data"})

    assert resp.status_code == 403
    assert "saml_group_mapping_ambiguous" in resp.text
    assert "dash_session" not in resp.headers.get("set-cookie", "")


@patch("src.auth.saml._build_auth")
def test_saml_acs_rejects_unauthenticated(mock_build_auth):
    """POST /auth/saml/acs returns 401 when assertion is not authenticated."""
    mock_auth = _mock_saml_auth()
    mock_auth.is_authenticated.return_value = False
    mock_build_auth.return_value = mock_auth
    app = _make_app("saml")
    client = TestClient(app)

    resp = client.post("/auth/saml/acs", data={"SAMLResponse": "bad"})
    assert resp.status_code == 401
    assert "saml_not_authenticated" in resp.text


def test_auth_mode_saml_disables_google():
    """When AUTH_MODE=saml, /auth/google/start returns 404."""
    app = _make_app("saml")
    client = TestClient(app)

    resp = client.get("/auth/google/start")
    assert resp.status_code == 404


@patch("src.auth.oauth.oauth.google.authorize_redirect", new_callable=AsyncMock)
@patch("src.auth.saml._build_auth")
def test_auth_mode_hybrid_enables_both(mock_build_auth, mock_authorize_redirect):
    """When AUTH_MODE=hybrid, both SAML metadata and Google start are available."""
    mock_build_auth.return_value = _mock_saml_auth()
    from fastapi.responses import RedirectResponse

    mock_authorize_redirect.return_value = RedirectResponse(
        "https://accounts.google.com/mock-authorize", status_code=302
    )
    app = _make_app("hybrid")
    # Hermetic: without a live REDIS_URL, /auth/google/start would 500 on the
    # unconditional per_ip_signup_limit KeyError; with REDIS_URL live it would
    # reach authlib's authorize_redirect, which performs a REAL network GET to
    # Google's OIDC discovery endpoint. Mock authorize_redirect (patched above)
    # so the route is exercised with zero network access either way, and
    # disable follow_redirects as defense in depth against ever dereferencing
    # a 302 to a real external host.
    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)

    saml_resp = client.get("/auth/saml/metadata")
    assert saml_resp.status_code == 200

    # Verify Google route is registered and reachable without touching the
    # network (authorize_redirect is mocked above).
    assert client.get("/auth/google/start").status_code != 404
    mock_authorize_redirect.assert_awaited_once()


@patch("src.auth.saml._build_auth")
def test_saml_logout_redirects_to_idp(mock_build_auth):
    """GET /auth/saml/logout returns 302 redirect to IdP SLO."""
    mock_build_auth.return_value = _mock_saml_auth()
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/saml/logout")
    assert resp.status_code == 302
    assert "idp.example.com/slo" in resp.headers.get("location", "")


# ---------------------------------------------------------------------------
# S2: settings.json ${ENV_VAR} expansion
# ---------------------------------------------------------------------------


def test_saml_settings_expandvars(tmp_path, monkeypatch):
    """${ENV_VAR} placeholders in settings.json resolve from the environment."""
    monkeypatch.setenv("SAML_SP_ENTITY_ID", "https://sp.example.com/meta")
    monkeypatch.setenv("SAML_IDP_SSO_URL", "https://idp.example.com/sso")
    (tmp_path / "settings.json").write_text(
        json.dumps(
            {
                "sp": {"entityId": "${SAML_SP_ENTITY_ID}"},
                "idp": {"singleSignOnService": {"url": "${SAML_IDP_SSO_URL}"}},
                "strict": True,
            }
        )
    )
    monkeypatch.setenv("SAML_CONFIG_DIR", str(tmp_path))

    from src.auth.saml import _load_saml_settings

    s = _load_saml_settings()
    assert s["sp"]["entityId"] == "https://sp.example.com/meta"
    assert s["idp"]["singleSignOnService"]["url"] == "https://idp.example.com/sso"
    assert s["strict"] is True  # non-string values untouched


def test_saml_settings_undefined_var_left_verbatim(tmp_path, monkeypatch):
    """An undefined ${VAR} is left verbatim rather than silently blanked."""
    monkeypatch.delenv("SAML_SP_ENTITY_ID", raising=False)
    (tmp_path / "settings.json").write_text(
        json.dumps({"sp": {"entityId": "${SAML_SP_ENTITY_ID}"}})
    )
    monkeypatch.setenv("SAML_CONFIG_DIR", str(tmp_path))

    from src.auth.saml import _load_saml_settings

    s = _load_saml_settings()
    assert s["sp"]["entityId"] == "${SAML_SP_ENTITY_ID}"


# ---------------------------------------------------------------------------
# S3: SAML provisioning mints an API key only when none is active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.services.audit_service.fire_and_forget_audit", new_callable=AsyncMock)
@patch("src.auth.saml.create_api_key", new_callable=AsyncMock)
@patch("src.auth.saml.user_has_active_api_key", new_callable=AsyncMock)
@patch("src.auth.saml.upsert_user", new_callable=AsyncMock)
async def test_saml_provision_mints_when_no_active_key(
    mock_upsert, mock_has_key, mock_create, mock_audit
):
    from src.auth.saml import _saml_provision_user

    mock_upsert.return_value = 5
    mock_has_key.return_value = False

    uid = await _saml_provision_user("User@Example.com")

    assert uid == 5
    mock_upsert.assert_awaited_once_with(
        email="User@Example.com",
        google_sub=None,
        email_lower="user@example.com",
        disposable_flag=False,
        auth_provider="saml",
    )
    mock_create.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.services.audit_service.fire_and_forget_audit", new_callable=AsyncMock)
@patch("src.auth.saml.create_api_key", new_callable=AsyncMock)
@patch("src.auth.saml.user_has_active_api_key", new_callable=AsyncMock)
@patch("src.auth.saml.upsert_user", new_callable=AsyncMock)
async def test_saml_provision_skips_when_key_exists(
    mock_upsert, mock_has_key, mock_create, mock_audit
):
    from src.auth.saml import _saml_provision_user

    mock_upsert.return_value = 5
    mock_has_key.return_value = True

    uid = await _saml_provision_user("User@Example.com")

    assert uid == 5
    mock_upsert.assert_awaited_once_with(
        email="User@Example.com",
        google_sub=None,
        email_lower="user@example.com",
        disposable_flag=False,
        auth_provider="saml",
    )
    mock_create.assert_not_called()
