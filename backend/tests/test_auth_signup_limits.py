import pytest
from fastapi import HTTPException


@pytest.fixture
def fake_redis(monkeypatch):
    import fakeredis.aioredis as far

    r = far.FakeRedis(decode_responses=True)
    monkeypatch.setattr("src.auth.signup_limits._r", lambda: r)
    return r


class FakeReq:
    client = type("C", (), {"host": "1.1.1.1"})()


def test_ip_signup_limit_enabled_requires_redis(monkeypatch):
    from src.auth.signup_limits import ip_signup_limit_enabled

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("SIGNUP_RATE_LIMIT_DISABLED", raising=False)
    monkeypatch.delenv("RELEASE", raising=False)

    assert ip_signup_limit_enabled() is False


def test_ip_signup_limit_disabled_only_outside_release(monkeypatch):
    from src.auth.signup_limits import ip_signup_limit_enabled

    monkeypatch.setenv("REDIS_URL", "redis://cache:6379")
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_DISABLED", "1")
    monkeypatch.delenv("RELEASE", raising=False)
    assert ip_signup_limit_enabled() is False

    monkeypatch.setenv("RELEASE", "prod-v1")
    assert ip_signup_limit_enabled() is True


IP_KEY = "signup:ip:1.1.1.1"


@pytest.mark.asyncio
async def test_per_ip_allows_an_office_and_blocks_past_it(fake_redis, monkeypatch):
    from src.auth.signup_limits import per_ip_signup_limit

    monkeypatch.delenv("SIGNUPS_PER_IP_PER_HOUR", raising=False)
    for _ in range(60):
        await per_ip_signup_limit(FakeReq())
    with pytest.raises(HTTPException) as exc:
        await per_ip_signup_limit(FakeReq())
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "signup_rate_limited"


def test_the_ip_limit_is_office_sized_and_set_within_bounds(monkeypatch):
    from src.auth.signup_limits import ip_signup_limit

    monkeypatch.delenv("SIGNUPS_PER_IP_PER_HOUR", raising=False)
    assert ip_signup_limit() == (60, 3600)
    for raw, want in (("200", 200), ("3", 10), ("5000", 1000), ("lots", 60), ("", 60)):
        monkeypatch.setenv("SIGNUPS_PER_IP_PER_HOUR", raw)
        assert ip_signup_limit()[0] == want


@pytest.mark.asyncio
async def test_a_refused_attempt_counts_toward_nothing(fake_redis, monkeypatch):
    from src.auth.signup_limits import per_ip_signup_limit

    monkeypatch.setenv("SIGNUPS_PER_IP_PER_HOUR", "10")
    for _ in range(10):
        await per_ip_signup_limit(FakeReq())
    for _ in range(5):
        with pytest.raises(HTTPException):
            await per_ip_signup_limit(FakeReq())
    assert int(await fake_redis.get(IP_KEY)) == 10


@pytest.mark.asyncio
async def test_the_ip_refusal_gives_the_real_wait(fake_redis, monkeypatch):
    from src.auth.signup_limits import per_ip_signup_limit

    monkeypatch.setenv("SIGNUPS_PER_IP_PER_HOUR", "10")
    for _ in range(10):
        await per_ip_signup_limit(FakeReq())
    await fake_redis.expire(IP_KEY, 37 * 60 - 5)
    with pytest.raises(HTTPException) as exc:
        await per_ip_signup_limit(FakeReq())
    detail = exc.value.detail
    assert detail["message"] == "Too many sign-in and sign-up attempts from this network. Try again in 37 minutes."
    assert detail["limit"] == "ip" and detail["retry_after_seconds"] == 37 * 60 - 5
    assert exc.value.headers["Retry-After"] == str(37 * 60 - 5)


# ── the email-link route: an office behind one address, one email, refusals ──


def _magic_app():
    from fastapi import FastAPI

    from src.auth.magic_link import router

    app = FastAPI()
    app.include_router(router, prefix="/auth")
    return app


@pytest.fixture
def link_route(fake_redis, monkeypatch):
    """POST /auth/magic/start with Turnstile, the token store and the mail
    provider stubbed; the limits run for real on fakeredis."""
    from unittest.mock import AsyncMock, MagicMock

    import src.auth.magic_link as m

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "login@example.com")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.example.com")
    monkeypatch.setenv("MAGIC_LINK_RESEND_SECONDS", "60")
    monkeypatch.delenv("SIGNUPS_PER_IP_PER_HOUR", raising=False)
    monkeypatch.setattr(m, "ip_signup_limit_enabled", lambda: True)
    turnstile = AsyncMock()
    monkeypatch.setattr(m, "verify_turnstile", turnstile)
    monkeypatch.setattr(m, "get_soft_flag_set", AsyncMock(return_value=set()))
    monkeypatch.setattr(m, "_r", lambda: AsyncMock())
    monkeypatch.setattr(m, "_rotate_magic_token", AsyncMock())

    async def cleanup(_r, _active, _token, send_key):  # as the real one: the resend window goes
        await fake_redis.delete(send_key)

    monkeypatch.setattr(m, "_cleanup_failed_send", cleanup)
    send = MagicMock(return_value={"id": "email-1"})
    monkeypatch.setattr(m.resend.Emails, "send", send)
    from httpx import ASGITransport, AsyncClient

    app = _magic_app()

    async def post(email):
        async with AsyncClient(transport=ASGITransport(app=app, client=("10.0.0.7", 5000)), base_url="http://t") as c:
            return await c.post("/auth/magic/start", data={"email": email, "cf_turnstile_response": "ok"})

    return post, turnstile, send


