"""Tests for src.api.admission (F-CAP-1): per-process admission control with
per-org fairness, guarding against the DB-pool-exhaustion 500s a burst of
concurrent ``/validate`` requests used to cause.

Mirrors the testing idiom of test_org_limits.py: a lightweight fake Request
carrying only ``state.authed_user``, plus direct calls against the
dependency/state-machine rather than spinning up the full app.

``admit_analysis`` is an async-generator FastAPI dependency (same shape as
``src.db.engine.get_db_session``): acquire happens before ``yield``, release
happens in a ``finally`` after. To drive it directly in tests we open/close
the generator manually:
  - ``gen = admit_analysis(request)``
  - open (acquire):  ``await gen.__anext__()``
  - close (release):  ``await gen.__anext__()`` again -> the generator resumes
    past ``yield``, runs its ``finally``, and then raises
    ``StopAsyncIteration`` (normal generator exhaustion) -- caught below.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.auth.require_api_key import AuthedUser


def _req(user_id: int, api_key_id: int = 1) -> SimpleNamespace:
    """A minimal fake Request carrying only what admit_analysis reads."""
    user = AuthedUser(user_id=user_id, api_key_id=api_key_id, key_prefix="test_pfx")
    return SimpleNamespace(state=SimpleNamespace(authed_user=user))


def _unauth_req() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


async def _acquire(request):
    """Open the admission generator: run it up to (and including) ``yield``.

    Returns the live generator so the caller can release it later. Raises
    whatever HTTPException the acquire step raises (ceiling hit).
    """
    from src.api.admission import admit_analysis

    gen = admit_analysis(request)
    await gen.__anext__()
    return gen


async def _release(gen) -> None:
    """Resume past ``yield`` so the dependency's ``finally`` (release) runs."""
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass


@pytest.fixture
def org_membership(monkeypatch):
    """Map user_id -> (org_id, org_role), same convention as test_org_limits.py."""
    mapping: dict[int, tuple[str, str]] = {}

    async def _fake_lookup(user_id: int):
        return mapping.get(user_id)

    monkeypatch.setattr("src.api.admission.lookup_org_membership", _fake_lookup)
    return mapping


# ---------------------------------------------------------------------------
# Global cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_cap_third_request_gets_429_server_busy(
    org_membership, monkeypatch
):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "10")
    org_membership[1] = ("org_a", "member")
    org_membership[2] = ("org_a", "member")
    org_membership[3] = ("org_a", "member")

    gen1 = await _acquire(_req(1))
    gen2 = await _acquire(_req(2))

    with pytest.raises(HTTPException) as exc:
        await _acquire(_req(3))

    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "server_busy"
    assert "doc_url" in exc.value.detail
    assert int(exc.value.headers["Retry-After"]) > 0

    # Freeing one slot admits the next caller.
    await _release(gen1)
    gen3 = await _acquire(_req(3))
    await _release(gen2)
    await _release(gen3)


@pytest.mark.asyncio
async def test_global_cap_state_machine_directly(org_membership, monkeypatch):
    """Unit-test the acquire/release state machine itself: acquire N slots,
    the N+1th raises 429, releasing one frees a slot for the next caller."""
    from src.api.admission import _acquire, _release, _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "10")

    state = _state()
    _acquire(state, "org_a")
    _acquire(state, "org_b")
    assert state.global_count == 2

    with pytest.raises(HTTPException) as exc:
        _acquire(state, "org_c")
    assert exc.value.detail["code"] == "server_busy"
    assert state.global_count == 2  # rejected acquire must not mutate counters

    _release(state, "org_a")
    assert state.global_count == 1
    _acquire(state, "org_c")  # now admitted
    assert state.global_count == 2

    _release(state, "org_b")
    _release(state, "org_c")
    assert state.global_count == 0
    assert state.per_org == {}


