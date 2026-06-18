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
    os.environ.setdefault("SESSION_SECRET", "test-only")
    import importlib
    from fastapi.testclient import TestClient

    import main as mainmod
    importlib.reload(mainmod)

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.get("/auth/google/start").status_code != 404
    assert client.get("/auth/google/callback").status_code != 404
    assert client.post("/auth/magic/start").status_code != 404
    assert client.get("/auth/magic/verify").status_code != 404
