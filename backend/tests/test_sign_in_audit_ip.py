"""Sign-in audit rows say where the sign-in came from, and never carry secrets.

Two-step completions already record the client IP (the verified proxy IP, else
the direct peer) and the browser. Password, email-link and Google sign-ins now
do too, so Activity can answer "was that me?" for every way in. None of them
stores the password, the emailed token, the session or Google's tokens, and the
log scrubber still removes those. A user agent is stored as sent, through the
same scrubber, so a crafted one can't plant a credential in the audit trail.

Live Postgres and Redis (``REDIS_URL``); the real routes, with only Google's
token exchange and the outgoing email stubbed.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql") and bool(os.environ.get("REDIS_URL"))
_requires_pg = pytest.mark.skipif(not _PG, reason="requires Postgres and Redis (DATABASE_URL, REDIS_URL)")

SECRET = base64.b64encode(b"p" * 32).decode()
BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Safari/605.1.15"
OFFICE_IP = "203.0.113.7"


def _signed(method: str, path: str, ip: str = OFFICE_IP) -> dict[str, str]:
    """The headers the web app's auth proxy signs for ``ip`` (frontend/src/lib/auth-proxy.ts)."""
    from src.auth.client_ip import CLIENT_IP_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, _encoded_signature, signature_payload

    ts = str(int(time.time()))
    sig = _encoded_signature(signature_payload(ts, method, path, ip), base64.b64decode(SECRET))
    return {CLIENT_IP_HEADER: ip, TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: sig, "user-agent": BROWSER}


def _app(*routers):
    from fastapi import FastAPI

    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    for r in routers:
        app.include_router(r, prefix="/auth")
    return app


async def _client(app, peer=("198.51.100.23", 50123)):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app, client=peer), base_url="http://t")


async def _login_rows(email):
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        return (await s.execute(text(
            "SELECT a.ip_address, a.user_agent, a.detail_json::text, a.resource_type, a.resource_id, a.user_email "
            "FROM audit_log a JOIN users u ON u.id = a.user_id "
            "WHERE u.email_lower = :e AND a.action = 'auth.login' ORDER BY a.id"), {"e": email})).all()


async def _forget(email):
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        ids = [r[0] for r in (await s.execute(text("SELECT id FROM users WHERE email_lower = :e"), {"e": email})).all()]
        if ids:
            orgs = [r[0] for r in (await s.execute(text("SELECT org_id FROM memberships WHERE user_id = ANY(:u)"), {"u": ids})).all()]
            for stmt in ("DELETE FROM audit_log WHERE user_id = ANY(:u)", "DELETE FROM api_keys WHERE user_id = ANY(:u)",
                         "DELETE FROM memberships WHERE user_id = ANY(:u)", "UPDATE users SET current_org_id = NULL WHERE id = ANY(:u)"):
                await s.execute(text(stmt), {"u": ids})
            if orgs:
                await s.execute(text("DELETE FROM audit_log WHERE org_id = ANY(:o)"), {"o": orgs})
                await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": orgs})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": ids})
        await s.commit()
    await eng.dispose_engine()


@pytest.fixture
def proxy_secret(monkeypatch):
    monkeypatch.setenv("AUTH_PROXY_SECRET", SECRET)
    monkeypatch.setenv("PASSWORD_LOGIN_ENABLED", "1")


@_requires_pg
@pytest.mark.asyncio
async def test_a_password_sign_in_row_has_the_verified_ip_and_browser_and_no_password(proxy_secret):
    import src.db.engine as eng
    from src.auth.hashing import hash_password
    from src.auth.password import router as password_router

    email = f"sia-{uuid.uuid4().hex[:10]}@northfieldpumps.com"
    password = "Northfield-pw-2026"
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO users (email, email_lower, role, auth_provider, password_hash) "
                             "VALUES (:e, :e, 'analyst', 'password', :h)"), {"e": email, "h": hash_password(password)})
        await s.commit()
    try:
        async with await _client(_app(password_router)) as c:
            r = await c.post("/auth/login", json={"email": email, "password": password},
                             headers=_signed("POST", "/auth/login"))
        assert r.status_code == 200, r.text
        session = r.json()["session"]
        [(ip, ua, detail, *_rest)] = await _login_rows(email)
        assert (ip, ua) == (OFFICE_IP, BROWSER)
        row = repr(await _login_rows(email))
        assert password not in row and session not in row
    finally:
        await _forget(email)


