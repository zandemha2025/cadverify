"""Tests for SAML 2.0 SP authentication.

All python3-saml internals are mocked so tests run without a real IdP
or xmlsec1 installed.
"""
from __future__ import annotations

import importlib
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
    client = TestClient(app)

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
@patch("src.auth.saml._build_auth")
def test_saml_acs_provisions_user(mock_build_auth, mock_provision):
    """POST /auth/saml/acs provisions user and sets session cookie."""
    mock_build_auth.return_value = _mock_saml_auth()
    mock_provision.return_value = 42
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False)

    resp = client.post("/auth/saml/acs", data={"SAMLResponse": "base64data"})
    assert resp.status_code == 303
    mock_provision.assert_called_once_with("user@enterprise.com")
    # Session cookie should be set
    assert "dash_session" in resp.headers.get("set-cookie", "")


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


@patch("src.auth.saml._build_auth")
def test_auth_mode_hybrid_enables_both(mock_build_auth):
    """When AUTH_MODE=hybrid, both SAML metadata and Google start are available."""
    mock_build_auth.return_value = _mock_saml_auth()
    app = _make_app("hybrid")
    client = TestClient(app)

    saml_resp = client.get("/auth/saml/metadata")
    assert saml_resp.status_code == 200

    # Verify Google route is registered (not 404). The actual call may fail
    # due to missing REDIS_URL for rate limiting, but route existence is
    # confirmed by checking it is NOT a 404.
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/auth/google/start" in routes


@patch("src.auth.saml._build_auth")
def test_saml_logout_redirects_to_idp(mock_build_auth):
    """GET /auth/saml/logout returns 302 redirect to IdP SLO."""
    mock_build_auth.return_value = _mock_saml_auth()
    app = _make_app("saml")
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/auth/saml/logout")
    assert resp.status_code == 302
    assert "idp.example.com/slo" in resp.headers.get("location", "")
