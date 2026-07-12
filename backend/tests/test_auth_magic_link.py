import asyncio
import base64
import os
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request


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


def test_magic_redis_keys_share_cluster_slot_without_email_pii():
    from src.auth.magic_keys import (
        magic_active_key,
        magic_generation_key,
        magic_send_key,
        magic_token_key,
    )

    email = "alice@example.com"
    keys = (
        magic_active_key(email),
        magic_generation_key(email),
        magic_send_key(email),
        magic_token_key(email, "secret-token"),
    )
    slots = {key.split("{", 1)[1].split("}", 1)[0] for key in keys}

    assert len(slots) == 1
    assert all(email not in key for key in keys)
    assert all("secret-token" not in key for key in keys)


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
    fake_redis.get = AsyncMock(return_value=None)

    with patch("src.auth.magic_link.ip_signup_limit_enabled", return_value=False), patch(
        "src.auth.magic_link.verify_turnstile", new_callable=AsyncMock
    ), patch(
        "src.auth.magic_link.get_soft_flag_set",
        new_callable=AsyncMock,
        return_value=set(),
    ), patch(
        "src.auth.magic_link.per_email_magic_link_limit", new_callable=AsyncMock
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


class _AtomicMagicRedis:
    """Small semantic fake for the Lua state transitions used by auth."""

    def __init__(self):
        self.state: dict[str, str] = {}

    async def eval(self, script, numkeys, *values):
        import src.auth.magic_link as m

        keys = values[:numkeys]
        args = values[numkeys:]
        if script == m._ROTATE_MAGIC_TOKEN_LUA:
            active_key, token_key, generation_key = keys
            generation = int(self.state.get(generation_key, "0")) + 1
            self.state[generation_key] = str(generation)
            previous = self.state.get(active_key)
            if previous and previous != token_key:
                self.state.pop(previous, None)
            self.state[token_key] = str(generation)
            self.state[active_key] = token_key
            return generation
        if script == m._CLEANUP_FAILED_SEND_LUA:
            active_key, token_key, send_key = keys
            current = self.state.get(active_key)
            self.state.pop(token_key, None)
            if current == token_key:
                self.state.pop(active_key, None)
                self.state.pop(send_key, None)
                return 1
            return 0
        if script == m._CLEAR_ACTIVE_POINTER_LUA:
            active_key, token_key = keys
            if self.state.get(active_key) == token_key:
                self.state.pop(active_key, None)
                return 1
            return 0
        if script == m._RESTORE_CONSUMED_TOKEN_LUA:
            active_key, token_key, generation_key = keys
            if self.state.get(generation_key) != str(args[0]):
                return 0
            current = self.state.get(active_key)
            if current and current != token_key:
                return 0
            self.state.setdefault(token_key, str(args[0]))
            self.state[active_key] = token_key
            return 1
        raise AssertionError("unknown magic-link Lua script")

    async def ttl(self, key):
        return 900 if key in self.state else -2

    async def getdel(self, key):
        return self.state.pop(key, None)

    async def get(self, key):
        return self.state.get(key)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/auth/magic/start",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
            "scheme": "https",
        }
    )


@pytest.mark.asyncio
async def test_delayed_failed_send_cannot_delete_newer_magic_link(monkeypatch):
    """A slow first Resend failure must not revoke the later successful link."""
    import src.auth.magic_link as m
    from src.auth.magic_keys import magic_send_key

    email = "alice@example.com"
    redis = _AtomicMagicRedis()
    tokens = iter(("first-token", "second-token"))
    first_send_started = asyncio.Event()
    release_first_send = asyncio.Event()
    limiter_calls = 0
    send_calls = 0

    async def fake_limit(email_norm, *, soft_flagged):
        nonlocal limiter_calls
        assert email_norm == email
        assert soft_flagged is False
        limiter_calls += 1
        # Model the first window expiring while its provider call is delayed,
        # then the second request owning a fresh resend window.
        redis.state[magic_send_key(email_norm)] = f"window-{limiter_calls}"

    async def fake_to_thread(_func, _payload):
        nonlocal send_calls
        send_calls += 1
        if send_calls == 1:
            first_send_started.set()
            await release_first_send.wait()
            raise RuntimeError("delayed provider failure")
        return {"id": "newer-email"}

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "login@example.com")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.example.com")
    monkeypatch.setattr(m, "ip_signup_limit_enabled", lambda: False)
    monkeypatch.setattr(m, "verify_turnstile", AsyncMock())
    monkeypatch.setattr(m, "get_soft_flag_set", AsyncMock(return_value=set()))
    monkeypatch.setattr(m, "per_email_magic_link_limit", fake_limit)
    monkeypatch.setattr(m, "_r", lambda: redis)
    monkeypatch.setattr(m, "_mint", lambda _email: next(tokens))
    monkeypatch.setattr(m.asyncio, "to_thread", fake_to_thread)

    first = asyncio.create_task(
        m.magic_start(
            _request(), email=email, cf_turnstile_response="ok"
        )
    )
    await first_send_started.wait()

    second = await m.magic_start(
        _request(), email=email, cf_turnstile_response="ok"
    )
    assert second == {"status": "sent"}

    release_first_send.set()
    with pytest.raises(HTTPException) as exc_info:
        await first
    assert exc_info.value.detail["code"] == "email_delivery_unavailable"

    first_key = m._token_key("first-token", email)
    second_key = m._token_key("second-token", email)
    active_key = m._active_token_key(email)
    assert first_key not in redis.state
    assert redis.state[second_key] == "2"
    assert redis.state[active_key] == second_key
    assert redis.state[magic_send_key(email)] == "window-2"


