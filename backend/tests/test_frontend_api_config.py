from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_frontend_uses_runtime_server_origin_and_same_origin_browser_routes():
    api_client = read("frontend/src/lib/api.ts")
    batch_client = read("frontend/src/lib/api/batch.ts")
    api_base = read("frontend/src/lib/api-base.ts")
    signup_page = read("frontend/src/app/(auth)/signup/page.tsx")
    login_page = read("frontend/src/app/(auth)/login/page.tsx")
    login_form = read("frontend/src/app/(auth)/login/login-form.tsx")
    safe_return_path = read("frontend/src/lib/safe-return-path.ts")

    assert "cadvrfy-api.fly.dev" not in api_base
    assert "NEXT_PUBLIC_API_BASE" not in api_base
    assert "process.env.API_BASE" in api_base
    assert 'export const API_BASE = "/api/proxy"' in api_base
    assert "`/api/public-share${normalizedPath}`" in api_base
    assert '.replace(/\\\\[rn]/g, "")' in api_base
    assert "process.env.NEXT_PUBLIC_API_URL" not in api_client
    assert "process.env.NEXT_PUBLIC_API_URL" not in batch_client
    assert "http://localhost:8000/api/v1" not in api_client
    assert "http://localhost:8000/api/v1" not in batch_client
    for auth_page in (signup_page, login_form):
        assert "Continue with Google" not in auth_page
        assert "cf-turnstile" not in auth_page
        assert "startMagic" not in auth_page
        assert "/auth/google/start" not in auth_page
    # Released public signup is email-verified; regulated auth renders a real
    # SSO initiation link instead of a nonfunctional/fabricated provider button.
    assert "Production accounts begin with a single-use email link." in signup_page
    assert "Continue with enterprise SSO" in login_form
    assert "process.env.SSO_LOGIN_PATH" in login_page
    assert 'process.env.MAGIC_LINK_UI_ENABLED === "1"' in login_page
    assert "TURNSTILE_SITE_KEY" in login_page
    assert 'fetch("/api/auth/magic/start"' in login_form
    assert "TurnstileWidget" in login_form
    assert "safeLocalPath(params.get(\"next\")" in login_form
    assert "parsed.origin !== base.origin" in safe_return_path
    assert 'raw.startsWith("//")' in safe_return_path
    assert "next.startsWith" not in login_form


def test_next_api_proxy_streams_large_uploads_and_blocks_redirects():
    proxy_route = read("frontend/src/app/api/proxy/[...path]/route.ts")
    body_helper = read("frontend/src/lib/proxy-request-body.ts")

    assert "req.arrayBuffer()" not in proxy_route
    assert "prepareProxyRequestBody(method, contentType, req.body)" in proxy_route
    assert "body: hasBody ? prepared.body : undefined" in proxy_route
    assert 'duplex?: "half"' in proxy_route
    assert 'if (prepared.streaming) init.duplex = "half"' in proxy_route
    assert 'redirect: "error"' in proxy_route
    assert "signal: req.signal" in proxy_route
    assert "MAX_BUFFERED_PROXY_JSON_BYTES = 1024 * 1024" in body_helper
    assert 'mime.endsWith("+json")' in body_helper
    assert "return { body: stream, streaming: true" in body_helper
    assert "reader.cancel" in body_helper
    assert 'code: "proxy_json_too_large"' in proxy_route
    for unsafe in ('segment.includes("/")', 'segment.includes("\\\\")', 'segment.includes("%")'):
        assert unsafe in proxy_route


def test_public_share_proxy_has_a_narrow_get_only_allowlist():
    public_route = read("frontend/src/app/api/public-share/[...path]/route.ts")

    assert "const BASE62_ID = /^[A-Za-z0-9]{12}$/" in public_route
    assert "export async function GET" in public_route
    assert "export const POST" not in public_route
    assert 'redirect: "error"' in public_route
    assert 'cache: "no-store"' in public_route
    assert 'headers.set("cache-control", "private, no-store")' in public_route
    assert "Cookie" not in public_route


