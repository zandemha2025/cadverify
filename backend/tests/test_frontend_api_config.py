from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_frontend_uses_browser_reachable_api_base():
    api_client = read("frontend/src/lib/api.ts")
    batch_client = read("frontend/src/lib/api/batch.ts")
    api_base = read("frontend/src/lib/api-base.ts")
    signup_page = read("frontend/src/app/(auth)/signup/page.tsx")
    login_page = read("frontend/src/app/(auth)/login/page.tsx")

    assert "https://cadvrfy-api.fly.dev" in api_base
    assert "NEXT_PUBLIC_API_BASE" in api_base
    assert '.replace(/\\\\[rn]/g, "")' in api_base
    assert "process.env.NEXT_PUBLIC_API_URL" not in api_client
    assert "process.env.NEXT_PUBLIC_API_URL" not in batch_client
    assert "http://localhost:8000/api/v1" not in api_client
    assert "http://localhost:8000/api/v1" not in batch_client
    for auth_page in (signup_page, login_page):
        assert "Continue with Google" not in auth_page
        assert "cf-turnstile" not in auth_page
        assert "startMagic" not in auth_page
        assert "/auth/google/start" not in auth_page
    # Both auth pages were componentized onto AuthFrame; each still states
    # honestly that SSO is conditional on configured provider credentials
    # (never a fabricated third-party button). The copy differs per page.
    assert "Enterprise SSO is enabled when a provider is connected." in signup_page
    assert "SSO appears when provider credentials are configured." in login_page


def test_next_api_proxy_is_not_used_for_large_uploads():
    proxy_route = ROOT / "frontend/src/app/api/[...path]/route.ts"
    proxy_helper = ROOT / "frontend/src/lib/backend-proxy.ts"
    assert not proxy_route.exists()
    assert not proxy_helper.exists()


def test_deploy_configs_reference_live_backend_origin():
    checked_files = [
        "frontend/fly.toml",
        "docker-compose.yml",
        "cadverify-enterprise/docker-compose.yml",
        "charts/cadverify/templates/deployment-frontend.yaml",
        "scripts/ops/kill-switch.sh",
        ".github/workflows/ci.yml",
    ]

    combined = "\n".join(read(path) for path in checked_files)
    assert "cadverify-api" not in combined
    assert "NEXT_PUBLIC_API_URL" not in combined
    assert "NEXT_PUBLIC_API_BASE" in combined
    assert "cadvrfy-api" in read("frontend/fly.toml")
    assert "cadvrfy-api" in read("scripts/ops/kill-switch.sh")


def test_public_docs_use_live_urls_and_route_shims_exist():
    # /docs is now a compatibility redirect to /developers (the dark-theater
    # API quickstart). The live-URL contract moved with it — assert the redirect
    # shim on /docs and the live/absent URLs on its target, /developers.
    docs = read("frontend/src/app/docs/page.tsx")
    developers = read("frontend/src/app/(site)/developers/page.tsx")
    scalar_route = read("frontend/src/app/scalar/route.ts")

    assert 'redirect("/developers")' in docs

    assert "https://cadvrfy-api.fly.dev/api/v1/validate" in developers
    assert "https://github.com/zandemha2025/cadverify" in developers
    assert "https://api.cadverify.com" not in developers
    assert "https://github.com/cadverify/cadverify" not in developers
    assert 'backendUrl("/docs")' in scalar_route

    # Legacy URLs now resolve via next.config redirects (the physical shim pages
    # were removed when auth moved to the (auth)/(app) route groups and API keys
    # were demoted to Settings -> Developer). Assert the redirect shims exist.
    next_config = read("frontend/next.config.ts")
    assert '"/auth/signup"' in next_config and '"/signup"' in next_config
    assert '"/dashboard/keys"' in next_config
    assert '"/dashboard/analyses/:id"' in next_config
    assert '"/analyses/:id"' in next_config
    assert '"/settings/developer"' in next_config