# ---------------------------------------------------------------------------
# Per-org fairness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_org_fairness_one_org_cannot_starve_another(
    org_membership, monkeypatch
):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "10")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "2")
    org_membership[1] = ("org_a", "member")
    org_membership[2] = ("org_a", "member")
    org_membership[3] = ("org_a", "member")
    org_membership[10] = ("org_b", "member")

    gen_a1 = await _acquire(_req(1))
    gen_a2 = await _acquire(_req(2))

    # org_a's 3rd concurrent request trips its own ceiling.
    with pytest.raises(HTTPException) as exc:
        await _acquire(_req(3))
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "org_at_capacity"
    assert "2" in exc.value.detail["message"]
    assert int(exc.value.headers["Retry-After"]) > 0

    # org_b is unaffected -- proves org_a can't starve the platform's global
    # capacity for other orgs even though the global cap (10) has plenty of
    # headroom left.
    gen_b1 = await _acquire(_req(10))

    await _release(gen_a1)
    await _release(gen_a2)
    await _release(gen_b1)


# ---------------------------------------------------------------------------
# Release semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_on_success_frees_slot(org_membership, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "1")
    org_membership[1] = ("org_a", "member")

    from src.api.admission import _state

    gen = await _acquire(_req(1))
    await _release(gen)

    state = _state()
    assert state.global_count == 0
    assert state.per_org == {}


@pytest.mark.asyncio
async def test_release_on_exception_frees_slot_no_leak(org_membership, monkeypatch):
    """Even when the handler body raises, the dependency's ``finally`` must
    still free the slot -- no leaked in-flight count from a failed analysis."""
    from src.api.admission import admit_analysis, _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "1")
    org_membership[1] = ("org_a", "member")

    gen = admit_analysis(_req(1))
    await gen.__anext__()  # acquire

    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("simulated handler failure"))

    state = _state()
    assert state.global_count == 0
    assert state.per_org == {}

    # And the slot is genuinely usable again afterwards.
    gen2 = await _acquire(_req(1))
    await _release(gen2)


# ---------------------------------------------------------------------------
# No-op paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_is_noop(org_membership, monkeypatch):
    from src.api.admission import _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "0")  # would trip instantly if active

    gen = await _acquire(_unauth_req())
    await _release(gen)

    state = _state()
    assert state.global_count == 0


@pytest.mark.asyncio
async def test_no_org_membership_is_noop(org_membership, monkeypatch):
    from src.api.admission import _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "0")  # would trip instantly if active
    # user_id=99 has no entry in org_membership -> lookup returns None.

    gen = await _acquire(_req(99))
    await _release(gen)

    state = _state()
    assert state.global_count == 0


@pytest.mark.asyncio
async def test_org_lookup_error_fails_open(org_membership, monkeypatch):
    from src.api.admission import _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "0")  # would trip instantly if active

    async def _boom(user_id: int):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("src.api.admission.lookup_org_membership", _boom)

    gen = await _acquire(_req(1))
    await _release(gen)

    state = _state()
    assert state.global_count == 0


# ---------------------------------------------------------------------------
# Kill-switch: ADMISSION_DISABLED (dev/test only, mirrors ORG_RATE_LIMIT_DISABLED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admission_disabled_noops_in_dev(org_membership, monkeypatch):
    monkeypatch.setenv("ADMISSION_DISABLED", "1")
    monkeypatch.delenv("RELEASE", raising=False)

    def _boom_lookup(*a, **kw):
        raise AssertionError("admit_analysis must no-op before resolving org")

    monkeypatch.setattr("src.api.admission.lookup_org_membership", _boom_lookup)

    gen = await _acquire(_req(1))
    await _release(gen)


@pytest.mark.asyncio
async def test_admission_disabled_ignored_in_release(org_membership, monkeypatch):
    """Mirrors org_limits._org_limits_disabled: RELEASE set -> the dev bypass
    is ignored and admission control stays enforced."""
    monkeypatch.setenv("ADMISSION_DISABLED", "1")
    monkeypatch.setenv("RELEASE", "prod-v1")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "1")
    org_membership[1] = ("org_a", "member")
    org_membership[2] = ("org_a", "member")

    gen1 = await _acquire(_req(1))
    with pytest.raises(HTTPException):
        await _acquire(_req(2))
    await _release(gen1)


# ---------------------------------------------------------------------------
# Normal (non-saturated) traffic is untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_traffic_under_ceiling_is_untouched(org_membership, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "8")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "3")
    org_membership[1] = ("org_a", "member")

    # A handful of sequential ordinary requests: no exception, slot always
    # frees back to zero between requests.
    from src.api.admission import _state

    for _ in range(5):
        gen = await _acquire(_req(1))
        await _release(gen)

    assert _state().global_count == 0
