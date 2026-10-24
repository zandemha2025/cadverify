"""Password recovery boundaries; no real email is sent."""
import asyncio
import os
import re
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from src.auth import password_reset as reset
from src.auth.hashing import hash_password, verify_password


class ResetRedis:
    def __init__(self):
        self.values = {}
        self.expiry = {}

    async def set(self, key, value, *, ex, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expiry[key] = ex
        return True

    async def getdel(self, key):
        return self.values.pop(key, None)

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def recovery(monkeypatch):
    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.delenv("PRODUCTION_AUTH_PROXY_REQUIRED", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_only")
    monkeypatch.setenv("RESEND_FROM", "ScaleCad <login@example.com>")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:16380")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://scalecad.example")
    monkeypatch.setattr(reset.limiter, "enabled", False)
    redis = ResetRedis()
    monkeypatch.setattr(reset, "_r", lambda: redis)
    monkeypatch.setattr(reset, "verify_turnstile", AsyncMock())
    credentials = AsyncMock(return_value=(42, hash_password("OldPassword123"), "analyst"))
    monkeypatch.setattr(reset, "get_login_credentials", credentials)
    monkeypatch.setattr(reset, "user_is_active", AsyncMock(return_value=True))
    monkeypatch.setattr(reset, "set_password_hash", AsyncMock(return_value=1))
    send = AsyncMock(return_value=httpx.Response(200, json={"id": "mail-1"}, request=httpx.Request("POST", "https://api.resend.com/emails")))
    monkeypatch.setattr(httpx.AsyncClient, "post", send)
    app = FastAPI()
    from src.api.errors import structured_validation_error_handler
    app.add_exception_handler(RequestValidationError, structured_validation_error_handler)
    app.include_router(reset.router, prefix="/auth")
    return TestClient(app, client=(f"reset-test-{uuid.uuid4().hex}", 50000)), redis, credentials, send


def start(client, email="owner@example.com"):
    return client.post("/auth/password/reset/start", json={"email": email, "turnstileToken": "test-captcha"})


def token_from(send):
    text = send.call_args.kwargs["json"]["text"]
    return re.search(r"/reset-password#token=([A-Za-z0-9_-]+)", text).group(1)


def complete(client, token, password="NewPassword456"):
    return client.post("/auth/password/reset/complete", json={"token": token, "password": password})


def test_reset_link_is_fragment_only_hashed_short_lived_and_single_use(recovery):
    client, redis, _, send = recovery
    response = start(client)
    assert response.status_code == 200
    token = token_from(send)
    assert len(token) == 43
    assert "?token=" not in send.call_args.kwargs["json"]["text"]
    assert all(token not in key and "owner@example.com" not in key for key in redis.values)
    key = reset._token_key(token)
    assert redis.expiry[key] == 900
    assert complete(client, token).json() == {"ok": True}
    reset.set_password_hash.assert_awaited_once()
    args = reset.set_password_hash.call_args
    assert args.args[0] == 42
    assert verify_password(args.args[1], "NewPassword456")
    assert args.kwargs["expected_hash"]
    assert complete(client, token).status_code == 400


@pytest.mark.parametrize("account", ["unknown", "sso", "inactive", "mail_failure"])
def test_start_does_not_disclose_account_state_or_delivery_failure(recovery, account):
    client, redis, credentials, send = recovery
    expected = start(client).json()
    redis.values.clear()
    send.reset_mock()
    if account == "unknown":
        credentials.return_value = None
    elif account == "sso":
        credentials.return_value = (42, None, "analyst")
    elif account == "inactive":
        reset.user_is_active.return_value = False
    else:
        send.side_effect = httpx.ConnectError("provider unavailable")
    response = start(client)
    assert response.status_code == 200
    assert response.json() == expected
    if account == "mail_failure":
        assert not any(key.startswith("password-reset:token:") for key in redis.values)
    if account != "mail_failure":
        send.assert_not_called()


def test_email_cooldown_has_same_response_and_does_not_resend(recovery):
    client, _, _, send = recovery
    first = start(client)
    second = start(client, " OWNER@EXAMPLE.COM ")
    assert first.json() == second.json()
    assert first.status_code == second.status_code == 200
    assert send.call_count == 1


def test_bad_password_does_not_burn_link_but_changed_credential_invalidates_it(recovery):
    client, _, credentials, send = recovery
    start(client)
    token = token_from(send)
    assert complete(client, token, "weak").status_code == 400
    credentials.return_value = (42, hash_password("OtherPassword123"), "analyst")
    assert complete(client, token).status_code == 400
    reset.set_password_hash.assert_not_awaited()


def test_expired_tampered_missing_and_deactivated_tokens_fail_closed(recovery):
    client, redis, _, send = recovery
    start(client)
    token = token_from(send)
    assert complete(client, "A" * 43).status_code == 400
    assert complete(client, "short").status_code == 422
    reset.user_is_active.return_value = False
    assert complete(client, token).status_code == 400
    reset.set_password_hash.assert_not_awaited()
    redis.values.clear()  # Redis TTL expiration removes the bearer proof.
    assert complete(client, token).status_code == 400


def test_concurrent_redemption_can_change_password_only_once(recovery):
    _, _, _, send = recovery
    from inspect import unwrap
    from starlette.requests import Request
    from starlette.responses import Response

    asyncio.run(reset._deliver_reset("owner@example.com"))
    token = token_from(send)

    async def redeem():
        request = Request({"type": "http", "method": "POST", "path": "/auth/password/reset/complete", "headers": []})
        handler = unwrap(reset.complete_password_reset)
        return await handler(reset.ResetCompleteIn(token=token, password="NewPassword456"), request, Response())

    async def both():
        return await asyncio.gather(redeem(), redeem(), return_exceptions=True)

    results = asyncio.run(both())
    assert sum(result == {"ok": True} for result in results) == 1
    reset.set_password_hash.assert_awaited_once()


def test_missing_config_captcha_and_proxy_fail_before_account_lookup(recovery, monkeypatch):
    client, _, credentials, send = recovery
    monkeypatch.delenv("RESEND_API_KEY")
    assert start(client).status_code == 503
    credentials.assert_not_awaited()
    send.assert_not_called()
    monkeypatch.setenv("RESEND_API_KEY", "re_test_only")
    from fastapi import HTTPException
    reset.verify_turnstile.side_effect = HTTPException(400, "captcha_failed")
    assert start(client).status_code == 400
    credentials.assert_not_awaited()
    monkeypatch.setenv("PRODUCTION_AUTH_PROXY_REQUIRED", "1")
    monkeypatch.delenv("AUTH_PROXY_SECRET", raising=False)
    assert start(client).status_code == 503
    credentials.assert_not_awaited()


def test_db_compare_and_set_rejection_never_reports_reset_success(recovery):
    client, _, _, send = recovery
    start(client)
    reset.set_password_hash.return_value = None
    assert complete(client, token_from(send)).status_code == 400


def test_reset_start_enforces_its_ip_limit(recovery, monkeypatch):
    from slowapi.errors import RateLimitExceeded
    from src.auth.rate_limit import rate_limit_handler

    client, _, _, _ = recovery
    client.app.state.limiter = reset.limiter
    client.app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    monkeypatch.setattr(reset.limiter, "enabled", True)
    for _ in range(5):
        assert start(client).status_code == 200
    assert start(client).status_code == 429


def test_recovery_respects_password_auth_policy(recovery, monkeypatch):
    client, _, credentials, _ = recovery
    monkeypatch.setenv("PASSWORD_LOGIN_ENABLED", "0")
    assert start(client).status_code == 404
    assert complete(client, "A" * 43).status_code == 404
    credentials.assert_not_awaited()


def test_validation_errors_never_reflect_passwords_or_reset_tokens(recovery):
    client, _, _, _ = recovery
    password = "PrivatePasswordSentinel123" * 8
    token = "ResetTokenSentinel" * 8
    response = complete(client, token, password)
    assert response.status_code == 422
    assert password not in response.text
    assert token not in response.text


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql") or not os.getenv("REDIS_URL"), reason="requires local Postgres and Redis")
@pytest.mark.asyncio
async def test_pg_reset_revokes_sessions_rejects_old_password_and_preserves_new_login(monkeypatch):
    from fastapi import Depends
    from sqlalchemy import text
    import src.db.engine as engine
    from src.auth.dashboard_session import require_dashboard_session
    from src.auth.password import router as password_router

    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.delenv("PRODUCTION_AUTH_PROXY_REQUIRED", raising=False)
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_only")
    monkeypatch.setenv("RESEND_FROM", "login@example.com")
    monkeypatch.setattr(reset.limiter, "enabled", False)
    monkeypatch.setattr(reset, "verify_turnstile", AsyncMock())
    send = AsyncMock(return_value=httpx.Response(200, request=httpx.Request("POST", "https://api.resend.com/emails")))
    monkeypatch.setattr(httpx.AsyncClient, "post", send)
    app = FastAPI()
    app.include_router(password_router, prefix="/auth")
    app.include_router(reset.router, prefix="/auth")

    @app.get("/protected")
    async def protected(user_id=Depends(require_dashboard_session)):
        return {"id": user_id}

    email = f"reset-{uuid.uuid4().hex}@example.com"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            created = await client.request("POST", "/auth/signup", json={"email": email, "password": "OldPassword123"})
            assert created.status_code == 200, created.text
            uid = created.json()["user"]["id"]
            old_cookie = {"Cookie": f"dash_session={created.json()['session']}"}
            assert (await client.get("/protected", headers=old_cookie)).status_code == 200
            requested = await client.request("POST", "/auth/password/reset/start", json={"email": email, "turnstileToken": "test"})
            assert requested.status_code == 200
            token = token_from(send)
            assert 0 < await reset._r().ttl(reset._token_key(token)) <= 900
            # A second, still-unexpired link cannot overwrite the reset later.
            await reset._deliver_reset(email)
            second_token = token_from(send)
            result = await client.request("POST", "/auth/password/reset/complete", json={"token": token, "password": "NéwPassword456"})
            assert result.status_code == 200, result.text
            assert result.json() == {"ok": True}
            assert await reset._r().get(reset._token_key(token)) is None
            assert "session" not in result.json()
            assert (await client.get("/protected", headers=old_cookie)).status_code == 401
            old_login = await client.request("POST", "/auth/login", json={"email": email, "password": "OldPassword123"})
            assert old_login.status_code == 401
            new_login = await client.request("POST", "/auth/login", json={"email": email, "password": "NéwPassword456"})
            assert new_login.status_code == 200
            new_cookie = {"Cookie": f"dash_session={new_login.json()['session']}"}
            assert (await client.get("/protected", headers=new_cookie)).status_code == 200
            for used in (token, second_token):
                rejected = await client.request("POST", "/auth/password/reset/complete", json={"token": used, "password": "AttackerPassword789"})
                assert rejected.status_code == 400
            assert (await client.get("/protected", headers=new_cookie)).status_code == 200
            async with engine.get_session_factory()() as session:
                events = (await session.execute(text("SELECT action FROM audit_log WHERE user_id = :u AND action = 'auth.password_changed'"), {"u": uid})).scalars().all()
                assert events == ["auth.password_changed"]
    finally:
        async with engine.get_session_factory()() as session:
            await session.execute(text("DELETE FROM users WHERE email_lower = :email"), {"email": email})
            await session.commit()
        await engine.dispose_engine()
