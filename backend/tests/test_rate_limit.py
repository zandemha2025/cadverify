"""Unit tests for src.auth.rate_limit (AUTH-07).

Builds an isolated FastAPI app so the global test bypass (conftest
_bypass_api_key_auth) doesn't interfere. Uses a 3/minute limit to keep
the test fast while still exercising all four X-RateLimit-* headers.
"""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi import Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


@pytest.fixture
def client_with_limits(monkeypatch):
    # Force memory:// for test speed and isolation.
    monkeypatch.setenv("REDIS_URL", "memory://")
    import src.auth.rate_limit as rl

    importlib.reload(rl)
    from src.auth.require_api_key import AuthedUser

    app = FastAPI()
    app.state.limiter = rl.limiter
    app.add_exception_handler(RateLimitExceeded, rl.rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    async def fake_dep(request: Request):
        u = AuthedUser(user_id=1, api_key_id=1, key_prefix="abcd1234")
        request.state.authed_user = u
        return u

    @app.get("/t")
    @rl.limiter.limit("3/minute")
    async def t(
        request: Request,
        response: Response,
        user: AuthedUser = Depends(fake_dep),
    ):
        return {"ok": True}

    return TestClient(app)


def test_within_limit(client_with_limits):
    for _ in range(3):
        assert client_with_limits.get("/t").status_code == 200


def test_over_limit_returns_429_with_headers(client_with_limits):
    for _ in range(3):
        client_with_limits.get("/t")
    r = client_with_limits.get("/t")
    assert r.status_code == 429
    assert r.headers["Retry-After"] != ""
    assert r.headers["X-RateLimit-Limit"] == "3"
    assert r.headers["X-RateLimit-Remaining"] == "0"
    assert int(r.headers["X-RateLimit-Reset"]) > int(time.time())
    body = r.json()
    assert body["code"] == "rate_limited"
    assert "doc_url" in body


def test_successful_response_has_ratelimit_headers(client_with_limits):
    r = client_with_limits.get("/t")
    assert r.status_code == 200
    # slowapi's headers_enabled populates these on 200 responses too.
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers


# ---------------------------------------------------------------------------
# Storage backend resolution (F-ARCH-3): fail loud in production
# ---------------------------------------------------------------------------


def test_resolve_storage_uri_requires_redis_in_production(monkeypatch):
    """RELEASE set + no REDIS_URL -> fail loud (not silent memory:// fallback)."""
    monkeypatch.setenv("RELEASE", "prod-v1")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("RATE_LIMIT_ALLOW_MEMORY", raising=False)
    import src.auth.rate_limit as rl

    with pytest.raises(RuntimeError, match="REDIS_URL"):
        rl._resolve_storage_uri()


def test_resolve_storage_uri_memory_off_switch(monkeypatch):
    """RATE_LIMIT_ALLOW_MEMORY=1 lets production opt into memory:// explicitly."""
    monkeypatch.setenv("RELEASE", "prod-v1")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("RATE_LIMIT_ALLOW_MEMORY", "1")
    import src.auth.rate_limit as rl

    assert rl._resolve_storage_uri() == "memory://"


def test_resolve_storage_uri_dev_defaults_memory(monkeypatch):
    """Dev/test (no RELEASE) keeps the memory:// convenience default."""
    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    import src.auth.rate_limit as rl

    assert rl._resolve_storage_uri() == "memory://"


def test_resolve_storage_uri_uses_real_redis(monkeypatch):
    """A real REDIS_URL is always used verbatim."""
    monkeypatch.setenv("RELEASE", "prod-v1")
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    import src.auth.rate_limit as rl

    assert rl._resolve_storage_uri() == "redis://cache:6379"