@pytest.mark.asyncio
async def test_thirty_colleagues_behind_one_office_address_each_get_a_link(fake_redis, link_route):
    post, _turnstile, send = link_route
    for i in range(30):
        r = await post(f"person{i}@northfieldpumps.com")
        assert r.status_code == 200, (i, r.text)
    assert send.call_count == 30


@pytest.mark.asyncio
async def test_one_email_gets_five_links_an_hour_and_the_refusal_says_the_real_wait(fake_redis, link_route):
    from src.auth.magic_keys import magic_hourly_key, magic_send_key

    post, _turnstile, send = link_route
    email = "dana@northfieldpumps.com"
    for _ in range(5):
        assert (await post(email)).status_code == 200
        await fake_redis.delete(magic_send_key(email))  # the 60 s resend window has passed
    await fake_redis.expire(magic_hourly_key(email), 12 * 60 - 3)
    r = await post(email)
    assert r.status_code == 429, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "magic_link_limited" and detail["limit"] == "email"
    assert detail["message"] == "Too many sign-in links sent to this email. Try again in 12 minutes."
    assert detail["retry_after_seconds"] == 12 * 60 - 3 and r.headers["Retry-After"] == str(12 * 60 - 3)
    assert send.call_count == 5
    # The refused send gave its network slot back: only the five that went out count.
    assert int(await fake_redis.get("signup:ip:10.0.0.7")) == 5


@pytest.mark.asyncio
async def test_the_resend_window_says_the_real_wait_and_counts_toward_nothing(fake_redis, link_route):
    from src.auth.magic_keys import magic_send_key

    post, _turnstile, _send = link_route
    assert (await post("sam@northfieldpumps.com")).status_code == 200
    await fake_redis.expire(magic_send_key("sam@northfieldpumps.com"), 45)
    r = await post("sam@northfieldpumps.com")
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert detail["code"] == "magic_link_resend_limited"
    assert detail["message"] == "A sign-in link was just sent to this email. Try again in 45 seconds."
    assert int(await fake_redis.get("signup:ip:10.0.0.7")) == 1


@pytest.mark.asyncio
async def test_a_failed_security_check_or_mail_send_gives_the_slots_back(fake_redis, link_route):
    from fastapi import HTTPException as _H

    post, turnstile, send = link_route
    turnstile.side_effect = _H(400, detail={"code": "turnstile_failed", "message": "Security check failed."})
    assert (await post("pat@northfieldpumps.com")).status_code == 400
    assert int(await fake_redis.get("signup:ip:10.0.0.7") or 0) == 0
    turnstile.side_effect = None
    send.side_effect = RuntimeError("provider down")
    assert (await post("pat@northfieldpumps.com")).status_code == 503
    assert int(await fake_redis.get("signup:ip:10.0.0.7") or 0) == 0
    send.side_effect = None
    assert (await post("pat@northfieldpumps.com")).status_code == 200


@pytest.mark.asyncio
async def test_per_email_soft_flag_tighter_ttl(fake_redis):
    from src.auth.signup_limits import per_email_signup_limit

    await per_email_signup_limit("a@x.com", soft_flagged=True)
    ttl = await fake_redis.ttl("signup:email:a@x.com")
    assert 6 * 86400 < ttl <= 7 * 86400


@pytest.mark.asyncio
async def test_per_email_blocks_second_attempt(fake_redis):
    from src.auth.signup_limits import per_email_signup_limit

    await per_email_signup_limit("a@x.com", soft_flagged=False)
    with pytest.raises(HTTPException) as exc:
        await per_email_signup_limit("a@x.com", soft_flagged=False)
    assert exc.value.detail["code"] == "signup_email_limited"


@pytest.mark.asyncio
async def test_magic_link_resend_uses_short_separate_window(fake_redis, monkeypatch):
    from src.auth.magic_keys import magic_send_key
    from src.auth.signup_limits import per_email_magic_link_limit

    monkeypatch.setenv("MAGIC_LINK_RESEND_SECONDS", "60")
    await per_email_magic_link_limit("a@x.com", soft_flagged=False)

    ttl = await fake_redis.ttl(magic_send_key("a@x.com"))
    assert 0 < ttl <= 60
    assert await fake_redis.exists("signup:email:a@x.com") == 0

    with pytest.raises(HTTPException) as exc:
        await per_email_magic_link_limit("a@x.com", soft_flagged=False)
    assert exc.value.detail["code"] == "magic_link_resend_limited"
    assert exc.value.headers["Retry-After"]


@pytest.mark.asyncio
async def test_magic_link_soft_domain_window_is_minutes_not_days(
    fake_redis, monkeypatch
):
    from src.auth.magic_keys import magic_send_key
    from src.auth.signup_limits import per_email_magic_link_limit

    monkeypatch.setenv("MAGIC_LINK_RESEND_SECONDS", "60")
    await per_email_magic_link_limit("a@soft.example", soft_flagged=True)
    ttl = await fake_redis.ttl(magic_send_key("a@soft.example"))
    assert 240 < ttl <= 300
