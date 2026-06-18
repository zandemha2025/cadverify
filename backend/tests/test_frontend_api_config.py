from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_frontend_uses_browser_reachable_api_base():
    api_client = read("frontend/src/lib/api.ts")
    batch_client = read("frontend/src/lib/api/batch.ts")
    api_base = read("frontend/src/lib/api-base.ts")
    signup_page = read("frontend/src/app/(auth)/signup/page.tsx")

    assert "https://cadvrfy-api.fly.dev" in api_base
    assert "NEXT_PUBLIC_API_BASE" in api_base
    assert '.replace(/\\\\[rn]/g, "")' in api_base
    assert '.replace(/\\\\[rn]/g, "").trim()' in signup_page
    assert "process.env.NEXT_PUBLIC_API_URL" not in api_client
    assert "process.env.NEXT_PUBLIC_API_URL" not in batch_client
    assert "http://localhost:8000/api/v1" not in api_client
    assert "http://localhost:8000/api/v1" not in batch_client


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
    docs = read("frontend/src/app/docs/page.tsx")
    scalar_route = read("frontend/src/app/scalar/route.ts")

    assert "https://cadvrfy-api.fly.dev/api/v1/validate" in docs
    assert "https://cadvrfy.vercel.app" in docs
    assert "https://github.com/zandemha2025/cadverify" in docs
    assert "https://api.cadverify.com" not in docs
    assert "https://github.com/cadverify/cadverify" not in docs
    assert 'backendUrl("/docs")' in scalar_route

    assert (ROOT / "frontend/src/app/auth/signup/page.tsx").exists()
    assert (ROOT / "frontend/src/app/dashboard/keys/page.tsx").exists()
    assert (ROOT / "frontend/src/app/dashboard/analyses/[id]/page.tsx").exists()
