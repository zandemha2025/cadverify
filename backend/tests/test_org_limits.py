"""Tests for src.auth.org_limits (W-ORG-ISO): per-org resource isolation.

Mirrors the testing idiom used by test_auth_signup_limits.py (direct calls
against the dependency function + a fakeredis-backed ``_r()`` override) and
test_rate_limit.py (a lightweight fake Request carrying ``state.authed_user``)
rather than spinning up the full app -- these are unit tests of the guard
itself, isolated from auth/DB wiring.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth.require_api_key import AuthedUser


def _req(user_id: int, api_key_id: int = 1) -> SimpleNamespace:
    """A minimal fake Request carrying only what enforce_org_limits reads."""
    user = AuthedUser(user_id=user_id, api_key_id=api_key_id, key_prefix="test_pfx")
    return SimpleNamespace(state=SimpleNamespace(authed_user=user))


def _unauth_req() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


@pytest.fixture
def fake_redis(monkeypatch):
    import fakeredis.aioredis as far

    r = far.FakeRedis(decode_responses=True)
    monkeypatch.setattr("src.auth.org_limits._r", lambda: r)
    return r


@pytest.fixture
def org_membership(monkeypatch):
    """Map user_id -> (org_id, org_role) via a dict the test can mutate."""
    mapping: dict[int, tuple[str, str]] = {}

    async def _fake_lookup(user_id: int):
        return mapping.get(user_id)

    monkeypatch.setattr("src.auth.org_limits.lookup_org_membership", _fake_lookup)
    return mapping


@pytest.fixture
def under_quota(monkeypatch):
    """Keep the durable daily-analyses check out of the way by default."""

    async def _zero(org_id: str) -> int:
        return 0

    monkeypatch.setattr("src.auth.org_limits._daily_analyses_count", _zero)


# ---------------------------------------------------------------------------
# (a) Redis hourly ceiling -- flood + isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_flood_past_hour_ceiling_429_with_retry_after(
    fake_redis, org_membership, under_quota, monkeypatch
):
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_RATE_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_DAY", "20000")
    org_membership[1] = ("org_a", "member")

    # 5 requests are allowed (at the ceiling).
    for _ in range(5):
        await enforce_org_limits(_req(1))

    # The 6th trips the breaker.
    with pytest.raises(HTTPException) as exc:
        await enforce_org_limits(_req(1))

    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "org_rate_limited"
    assert "doc_url" in exc.value.detail
    retry_after = int(exc.value.headers["Retry-After"])
    assert retry_after > 0


@pytest.mark.asyncio
async def test_different_org_unaffected_in_same_window(
    fake_redis, org_membership, under_quota, monkeypatch
):
    """The isolation proof: org_a flooding past its ceiling must not touch org_b."""
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_RATE_LIMIT_PER_HOUR", "5")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_DAY", "20000")
    org_membership[1] = ("org_a", "member")
    org_membership[2] = ("org_b", "member")

    for _ in range(5):
        await enforce_org_limits(_req(1))
    with pytest.raises(HTTPException):
        await enforce_org_limits(_req(1))

    # org_b (a different user in a different org), same Redis window: untouched.
    for _ in range(5):
        await enforce_org_limits(_req(2))  # no raise


# ---------------------------------------------------------------------------
# Behavior preservation for normal (non-flooding) traffic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_traffic_under_ceiling_is_untouched(
    fake_redis, org_membership, under_quota, monkeypatch
):
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_RATE_LIMIT_PER_HOUR", "2000")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_DAY", "20000")
    org_membership[1] = ("org_a", "member")

    # A handful of ordinary requests: no exception, no return value (no-op).
    for _ in range(10):
        result = await enforce_org_limits(_req(1))
        assert result is None


@pytest.mark.asyncio
async def test_unauthenticated_request_is_noop(fake_redis, org_membership):
    from src.auth.org_limits import enforce_org_limits

    # No authed_user on request.state at all -- must not touch Redis/DB/lookup.
    assert await enforce_org_limits(_unauth_req()) is None


@pytest.mark.asyncio
async def test_no_org_membership_is_noop(fake_redis, org_membership, monkeypatch):
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_RATE_LIMIT_PER_HOUR", "0")  # would trip instantly if active
    # user_id=99 has no entry in org_membership -> lookup returns None.
    assert await enforce_org_limits(_req(99)) is None


# ---------------------------------------------------------------------------
# (b) Durable daily-analyses quota
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_analyses_quota_exceeded_429(fake_redis, org_membership, monkeypatch):
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_ANALYSES_PER_DAY", "5000")
    org_membership[1] = ("org_a", "member")

    async def _over(org_id: str) -> int:
        return 5000

    monkeypatch.setattr("src.auth.org_limits._daily_analyses_count", _over)

    with pytest.raises(HTTPException) as exc:
        await enforce_org_limits(_req(1))

    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "org_quota_exceeded"
    assert "5000" in exc.value.detail["message"]
    assert int(exc.value.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_daily_analyses_quota_under_is_unchanged(
    fake_redis, org_membership, under_quota, monkeypatch
):
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_ANALYSES_PER_DAY", "5000")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_HOUR", "2000")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_DAY", "20000")
    org_membership[1] = ("org_a", "member")

    assert await enforce_org_limits(_req(1)) is None


@pytest.mark.asyncio
async def test_daily_quota_db_error_fails_open(fake_redis, org_membership, monkeypatch):
    from src.auth.org_limits import enforce_org_limits

    org_membership[1] = ("org_a", "member")

    async def _boom(org_id: str) -> int:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("src.auth.org_limits._daily_analyses_count", _boom)

    # Must fail OPEN: no 429 despite the DB check erroring.
    assert await enforce_org_limits(_req(1)) is None


# ---------------------------------------------------------------------------
# Fail-open when Redis itself is unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_unavailable_fails_open(org_membership, under_quota, monkeypatch):
    """No fakeredis override + no REDIS_URL configured -> _r() raises inside the
    guard; enforce_org_limits must swallow it and proceed (no 429)."""
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.delenv("REDIS_URL", raising=False)
    org_membership[1] = ("org_a", "member")

    assert await enforce_org_limits(_req(1)) is None


@pytest.mark.asyncio
async def test_redis_error_mid_call_fails_open(org_membership, under_quota, monkeypatch):
    """Even a Redis instance that raises on incr() (mid-flight blip) fails open."""
    from src.auth.org_limits import enforce_org_limits

    class _BoomRedis:
        async def incr(self, key):
            raise ConnectionError("redis down")

    monkeypatch.setattr("src.auth.org_limits._r", lambda: _BoomRedis())
    org_membership[1] = ("org_a", "member")

    assert await enforce_org_limits(_req(1)) is None


# ---------------------------------------------------------------------------
# Kill-switch: ORG_RATE_LIMIT_DISABLED (dev/test only, mirrors RATE_LIMIT_DISABLED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_rate_limit_disabled_noops_in_dev(monkeypatch, org_membership):
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_RATE_LIMIT_DISABLED", "1")
    monkeypatch.delenv("RELEASE", raising=False)

    def _boom_lookup(*a, **kw):
        raise AssertionError("enforce_org_limits must no-op before resolving org")

    monkeypatch.setattr("src.auth.org_limits.lookup_org_membership", _boom_lookup)

    assert await enforce_org_limits(_req(1)) is None


@pytest.mark.asyncio
async def test_org_rate_limit_disabled_ignored_in_release(
    fake_redis, org_membership, under_quota, monkeypatch
):
    """Mirrors rate_limit._limiter_enabled: RELEASE set -> the dev bypass is
    ignored and the org ceiling stays enforced."""
    from src.auth.org_limits import enforce_org_limits

    monkeypatch.setenv("ORG_RATE_LIMIT_DISABLED", "1")
    monkeypatch.setenv("RELEASE", "prod-v1")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_HOUR", "1")
    monkeypatch.setenv("ORG_RATE_LIMIT_PER_DAY", "20000")
    org_membership[1] = ("org_a", "member")

    await enforce_org_limits(_req(1))
    with pytest.raises(HTTPException):
        await enforce_org_limits(_req(1))
