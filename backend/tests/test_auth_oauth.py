def _collect_route_paths(routes, prefix=""):
    paths = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(f"{prefix}{path}")

        nested = getattr(route, "routes", None)
        if nested:
            paths.update(
                _collect_route_paths(nested, f"{prefix}{getattr(route, 'prefix', '')}")
            )

    return paths


def test_oauth_router_importable():
    from src.auth.oauth import router
    paths = _collect_route_paths(router.routes)
    assert "/google/start" in paths
    assert "/google/callback" in paths


def test_magic_router_importable():
    from src.auth.magic_link import router
    paths = _collect_route_paths(router.routes)
    assert "/magic/start" in paths
    assert "/magic/verify" in paths


def test_main_wires_auth_routers():
    import os
    from unittest.mock import AsyncMock, patch

    os.environ.setdefault("SESSION_SECRET", "test-only")
    import importlib
    from fastapi.responses import RedirectResponse
    from fastapi.testclient import TestClient

    import main as mainmod
    importlib.reload(mainmod)

    # Hermetic: /auth/google/start would otherwise call authlib's
    # authorize_redirect, which performs a REAL network GET to
    # https://accounts.google.com/.well-known/openid-configuration
    # (OIDC discovery, via server_metadata_url) before it can even build the
    # redirect — independent of whether the test client follows redirects.
    # Mock the authlib call so this route-existence check never touches the
    # network, and disable follow_redirects as defense in depth so a 302 to
    # a real external host is never dereferenced by the test client either.
    with patch(
        "src.auth.oauth.oauth.google.authorize_redirect", new_callable=AsyncMock
    ) as mock_authorize_redirect:
        mock_authorize_redirect.return_value = RedirectResponse(
            "https://accounts.google.com/mock-authorize", status_code=302
        )
        client = TestClient(
            mainmod.app, raise_server_exceptions=False, follow_redirects=False
        )
        assert client.get("/auth/google/start").status_code != 404
        mock_authorize_redirect.assert_awaited_once()

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.get("/auth/google/callback").status_code != 404
    assert client.post("/auth/magic/start").status_code != 404
    assert client.get("/auth/magic/verify").status_code != 404


def test_password_mode_with_magic_config_mounts_magic_without_google(monkeypatch):
    """Launch config: AUTH_MODE=password + the magic-link trio configured
    (RESEND_API_KEY/MAGIC_LINK_SECRET/DASHBOARD_ORIGIN) must mount
    /auth/magic/* WITHOUT any Google credentials — magic-link is decoupled
    from AUTH_MODE (see main._magic_link_enabled)."""
    import importlib

    from fastapi.testclient import TestClient

    import main as mainmod

    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    # MAGIC_LINK_SECRET and DASHBOARD_ORIGIN are already set to valid values
    # by the autouse _auth_env fixture in conftest.py.
    importlib.reload(mainmod)

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.post("/auth/magic/start").status_code != 404
    assert client.get("/auth/magic/verify").status_code != 404
    # Google is NOT mounted — password+magic must not require it.
    assert client.get("/auth/google/start").status_code == 404
    assert client.get("/auth/google/callback").status_code == 404
    # Password auth stays mounted unconditionally.
    assert client.post("/auth/login").status_code != 404


def test_password_mode_without_resend_key_magic_absent(monkeypatch):
    """AUTH_MODE=password with the magic-link trio incomplete (no
    RESEND_API_KEY) → magic routes are NOT mounted (unchanged pre-fix
    behavior for an unconfigured password deployment); password login is
    unaffected."""
    import importlib

    from fastapi.testclient import TestClient

    import main as mainmod

    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    importlib.reload(mainmod)

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.post("/auth/magic/start").status_code == 404
    assert client.get("/auth/magic/verify").status_code == 404
    assert client.get("/auth/google/start").status_code == 404
    assert client.post("/auth/login").status_code != 404
