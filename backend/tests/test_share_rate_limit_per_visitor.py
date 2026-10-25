"""A share link's view limit is per visitor, through the web server too.

Security review R4 (F3): the share pages render on the web server, so the API
sees the web server's address. The web server signs each visitor's IP
(``frontend/src/lib/auth-proxy.ts``); the limiter keys on that signed IP. Two
visitors therefore get two buckets on ``GET /s/cost/{id}`` (120 an hour each),
and a forged, unsigned client-IP header buys nobody a fresh bucket.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

SECRET = b"r4-share-rate-key-secret-32-bytes!!"
PATH = "/s/cost/AAAAAAAAAAAA"
LIMIT = 120  # @limiter.limit("120/hour") on get_shared_cost_decision


def _signed(ip: str, path: str = PATH, method: str = "GET") -> dict[str, str]:
    ts = str(int(time.time()))
    payload = f"{ts}\n{method}\n{path}\n{ip}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(SECRET, payload, hashlib.sha256).digest()).rstrip(b"=").decode()
    return {"x-cadverify-client-ip": ip, "x-cadverify-proxy-timestamp": ts, "x-cadverify-proxy-signature": sig}


@pytest.fixture
def client(monkeypatch):
    import src.api.cost_decisions as cd
    import src.auth.rate_limit as rl
    from src.db.engine import get_db_session

    monkeypatch.setenv("AUTH_PROXY_SECRET", base64.b64encode(SECRET).decode())
    # A private in-memory store: never the shared Redis, whatever REDIS_URL says.
    storage = MemoryStorage()
    monkeypatch.setattr(rl.limiter, "_storage", storage)
    monkeypatch.setattr(rl.limiter, "_limiter", FixedWindowRateLimiter(storage))
    monkeypatch.setattr(rl.limiter, "enabled", True)

    async def _shared(short_id, _session):
        return {"kind": "part", "label": "Bracket", "short_id": short_id}

    monkeypatch.setattr(cd.svc, "get_shared", _shared)
    app = FastAPI()
    app.state.limiter = rl.limiter
    app.add_exception_handler(RateLimitExceeded, rl.rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(cd.public_cost_share_router, prefix="/s")
    app.dependency_overrides[get_db_session] = lambda: None
    return TestClient(app)


def test_two_signed_visitors_get_separate_buckets_on_a_cost_share(client):
    first, second = "203.0.113.7", "198.51.100.23"
    for _ in range(LIMIT):
        assert client.get(PATH, headers=_signed(first)).status_code == 200
    spent = client.get(PATH, headers=_signed(first))
    assert spent.status_code == 429 and spent.headers.get("Retry-After")
    # The same web server, another visitor: a bucket of their own.
    assert client.get(PATH, headers=_signed(second)).status_code == 200


def test_an_unsigned_client_ip_header_does_not_buy_a_fresh_bucket(client):
    for _ in range(LIMIT):
        assert client.get(PATH, headers=_signed("203.0.113.7")).status_code == 200
    # Without a valid signature the header is ignored and the caller is the socket
    # peer; signing the wrong path is no better.
    forged = {"x-cadverify-client-ip": "192.0.2.99"}
    for _ in range(LIMIT):
        assert client.get(PATH, headers=forged).status_code == 200
    assert client.get(PATH, headers=forged).status_code == 429
    wrong_path = _signed("192.0.2.98", path="/s/cost/BBBBBBBBBBBB")
    assert client.get(PATH, headers=wrong_path).status_code == 429
