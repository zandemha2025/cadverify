"""The check card's time comes from how long checks take here (me-21).

The card always said "About 30 s"; real checks took 70-100 s on a busy shared
server and the card never said why. The server keeps how long its recent
process checks and pricings took and how many analyses it is running now.
"""

from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace

import pytest

from src.api import admission


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_the_two_calls_of_a_check_are_told_apart():
    assert admission._kind("/api/v1/validate") == "validate"
    assert admission._kind("/api/v1/validate/cost") == "cost"
    assert admission._kind("/api/v1/validate/preview-mesh") is None


def test_timing_is_the_orgs_own_median_else_the_servers():
    async def body():
        st = admission._state()
        # The tester's checks: process checks of 22, 25 and 31 s, pricings of 48, 50 and 70 s.
        st.durations["validate"] = deque([("org-a", 22.0), ("org-a", 25.0), ("org-a", 31.0), ("org-b", 5.0)])
        st.durations["cost"] = deque([("org-a", 48.0), ("org-a", 70.0), ("org-a", 50.0)])
        mine = admission.recent_timing("org-a")
        other = admission.recent_timing("org-c")
        return mine, other

    mine, other = _run(body())
    assert mine == {"basis": "org", "validate_s": 25.0, "validate_samples": 3, "cost_s": 50.0, "cost_samples": 3}
    # An org with no checks yet reads the server's: median of 22, 25, 31, 5 = (22 + 25) / 2 = 23.5.
    assert other["basis"] == "server" and other["validate_s"] == 23.5 and other["cost_s"] == 50.0


def test_nothing_measured_yet_is_none_never_a_guess():
    t = _run((lambda: asyncio.sleep(0, result=admission.recent_timing("org-a")))())
    assert t == {"basis": None, "validate_s": None, "validate_samples": 0, "cost_s": None, "cost_samples": 0}


def test_admission_records_a_finished_check_and_counts_whats_running(monkeypatch):
    async def fake_membership(_uid):
        return ("org-a", "member")

    monkeypatch.setattr(admission, "lookup_org_membership", fake_membership)
    monkeypatch.setattr(admission, "_admission_disabled", lambda: False)
    req = SimpleNamespace(state=SimpleNamespace(authed_user=SimpleNamespace(user_id=1)), url=SimpleNamespace(path="/api/v1/validate"))

    async def body():
        gen = admission.admit_analysis(req)
        await gen.__anext__()
        running = admission.in_flight("org-a")
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        return running, admission.in_flight("org-a"), admission._state().durations["validate"][-1]

    running, after, last = _run(body())
    assert running == (1, 1) and after == (0, 0)
    assert last[0] == "org-a" and last[1] >= 0


def test_a_check_that_ran_out_of_time_counts_its_time(monkeypatch):
    from fastapi import HTTPException

    async def fake_membership(_uid):
        return ("org-t", "member")

    monkeypatch.setattr(admission, "lookup_org_membership", fake_membership)
    monkeypatch.setattr(admission, "_admission_disabled", lambda: False)
    req = SimpleNamespace(state=SimpleNamespace(authed_user=SimpleNamespace(user_id=1)), url=SimpleNamespace(path="/api/v1/validate/cost"))

    async def body(status):
        gen = admission.admit_analysis(req)
        await gen.__anext__()
        with pytest.raises(HTTPException):
            await gen.athrow(HTTPException(status_code=status))
        return [o for o, _s in admission._state().durations.get("cost", ())]

    async def both():
        refused = await body(422)
        timed_out = await body(504)
        return refused, timed_out

    refused, timed_out = _run(both())
    assert refused == [] and timed_out == ["org-t"]
