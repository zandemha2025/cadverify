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


# ---------------------------------------------------------------------------
# A part check counts once, whatever number of calls it makes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_calls_of_one_check_count_once(monkeypatch):
    from src.api.admission import _acquire, _release, _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "10")
    monkeypatch.setenv("ADMISSION_CHECK_GRACE_SECONDS", "0")
    state = _state()
    calls = ["/api/v1/validate/assembly?format=json", "/api/v1/validate/preview-mesh?purpose=analysis",
             "/api/v1/validate", "/api/v1/validate/cost"]
    for call in calls:
        _acquire(state, "org_a", "org_a:1:aaa", call)
    assert state.global_count == 1  # the probe, preview, check and price of one file
    _acquire(state, "org_b", "org_b:2:bbb", "/api/v1/validate")
    assert state.global_count == 2
    with pytest.raises(HTTPException) as exc:
        _acquire(state, "org_c", "org_c:3:ccc", "/api/v1/validate")
    assert exc.value.detail["code"] == "server_busy"
    # The first check's calls still run: they never take a second unit.
    _acquire(state, "org_a", "org_a:1:aaa", "/api/v1/validate/cost/demo")
    assert state.global_count == 2
    for call in calls + ["/api/v1/validate/cost/demo"]:
        _release(state, "org_a", "org_a:1:aaa", call)
    _release(state, "org_b", "org_b:2:bbb", "/api/v1/validate")
    assert state.global_count == 0 and state.per_org == {} and state.checks == {}


@pytest.mark.asyncio
async def test_two_calls_of_the_same_kind_on_one_file_count_as_two_checks(monkeypatch):
    from src.api.admission import _acquire, _release, _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "2")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "10")
    monkeypatch.setenv("ADMISSION_CHECK_GRACE_SECONDS", "0")
    state = _state()
    _acquire(state, "org_a", "k", "/api/v1/validate")
    _acquire(state, "org_a", "k", "/api/v1/validate")  # the same bytes checked twice at once
    assert state.global_count == 2
    with pytest.raises(HTTPException):
        _acquire(state, "org_a", "k", "/api/v1/validate")  # parallel calls can't hide work
    _acquire(state, "org_a", "k", "/api/v1/validate/preview-mesh")  # a different call of it: free
    assert state.global_count == 2
    _release(state, "org_a", "k", "/api/v1/validate")
    assert state.global_count == 1
    for call in ("/api/v1/validate", "/api/v1/validate/preview-mesh"):
        _release(state, "org_a", "k", call)
    assert state.global_count == 0


@pytest.mark.asyncio
async def test_a_check_stays_counted_briefly_after_its_last_call(monkeypatch):
    import asyncio

    from src.api.admission import _acquire, _release, _state

    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "1")
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES_PER_ORG", "10")
    monkeypatch.setenv("ADMISSION_CHECK_GRACE_SECONDS", "0.2")
    state = _state()
    _acquire(state, "org_a", "k", "/api/v1/validate")
    _release(state, "org_a", "k", "/api/v1/validate")
    # The check's price comes a moment later: its room is still there...
    assert state.global_count == 1
    with pytest.raises(HTTPException):
        _acquire(state, "org_b", "other", "/api/v1/validate")
    _acquire(state, "org_a", "k", "/api/v1/validate/cost")
    _release(state, "org_a", "k", "/api/v1/validate/cost")
    # ...and once the grace passes with no call, it's given back.
    await asyncio.sleep(0.3)
    assert state.global_count == 0 and state.checks == {}
    _acquire(state, "org_b", "other", "/api/v1/validate")
    _release(state, "org_b", "other", "/api/v1/validate")


from fastapi import Depends, FastAPI, File, Request, UploadFile  # noqa: E402  (module level: the routes' annotations)


def _check_app(monkeypatch, seen):
    from src.api.admission import admit_analysis
    from src.services import compute_budget

    app = FastAPI()

    async def authed(request: Request):
        request.state.authed_user = AuthedUser(user_id=int(request.headers.get("x-user", "1")), api_key_id=1,
                                               key_prefix="t")

    @app.post("/api/v1/validate", dependencies=[Depends(authed)])
    async def validate(request: Request, file: UploadFile = File(...), _a: None = Depends(admit_analysis)):
        from src.api.admission import in_flight

        seen.append((compute_budget.check_key(), in_flight("org_a")[0], await file.read()))
        return {"ok": True}

    @app.get("/api/v1/parts/{mesh_hash}/orientations", dependencies=[Depends(authed)])
    async def orient(mesh_hash: str, _a: None = Depends(admit_analysis)):
        seen.append((compute_budget.check_key(), None, None))
        return {"ok": True}

    return app


def test_admission_names_the_check_for_the_compute_budget(org_membership, monkeypatch):
    import hashlib

    from fastapi.testclient import TestClient

    org_membership[1] = ("org_a", "member")
    org_membership[2] = ("org_a", "member")
    seen: list = []
    client = TestClient(_check_app(monkeypatch, seen))
    part = b"solid part\nendsolid part\n"
    sha = hashlib.sha256(part).hexdigest()
    assert client.post("/api/v1/validate", files={"file": ("p.stl", part)}).status_code == 200
    assert client.post("/api/v1/validate", files={"file": ("renamed.stl", part)}).status_code == 200
    assert client.post("/api/v1/validate", files={"file": ("p.stl", part + b" ")}).status_code == 200
    assert client.post("/api/v1/validate", files={"file": ("p.stl", part)}, headers={"x-user": "2"}).status_code == 200
    assert client.get(f"/api/v1/parts/{sha}/orientations").status_code == 200
    keys = [k for k, _n, _b in seen]
    # The same person and bytes: one check, whatever the file is called; the
    # endpoint still reads the whole upload after admission hashed it.
    assert keys[0] == keys[1] == f"org_a:1:{sha}"
    assert seen[0][2] == part
    assert keys[2] != keys[0]  # other bytes
    assert keys[3] == f"org_a:2:{sha}"  # another person
    assert keys[4] == keys[0]  # the kept part of the same bytes is the same check
    assert seen[0][1] == 1  # counted while it ran
    from src.services import compute_budget

    assert compute_budget.check_key() is None
