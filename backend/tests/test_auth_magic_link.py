import base64
import os
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def setup_module(module):
    os.environ.setdefault("MAGIC_LINK_SECRET", base64.b64encode(b"x" * 32).decode())


def test_roundtrip():
    from src.auth.magic_link import _mint, _verify
    t = _mint("alice@example.com")
    assert _verify(t) == "alice@example.com"


def test_tampered_signature():
    from src.auth.magic_link import _mint, _verify
    t = _mint("alice@example.com")
    tampered = t[:-1] + ("a" if t[-1] != "a" else "b")
    assert _verify(tampered) is None


def test_expired(monkeypatch):
    import src.auth.magic_link as m
    t = m._mint("alice@example.com")
    real_time = m.time.time()
    monkeypatch.setattr(m.time, "time", lambda: real_time + 16 * 60)
    assert m._verify(t) is None


def test_garbage_token_returns_none():
    from src.auth.magic_link import _verify
    assert _verify("not-a-token") is None
    assert _verify("") is None


def _app():
    from src.auth.magic_link import router

    app = FastAPI()
    app.include_router(router, prefix="/auth")
    return app


def test_magic_start_emails_fragment_link_without_blocking_event_loop(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "login@example.com")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.example.com")
    fake_redis = AsyncMock()
    fake_redis.setex = AsyncMock()

    with patch("src.auth.magic_link.ip_signup_limit_enabled", return_value=False), patch(
        "src.auth.magic_link.verify_turnstile", new_callable=AsyncMock
    ), patch(
        "src.auth.magic_link.get_soft_flag_set",
        new_callable=AsyncMock,
        return_value=set(),
    ), patch(
        "src.auth.magic_link.per_email_signup_limit", new_callable=AsyncMock
    ), patch(
        "src.auth.magic_link._r", return_value=fake_redis
    ), patch(
        "src.auth.magic_link.resend.Emails.send", return_value={"id": "email-1"}
    ) as send:
        response = TestClient(_app()).post(
            "/auth/magic/start",
            data={"email": "alice@example.com", "cf_turnstile_response": "ok"},
        )

    assert response.status_code == 200
    payload = send.call_args.args[0]
    assert "https://app.example.com/magic/verify#token=" in payload["html"]
    assert "/magic/verify?token=" not in payload["html"]
    assert "alice@example.com" not in payload["html"]


def test_magic_exchange_returns_no_store_server_session(monkeypatch):
    from src.auth.magic_link import MagicLogin

    monkeypatch.setenv(
        "DASHBOARD_SESSION_SECRET", base64.b64encode(b"s" * 32).decode()
    )
    monkeypatch.delenv("PRODUCTION_AUTH_PROXY_REQUIRED", raising=False)
    result = MagicLogin(
        user_id=7,
        session_version=2,
        redirect="/settings/developer?new=1&prefix=cv_live_test",
        key_prefix="cv_live_test",
        mint_once="cv_live_secret",
    )
    with patch(
        "src.auth.magic_link._consume", new_callable=AsyncMock, return_value=result
    ):
        response = TestClient(_app()).post(
            "/auth/magic/exchange", json={"token": "x" * 64}
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["session"]
    assert body["mint_once"] == "cv_live_secret"
    assert body["key_prefix"] == "cv_live_test"


def test_production_magic_exchange_rejects_unsigned_direct_callers(monkeypatch):
    monkeypatch.setenv("PRODUCTION_AUTH_PROXY_REQUIRED", "1")
    monkeypatch.delenv("AUTH_PROXY_SECRET", raising=False)
    with patch("src.auth.magic_link._consume", new_callable=AsyncMock) as consume:
        response = TestClient(_app()).post(
            "/auth/magic/exchange", json={"token": "x" * 64}
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "auth_proxy_unavailable"
    consume.assert_not_awaited()


def test_legacy_magic_query_redirects_to_first_party_fragment_in_production(
    monkeypatch,
):
    monkeypatch.setenv("PRODUCTION_AUTH_PROXY_REQUIRED", "1")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.example.com")
    token = "x" * 64
    with patch("src.auth.magic_link._consume", new_callable=AsyncMock) as consume:
        response = TestClient(_app(), follow_redirects=False).get(
            "/auth/magic/verify", params={"token": token}
        )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"https://app.example.com/magic/verify#token={token}"
    )
    consume.assert_not_awaited()
