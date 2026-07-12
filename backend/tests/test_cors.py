import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://proofshape.example")
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    import main

    importlib.reload(main)
    return TestClient(main.app)


def test_cors_preflight_from_configured_dashboard(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://proofshape.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://proofshape.example"


def test_cors_rejects_unconfigured_vercel_preview(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://my-feature-branch-abc123.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_rejects_unknown_origin(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_allow_credentials_false(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://proofshape.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-credentials") is None


def test_cors_allow_headers_explicit(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://proofshape.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    allowed = (r.headers.get("access-control-allow-headers") or "").lower()
    assert "authorization" in allowed