@pytest.mark.asyncio
async def test_old_db_failure_cannot_resurrect_after_newer_link_is_consumed(
    monkeypatch,
):
    """Generation survives pointer deletion and blocks stale-token restore."""
    import src.auth.magic_link as m
    from src.auth.magic_keys import magic_generation_key

    email = "alice@example.com"
    redis = _AtomicMagicRedis()
    first_token = m._mint(email)
    second_token = m._mint(email)
    first_key = m._token_key(first_token, email)
    second_key = m._token_key(second_token, email)
    active_key = m._active_token_key(email)
    generation_key = magic_generation_key(email)
    first_provisioning = asyncio.Event()
    release_first = asyncio.Event()
    provision_calls = 0

    async def fake_provision(**_kwargs):
        nonlocal provision_calls
        provision_calls += 1
        if provision_calls == 1:
            first_provisioning.set()
            await release_first.wait()
            raise RuntimeError("transient database failure")
        return SimpleNamespace(
            user_id=22,
            session_version=1,
            key_token=None,
            key_prefix=None,
        )

    first_generation = await m._rotate_magic_token(
        redis, active_key, first_key, generation_key
    )
    assert first_generation == 1
    monkeypatch.setattr(m, "_r", lambda: redis)
    monkeypatch.setattr(m, "provision_authenticated_login", fake_provision)

    first = asyncio.create_task(m._consume(first_token))
    await first_provisioning.wait()

    second_generation = await m._rotate_magic_token(
        redis, active_key, second_key, generation_key
    )
    assert second_generation == 2
    second = await m._consume(second_token)
    assert second.user_id == 22
    assert active_key not in redis.state
    assert redis.state[generation_key] == "2"

    release_first.set()
    with pytest.raises(RuntimeError, match="transient database failure"):
        await first

    assert first_key not in redis.state
    assert second_key not in redis.state
    assert active_key not in redis.state
    assert redis.state[generation_key] == "2"


@pytest.mark.asyncio
async def test_consume_provisions_each_verified_email_not_redis_generation(
    monkeypatch,
):
    """Two first-generation tokens must remain two distinct account emails."""
    import src.auth.magic_link as m
    from src.auth.magic_keys import magic_generation_key

    redis = _AtomicMagicRedis()
    provisioned_emails: list[str] = []

    async def fake_provision(**kwargs):
        email = kwargs["email"]
        provisioned_emails.append(email)
        return SimpleNamespace(
            user_id=101 if email == "alice@example.com" else 202,
            session_version=1,
            key_token=None,
            key_prefix=None,
        )

    monkeypatch.setattr(m, "_r", lambda: redis)
    monkeypatch.setattr(m, "provision_authenticated_login", fake_provision)

    results = []
    for email in ("alice@example.com", "bob@example.com"):
        token = m._mint(email)
        token_key = m._token_key(token, email)
        active_key = m._active_token_key(email)
        generation_key = magic_generation_key(email)
        generation = await m._rotate_magic_token(
            redis, active_key, token_key, generation_key
        )
        assert generation == 1
        results.append(await m._consume(token))

    assert provisioned_emails == ["alice@example.com", "bob@example.com"]
    assert [result.user_id for result in results] == [101, 202]

@pytest.mark.asyncio
async def test_magic_link_lua_cas_runs_atomically_on_redis7():
    """Execute the shipped Lua, not just the semantic fake, on CI's Redis 7."""
    import src.auth.magic_link as m
    from src.auth.magic_keys import magic_generation_key, magic_send_key

    unique = secrets.token_hex(8)
    email = f"lua-{unique}@example.com"
    first_key = m._token_key(f"first-{unique}", email)
    second_key = m._token_key(f"second-{unique}", email)
    active_key = m._active_token_key(email)
    generation_key = magic_generation_key(email)
    send_key = magic_send_key(email)
    client = aioredis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )
    try:
        await client.set(send_key, "newer-window", ex=60)
        first_generation = await m._rotate_magic_token(
            client, active_key, first_key, generation_key
        )
        second_generation = await m._rotate_magic_token(
            client, active_key, second_key, generation_key
        )
        await m._cleanup_failed_send(client, active_key, first_key, send_key)

        assert await client.get(first_key) is None
        assert await client.get(second_key) == str(second_generation)
        assert await client.get(active_key) == second_key
        assert await client.get(send_key) == "newer-window"

        await m._restore_consumed_token(
            client,
            active_key,
            first_key,
            generation_key,
            first_generation,
            60,
        )
        assert await client.get(first_key) is None
        assert await client.get(active_key) == second_key
    finally:
        await client.delete(
            active_key, first_key, second_key, generation_key, send_key
        )
        await client.aclose()


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
