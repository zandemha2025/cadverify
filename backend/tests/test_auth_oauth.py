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
