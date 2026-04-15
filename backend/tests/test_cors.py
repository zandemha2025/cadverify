from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_cors_preflight_from_prod_origin():
    r = client.options(
        "/health",
        headers={
            "Origin": "https://cadverify.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://cadverify.com"


def test_cors_preflight_from_vercel_preview():
    r = client.options(
        "/health",
        headers={
            "Origin": "https://my-feature-branch-abc123.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert (
        r.headers.get("access-control-allow-origin")
        == "https://my-feature-branch-abc123.vercel.app"
    )


def test_cors_rejects_unknown_origin():
    r = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_allow_credentials_false():
    r = client.options(
        "/health",
        headers={
            "Origin": "https://cadverify.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-credentials") is None


def test_cors_allow_headers_explicit():
    r = client.options(
        "/health",
        headers={
            "Origin": "https://cadverify.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    allowed = (r.headers.get("access-control-allow-headers") or "").lower()
    assert "authorization" in allowed