@_requires_pg
@pytest.mark.asyncio
async def test_an_email_link_sign_in_row_has_the_verified_ip_and_browser_and_no_token(proxy_secret, monkeypatch):
    import src.auth.magic_link as m

    email = f"sia-{uuid.uuid4().hex[:10]}@northfieldpumps.com"
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "login@example.com")
    sent = {}

    def _send(payload):
        sent["text"] = payload["text"]
        return {"id": "email-1"}

    try:
        with patch.object(m, "verify_turnstile", AsyncMock()), patch.object(m.resend.Emails, "send", _send):
            async with await _client(_app(m.router)) as c:
                r = await c.post("/auth/magic/start", data={"email": email, "cf_turnstile_response": "ok"},
                                 headers=_signed("POST", "/auth/magic/start"))
                assert r.status_code == 200, r.text
                token = sent["text"].split("#token=")[1].split("&")[0].strip()
                r = await c.post("/auth/magic/exchange", json={"token": token},
                                 headers=_signed("POST", "/auth/magic/exchange"))
        assert r.status_code == 200, r.text
        rows = await _login_rows(email)
        assert len(rows) == 1
        ip, ua, detail, *_ = rows[0]
        assert (ip, ua) == (OFFICE_IP, BROWSER) and '"auth_provider": "magic_link"' in detail
        assert token not in repr(rows) and r.json()["session"] not in repr(rows)
    finally:
        await _forget(email)


@_requires_pg
@pytest.mark.asyncio
async def test_a_google_sign_in_writes_a_row_with_the_ip_and_browser_and_no_google_tokens():
    from src.auth.oauth import router as oauth_router

    email = f"sia-{uuid.uuid4().hex[:10]}@northfieldpumps.com"
    google = {"access_token": "ya29.secret-access", "id_token": "eyJ.secret-id", "refresh_token": "1//secret-refresh",
              "userinfo": {"email": email, "sub": f"g-{uuid.uuid4().hex[:8]}", "email_verified": True}}
    try:
        with patch("src.auth.oauth.oauth") as mock_oauth:
            mock_oauth.google.authorize_access_token = AsyncMock(return_value=google)
            # Google returns the browser to the API directly: the peer is the client.
            async with await _client(_app(oauth_router), peer=("198.51.100.23", 50123)) as c:
                r = await c.get("/auth/google/callback", headers={"user-agent": BROWSER})
        assert r.status_code == 303, r.text
        rows = await _login_rows(email)
        assert len(rows) == 1
        ip, ua, detail, *_ = rows[0]
        assert (ip, ua) == ("198.51.100.23", BROWSER) and '"auth_provider": "google"' in detail
        for secret in ("ya29.secret-access", "eyJ.secret-id", "1//secret-refresh", google["userinfo"]["sub"]):
            assert secret not in repr(rows)
    finally:
        await _forget(email)


def test_a_crafted_user_agent_cannot_plant_a_credential():
    from starlette.requests import Request

    from src.auth.client_ip import client_user_agent

    def req(ua):
        return Request({"type": "http", "headers": [(b"user-agent", ua.encode())] if ua is not None else []})

    assert client_user_agent(req(BROWSER)) == BROWSER
    assert client_user_agent(req("curl/8.5 Bearer leaked.jwt cv_live_abc_def ?token=abc")) == (
        "curl/8.5 Bearer ***REDACTED*** cv_live_***REDACTED*** ?token=***REDACTED***")
    assert len(client_user_agent(req("x" * 2000))) == 500
    assert client_user_agent(req(None)) is None


def test_the_log_scrubber_still_removes_sign_in_secrets_and_keeps_where_from():
    from src.auth.scrubbing import scrub_processor

    event = scrub_processor(None, None, {
        "event": "sign-in", "password": "Northfield-pw-2026", "token": "magic-secret", "session": "s.e.c",
        "cf_turnstile_response": "turnstile-secret", "access_token": "ya29.x", "id_token": "eyJ.x",
        "headers": {"cookie": "dash_session=abc", "authorization": "Bearer abc", "user-agent": BROWSER},
        "url": "https://app.example.com/magic/verify#token=magic-secret",
        "ip_address": OFFICE_IP, "user_agent": BROWSER,
    })
    for key in ("password", "token", "session", "cf_turnstile_response", "access_token", "id_token"):
        assert event[key] == "***REDACTED***"
    assert event["headers"]["cookie"] == event["headers"]["authorization"] == "***REDACTED***"
    assert "magic-secret" not in event["url"]
    assert (event["ip_address"], event["user_agent"], event["headers"]["user-agent"]) == (OFFICE_IP, BROWSER, BROWSER)
