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


@pytest.mark.asyncio
async def test_per_ip_allows_3(fake_redis):
    from src.auth.signup_limits import per_ip_signup_limit

    for _ in range(3):
        await per_ip_signup_limit(FakeReq())


@pytest.mark.asyncio
async def test_per_ip_blocks_4th(fake_redis):
    from src.auth.signup_limits import per_ip_signup_limit

    for _ in range(3):
        await per_ip_signup_limit(FakeReq())
    with pytest.raises(HTTPException) as exc:
        await per_ip_signup_limit(FakeReq())
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "signup_rate_limited"


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
