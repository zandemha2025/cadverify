"""Tests for src.auth.validation_caps: hard 100-validations product caps.

Same idiom as test_org_limits.py: direct dependency calls with a fake Request
carrying ``state.authed_user`` plus monkeypatched membership/count lookups --
unit tests of the guard, isolated from auth/DB wiring.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth.require_api_key import AuthedUser
from src.auth import validation_caps as vc


def _req(user_id: int) -> SimpleNamespace:
    user = AuthedUser(user_id=user_id, api_key_id=1, key_prefix="test_pfx")
    return SimpleNamespace(state=SimpleNamespace(authed_user=user))


def _unauth_req() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


@pytest.fixture
def membership(monkeypatch):
    mapping: dict[int, tuple[str, str]] = {}

    async def _fake(user_id: int):
        return mapping.get(user_id)

    monkeypatch.setattr(vc, "lookup_org_membership", _fake)
    return mapping


@pytest.fixture
def counts(monkeypatch):
    """Map (dimension, key) -> row count; the test sets both explicitly."""
    table: dict[tuple, int] = {}

    async def _fake_count(column, key, since):
        return table.get((str(column), key), 0)

    monkeypatch.setattr(vc, "_count", _fake_count)
    return table


@pytest.fixture
def plans(monkeypatch):
    """Map user_id -> plan; absent means 'trial' (the safe default)."""
    table: dict[int, str] = {}

    async def _fake(user_id: int):
        return table.get(user_id, "trial")

    monkeypatch.setattr(vc, "_user_plan", _fake)
    return table


@pytest.fixture(autouse=True)
def _caps_on(monkeypatch):
    monkeypatch.delenv("VALIDATION_CAPS_DISABLED", raising=False)
    monkeypatch.delenv("RELEASE", raising=False)
    monkeypatch.setenv("VALIDATION_CAP_PER_ORG", "100")
    monkeypatch.setenv("VALIDATION_CAP_PER_USER", "100")
    monkeypatch.setenv("VALIDATION_CAP_WINDOW_DAYS", "0")


@pytest.mark.asyncio
async def test_under_both_caps_passes(membership, counts, plans):
    membership[7] = ("org-a", "admin")
    counts[("Analysis.org_id", "org-a")] = 99
    counts[("Analysis.user_id", 7)] = 99
    await vc.enforce_validation_caps(_req(7))  # no raise


@pytest.mark.asyncio
async def test_org_at_cap_rejects(membership, counts, plans):
    membership[7] = ("org-a", "admin")
    counts[("Analysis.org_id", "org-a")] = 100
    counts[("Analysis.user_id", 7)] = 3
    with pytest.raises(HTTPException) as ei:
        await vc.enforce_validation_caps(_req(7))
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "org_validation_cap_exceeded"
    assert "100" in ei.value.detail["message"]
    # Lifetime cap: no Retry-After (nothing to wait for).
    assert not ei.value.headers


@pytest.mark.asyncio
async def test_user_at_cap_rejects_even_when_org_under(membership, counts, plans):
    membership[7] = ("org-a", "admin")
    counts[("Analysis.org_id", "org-a")] = 50
    counts[("Analysis.user_id", 7)] = 100
    with pytest.raises(HTTPException) as ei:
        await vc.enforce_validation_caps(_req(7))
    assert ei.value.status_code == 403
    assert ei.value.detail["code"] == "user_validation_cap_exceeded"
    assert ei.value.detail["used"] == 100
    assert ei.value.detail["cap"] == 100
    assert ei.value.detail["remaining"] == 0
    assert ei.value.detail["plan"] == "trial"


@pytest.mark.asyncio
async def test_windowed_cap_carries_retry_after(membership, counts, plans, monkeypatch):
    monkeypatch.setenv("VALIDATION_CAP_WINDOW_DAYS", "30")
    membership[7] = ("org-a", "admin")
    counts[("Analysis.org_id", "org-a")] = 100
    counts[("Analysis.user_id", 7)] = 0
    with pytest.raises(HTTPException) as ei:
        await vc.enforce_validation_caps(_req(7))
    assert ei.value.headers["Retry-After"] == str(30 * 86400)


@pytest.mark.asyncio
async def test_unauthenticated_noop(membership):
    await vc.enforce_validation_caps(_unauth_req())


@pytest.mark.asyncio
async def test_no_membership_fails_open(membership, counts):
    counts[("Analysis.user_id", 7)] = 10_000
    await vc.enforce_validation_caps(_req(7))  # no org -> guard no-ops


@pytest.mark.asyncio
async def test_count_error_fails_open(membership, plans, monkeypatch):
    membership[7] = ("org-a", "admin")

    async def _boom(column, key, since):
        raise RuntimeError("db down")

    monkeypatch.setattr(vc, "_count", _boom)
    await vc.enforce_validation_caps(_req(7))


@pytest.mark.asyncio
async def test_kill_switch_dev_only(membership, counts, plans, monkeypatch):
    membership[7] = ("org-a", "admin")
    counts[("Analysis.org_id", "org-a")] = 10_000
    monkeypatch.setenv("VALIDATION_CAPS_DISABLED", "1")
    await vc.enforce_validation_caps(_req(7))  # disabled outside RELEASE
    monkeypatch.setenv("RELEASE", "1.2.3")
    with pytest.raises(HTTPException):  # ignored in production
        await vc.enforce_validation_caps(_req(7))


@pytest.mark.asyncio
async def test_pilot_plan_is_never_trial_gated(membership, counts, plans):
    membership[1] = ("org-owner", "admin")
    plans[1] = "pilot"
    counts[("Analysis.org_id", "org-owner")] = 10_000
    counts[("Analysis.user_id", 1)] = 10_000
    await vc.enforce_validation_caps(_req(1))  # unlimited, no raise


@pytest.mark.asyncio
async def test_user_trial_usage_reports_used_cap_remaining(counts, plans):
    counts[("Analysis.user_id", 7)] = 3
    out = await vc.user_trial_usage(7)
    assert out == {
        "plan": "trial",
        "unlimited": False,
        "used": 3,
        "cap": 100,
        "remaining": 97,
        "window_days": 0,
    }


@pytest.mark.asyncio
async def test_user_trial_usage_pilot_is_unlimited(counts, plans):
    plans[1] = "pilot"
    out = await vc.user_trial_usage(1)
    assert out == {
        "plan": "pilot",
        "unlimited": True,
        "used": None,
        "cap": None,
        "remaining": None,
    }
