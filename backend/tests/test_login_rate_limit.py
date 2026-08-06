"""Per-IP brute-force throttle on POST /auth/login (security hardening).

Login had no rate limit while every catalog/cost route did — a pen-tester's
first finding. This proves the ``@limiter.limit("10/minute;100/hour")`` on the
login route actually rejects a burst of guesses from one IP with a 429, while
staying off the DB (credentials lookup is monkeypatched to the invalid path).

The real router is mounted as-is (NOT reloaded): reloading the module would
re-run the ``@limiter.limit`` decorator and register the limit a second time,
double-counting requests. Instead we flip the shared limiter's ``enabled`` flag
on (tests otherwise disable it) and reset its process-global memory store.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware


@pytest.fixture
def login_client(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "memory://")

    import src.auth.password as pw
    import src.auth.rate_limit as rl

    # Enable the shared limiter for this test and reset the "memory://" store
    # (a singleton in the `limits` lib, so counts otherwise bleed across tests).
    monkeypatch.setattr(rl.limiter, "enabled", True)
    rl.limiter.reset()

    # Every attempt takes the invalid-credentials path — no DB, clean 401 — so
    # the test measures the throttle, not the login logic.
    async def _no_creds(_email_norm):
        return None

    monkeypatch.setattr(pw, "get_login_credentials", _no_creds)

    app = FastAPI()
    app.state.limiter = rl.limiter
    app.add_exception_handler(RateLimitExceeded, rl.rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(pw.router, prefix="/auth")
    try:
        yield TestClient(app)
    finally:
        rl.limiter.reset()


def _attempt(client):
    return client.post(
        "/auth/login", json={"email": "attacker@example.com", "password": "x"}
    )


def test_login_allows_burst_up_to_the_minute_limit(login_client):
    # The first 10 attempts/minute are the invalid-credentials 401, NOT 429 —
    # a human fumbling a password keeps ample headroom.
    for _ in range(10):
        assert _attempt(login_client).status_code == 401


def test_login_throttles_the_eleventh_attempt(login_client):
    for _ in range(10):
        _attempt(login_client)
    r = _attempt(login_client)
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"
    assert r.headers.get("Retry-After")