def test_deploy_configs_use_runtime_backend_origins():
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
    assert "NEXT_PUBLIC_API_BASE" not in combined
    assert "API_BASE" in combined
    assert "cadvrfy-api" not in read("frontend/fly.toml")
    assert "FLY_APP_NAME" in read("scripts/ops/kill-switch.sh")


def test_frontend_fails_closed_on_invalid_commercial_runtime_origin():
    instrumentation = read("frontend/instrumentation.ts")
    fly_config = read("frontend/fly.toml")
    promotion = read("scripts/ops/promote-fly-release.sh")

    assert "assertProductionRuntimeConfig()" in instrumentation
    assert "PRODUCTION_PUBLIC_API_TLS_REQUIRED" in instrumentation
    assert 'parsed.protocol !== "https:"' in instrumentation
    assert 'parsed.origin !== raw' in instrumentation
    assert 'PRODUCTION_PUBLIC_API_TLS_REQUIRED = "1"' in fly_config
    assert 'API_BASE = "https://' not in fly_config
    assert '--env "API_BASE=$CADVERIFY_PUBLIC_API_BASE"' in promotion


def test_first_party_auth_proxy_and_magic_exchange_are_production_gated():
    login_route = read("frontend/src/app/api/auth/login/route.ts")
    signup_route = read("frontend/src/app/api/auth/signup/route.ts")
    magic_start = read("frontend/src/app/api/auth/magic/start/route.ts")
    magic_exchange = read("frontend/src/app/api/auth/magic/exchange/route.ts")
    proxy_health = read("frontend/src/app/api/auth/proxy-health/route.ts")
    auth_proxy = read("frontend/src/lib/auth-proxy.ts")
    magic_backend = read("backend/src/auth/magic_link.py")
    password_backend = read("backend/src/auth/password.py")
    promotion = read("scripts/ops/promote-fly-release.sh")

    for route in (login_route, signup_route, magic_start, magic_exchange, proxy_health):
        assert "signedAuthProxyHeaders" in route
    assert "Fly-Client-IP" in auth_proxy
    assert 'digest("base64url")' in auth_proxy
    assert "AUTH_PROXY_SECRET" in auth_proxy
    assert 'decoded.toString("base64") !== raw' in auth_proxy
    assert 'decoded.toString("base64") !== raw' in read("frontend/instrumentation.ts")
    assert "await setSession(data.session)" in magic_exchange
    assert "await setRevealOnce(data.mint_once)" in magic_exchange
    assert "session: data.session" not in magic_exchange
    assert "/magic/verify#token=" in magic_backend
    assert "/magic/verify?token=" not in magic_backend
    assert "require_auth_proxy_if_enabled(request)" in magic_backend
    assert "require_auth_proxy_if_enabled(request)" in password_backend
    assert "CADVERIFY_REQUIRED_FLY_SECRETS=AUTH_PROXY_SECRET,TURNSTILE_SITE_KEY" in promotion
    assert '"$CADVERIFY_DASHBOARD_ORIGIN/api/auth/proxy-health"' in promotion


def test_oauth_state_cookie_is_short_lived_and_secure_in_production():
    main = read("backend/main.py")

    assert 'session_cookie="cv_oauth_state"' in main
    assert "max_age=15 * 60" in main
    assert 'same_site="lax"' in main
    assert "https_only=_is_production()" in main


def test_frontend_observability_scrubs_auth_and_disables_replay():
    client = read("frontend/instrumentation-client.ts")
    server = read("frontend/sentry.server.config.ts")
    scrubber = read("frontend/src/lib/sentry-scrub.ts")

    assert "replaysOnErrorSampleRate: 0" in client
    assert "sendDefaultPii: false" in client
    assert "sendDefaultPii: false" in server
    assert "beforeSend: scrubSentryEvent" in client
    assert "beforeSend: scrubSentryEvent" in server
    for key in ("password", "dash_session", "mint_once", "cf_turnstile_response"):
        assert f'"{key}"' in scrubber


