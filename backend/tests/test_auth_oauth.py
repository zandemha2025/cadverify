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
    import main as mainmod
    importlib.reload(mainmod)
    paths = _collect_route_paths(mainmod.app.routes)
    assert "/auth/google/start" in paths
    assert "/auth/google/callback" in paths
    assert "/auth/magic/start" in paths
    assert "/auth/magic/verify" in paths
