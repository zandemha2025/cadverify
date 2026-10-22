"""The shared parse pool under load: one slow part never kills the others' parses.

- A rung-0 cap or an abandoned request retires the shared pool: new work goes to
  a fresh pool, and the old one (the stuck worker with it) is killed only once
  its other in-flight parses have finished.
- A parse or assembly extraction takes a pool slot before its timer starts.
- A ladder whose rungs ran out of wall time on a saturated box answers busy
  (429 server_busy), not "this file can't be meshed".
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures.process import BrokenProcessPool

import pytest
from fastapi import HTTPException

from src.api import routes
from src.parsers import parse_pool
from src.services import compute_budget


@pytest.fixture
def fresh_pool(monkeypatch):
    monkeypatch.setenv("PARSE_POOL_WORKERS", "2")
    parse_pool.shutdown(kill=True)
    parse_pool.startup()
    yield
    parse_pool.shutdown(kill=True)


def _wait_running(futures, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(f.running() or f.done() for f in futures):
            return
        time.sleep(0.05)
    raise AssertionError("pool workers never started")


def test_retiring_a_pool_lets_the_other_parses_finish_then_kills_the_stuck_worker(fresh_pool):
    pool = parse_pool._get_pool()
    stuck = parse_pool._submit_tracked(pool, time.sleep, 60)
    sibling = parse_pool._submit_tracked(pool, time.sleep, 1.5)
    _wait_running([stuck, sibling])

    parse_pool.retire_pool(pool, stuck=stuck)
    assert parse_pool._get_pool() is not pool  # new work goes to a fresh pool at once
    # The other request's parse on the retired pool finishes normally...
    assert sibling.result(timeout=30) is None
    # ...and then the stuck worker is killed, well before its 60 s grind ends.
    t0 = time.monotonic()
    with pytest.raises(BrokenProcessPool):
        stuck.result(timeout=30)
    assert time.monotonic() - t0 < 20


def test_a_retired_pool_with_nothing_else_running_is_killed_at_once(fresh_pool):
    pool = parse_pool._get_pool()
    stuck = parse_pool._submit_tracked(pool, time.sleep, 60)
    _wait_running([stuck])
    parse_pool.retire_pool(pool, stuck=stuck)
    with pytest.raises(BrokenProcessPool):
        stuck.result(timeout=15)


@pytest.mark.asyncio
async def test_a_capped_rung_zero_retires_its_pool_and_spares_the_sibling(monkeypatch):
    """Rung 0 on the shared pool hits its cap: its pool is retired with it as the stuck one."""
    retired = []

    class _Pool:
        def submit(self, fn, *args):
            import concurrent.futures

            f = concurrent.futures.Future()
            f.set_running_or_notify_cancel()  # running: a cancel can't stop it
            return f

    pool = _Pool()
    monkeypatch.setattr(parse_pool, "_get_pool", lambda: pool)
    monkeypatch.setattr(parse_pool, "retire_pool", lambda p, stuck=None, **k: retired.append((p, stuck)))
    monkeypatch.setattr(parse_pool, "recycle_pool", lambda **k: pytest.fail("the shared pool must not be killed"))
    with pytest.raises(parse_pool._RungTimeout):
        await parse_pool._rung0_via_pool(b"step", ".step", 0.1, asyncio.get_event_loop())
    assert len(retired) == 1 and retired[0][0] is pool and retired[0][1] is not None


@pytest.mark.asyncio
async def test_a_cancelled_assembly_extraction_retires_its_pool(monkeypatch):
    retired = []
    started = asyncio.Event()

    class _Pool:
        def submit(self, fn, *args):
            import concurrent.futures

            f = concurrent.futures.Future()
            f.set_running_or_notify_cancel()
            asyncio.get_event_loop().call_soon(started.set)
            return f

    pool = _Pool()
    monkeypatch.setattr(parse_pool, "is_disabled", lambda: False)
    monkeypatch.setattr(parse_pool, "_get_pool", lambda: pool)
    monkeypatch.setattr(parse_pool, "retire_pool", lambda p, stuck=None, **k: retired.append((p, stuck)))
    monkeypatch.setattr(parse_pool, "recycle_pool", lambda **k: pytest.fail("the shared pool must not be killed"))
    task = asyncio.create_task(parse_pool.submit_assembly_async(b"step", ".step"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(retired) == 1 and retired[0][0] is pool


@pytest.mark.asyncio
async def test_the_pool_slot_is_taken_before_the_timer_and_is_re_entrant(monkeypatch):
    monkeypatch.setenv("PARSE_POOL_WORKERS", "1")
    async with parse_pool.pool_slot():
        async with parse_pool.pool_slot():  # the ladder inside takes it again: no deadlock
            pass
        waiter = asyncio.create_task(_slot_then(lambda: "second"))
        await asyncio.sleep(0.05)
        assert not waiter.done()  # one pool worker: the second waits for the slot
    assert await asyncio.wait_for(waiter, 1) == "second"


async def _slot_then(fn):
    async with parse_pool.pool_slot():
        return fn()


@pytest.mark.asyncio
async def test_rungs_capped_on_a_saturated_box_answer_busy_not_unmeshable(monkeypatch):
    monkeypatch.setenv("ANALYSIS_TIMEOUT_SEC", "3")

    async def _grind0(data, suffix, cap, loop):
        raise parse_pool._RungTimeout("rung 0 exceeded its cap")

    async def _grind_recovery(data, suffix, idx, cap):
        raise parse_pool._RungTimeout(f"rung {idx} exceeded its cap")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _grind0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _grind_recovery)

    monkeypatch.setattr(parse_pool, "_saturated", lambda: True)
    with pytest.raises(parse_pool.ParseBusy) as ei:
        await parse_pool.submit_async(b"part", ".step")
    assert "could not tessellate" in str(ei.value).lower()  # still the ladder's own words underneath
    # The route answers the API's busy 429, not a 400 "can't be meshed".
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    with pytest.raises(HTTPException) as http:
        await routes._tessellate_step_via_pool(b"part", ".step", "part.step")
    assert http.value.status_code == 429 and http.value.detail["code"] == "server_busy"
    assert isinstance(http.value, compute_budget.MeshBusy)

    # An idle box: the honest 400.
    monkeypatch.setattr(parse_pool, "_saturated", lambda: False)
    with pytest.raises(HTTPException) as http:
        await routes._tessellate_step_via_pool(b"part", ".step", "part.step")
    assert http.value.status_code == 400
    assert "could not tessellate" in str(http.value.detail).lower()


@pytest.mark.asyncio
async def test_a_deterministic_mesh_failure_stays_a_400_even_when_busy(monkeypatch):
    async def _fail0(data, suffix, cap, loop):
        raise RuntimeError("gmsh: no surfaces")

    async def _fail(data, suffix, idx, cap):
        raise RuntimeError("gmsh: no surfaces")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _fail0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _fail)
    monkeypatch.setattr(parse_pool, "_saturated", lambda: True)
    with pytest.raises(ValueError) as ei:
        await parse_pool.submit_async(b"part", ".step")
    assert not isinstance(ei.value, parse_pool.ParseBusy)


def test_a_busy_mesh_is_a_catalog_timeout_checked_again_later():
    from src.jobs.batch_tasks import _timed_out

    assert _timed_out(compute_budget.MeshBusy())
    assert not _timed_out(compute_budget.ComputeBusy())


def test_saturation_reads_the_load_and_the_budget(monkeypatch):
    monkeypatch.setattr(parse_pool.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(parse_pool.os, "getloadavg", lambda: (9.0, 5.0, 3.0))
    assert parse_pool._saturated()
    monkeypatch.setattr(parse_pool.os, "getloadavg", lambda: (1.0, 1.0, 1.0))
    assert not parse_pool._saturated()