def test_regulated_frontend_hides_password_setup_form():
    page = read("frontend/src/app/(app)/settings/security/page.tsx")
    password_form = read(
        "frontend/src/app/(app)/settings/security/security-settings-client.tsx"
    )

    assert "process.env.AUTH_MODE" in page
    assert 'authMode === "password" || authMode === "hybrid"' in page
    assert "Password setup is disabled in this environment." in page
    assert 'fetch("/api/auth/password/initialize"' not in page
    assert 'fetch("/api/auth/password/initialize"' in password_form


def test_regulated_ingress_preserves_next_share_pages_and_release_requires_ci():
    ingress = read("charts/cadverify/templates/ingress.yaml")
    release = read(".github/workflows/regulated-release.yml")

    assert "- path: /s\n" not in ingress
    assert "actions: read" in release
    assert "gh run list" in release
    assert '--commit "$GITHUB_SHA"' in release
    assert "--status success" in release


def test_regulated_promotion_proves_distinct_staging_and_production_boundaries():
    deploy = read(".github/workflows/regulated-deploy.yml")
    promote = read(".github/workflows/regulated-promote.yml")

    assert "AWS_GOVCLOUD_ACCOUNT_ID" in deploy
    assert "CADVERIFY_BOUNDARY_ENVIRONMENT" in deploy
    assert "aws sts get-caller-identity" in deploy
    assert "aws eks describe-cluster" in deploy
    assert "boundary_fingerprint" in deploy
    assert "FORBIDDEN_BOUNDARY_FINGERPRINT" in deploy
    assert "needs.deploy-staging.outputs.boundary_fingerprint" in promote


def test_auth_route_responses_are_not_cacheable():
    for path in (
        "frontend/src/app/api/auth/login/route.ts",
        "frontend/src/app/api/auth/signup/route.ts",
        "frontend/src/app/api/auth/magic/start/route.ts",
        "frontend/src/app/api/auth/magic/exchange/route.ts",
        "frontend/src/app/api/auth/password/initialize/route.ts",
        "frontend/src/app/api/auth/logout/route.ts",
    ):
        assert '"cache-control": "no-store"' in read(path)


def test_frontend_uses_nonce_csp_for_sensitive_pages():
    proxy = read("frontend/src/proxy.ts")
    layout = read("frontend/src/app/layout.tsx")
    login = read("frontend/src/app/(auth)/login/page.tsx")
    turnstile = read("frontend/src/components/auth/turnstile-widget.tsx")

    assert "Content-Security-Policy" in proxy
    assert "'strict-dynamic'" in proxy
    assert "'nonce-${nonce}'" in proxy
    assert "frame-ancestors 'none'" in proxy
    assert "https://challenges.cloudflare.com" in proxy
    assert "Strict-Transport-Security" in proxy
    assert "X-Content-Type-Options" in proxy
    assert "Permissions-Policy" in proxy
    assert "await connection()" in layout
    assert "nonce={nonce}" in layout
    assert 'headers()).get("x-nonce")' in login
    assert "nonce={nonce}" in turnstile


def test_public_docs_use_live_urls_and_route_shims_exist():
    # /docs is now a compatibility redirect to /developers (the dark-theater
    # API quickstart). The live-URL contract moved with it — assert the redirect
    # shim on /docs and the live/absent URLs on its target, /developers.
    docs = read("frontend/src/app/docs/page.tsx")
    developers = read("frontend/src/app/(site)/developers/page.tsx")
    scalar_route = read("frontend/src/app/scalar/route.ts")

    assert 'redirect("/developers")' in docs

    assert "backendOrigin()" in developers
    assert "{apiOrigin}/api/v1/validate" in developers
    assert "cadvrfy-api.fly.dev" not in developers
    assert 'git clone &quot;$PROOFSHAPE_DEPLOYMENT_REPOSITORY&quot; proofshape' in developers
    assert "https://github.com/zandemha2025/cadverify" not in developers
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
