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
