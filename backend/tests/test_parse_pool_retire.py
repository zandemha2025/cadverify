"""The shared parse pool under load: one slow part never kills the others' parses.

- A rung-0 cap or an abandoned request retires the shared pool: new work goes to
  a fresh pool, and the old one (the stuck worker with it) is killed only once
  its other in-flight parses have finished.
- A parse or assembly extraction takes a pool slot before its timer starts.
- A rung's cap is its worker's CPU time; a ladder that runs out of wall time
  first answers busy (429 server_busy) and never tries the next strategy.
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures.process import BrokenProcessPool

import pytest
import trimesh
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
async def test_a_stopped_rung_zero_retires_its_pool_and_spares_the_sibling(monkeypatch):
    """Rung 0 on the shared pool is stopped (here: out of time): its pool is retired, with it as the stuck one."""
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
    loop = asyncio.get_event_loop()
    monkeypatch.setattr(parse_pool, "STARTUP_LIMIT_SEC", 0.3)  # its worker never begins
    token = parse_pool.ladder_clock(0.3)
    try:
        with pytest.raises(parse_pool._RungStarved) as ei:
            await parse_pool._rung0_via_pool(b"step", ".step", 0.1, loop)
    finally:
        parse_pool._LADDER_CLOCK.reset(token)
    assert not ei.value.started
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
async def test_a_rung_out_of_wall_time_answers_busy_and_never_tries_the_next(monkeypatch):
    """Running out of wall time is the box, not the part: busy, and no other strategy (another mesh)."""
    tried = []

    async def _starved0(data, suffix, cap, loop):
        tried.append(0)
        raise parse_pool._RungStarved(0, 3.0, 24.0)

    async def _recovery(data, suffix, idx, cap):
        tried.append(idx)
        return trimesh.creation.box(extents=(10, 10, 10))

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _starved0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _recovery)
    with pytest.raises(parse_pool.ParseBusy) as ei:
        await parse_pool.submit_async(b"part", ".step")
    assert tried == [0]
    assert str(ei.value) == "ScaleCAD is busy; this part ran out of time before its meshing finished. Try again."
    # The route answers the API's busy 429, not a 400 "can't be meshed".
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    with pytest.raises(HTTPException) as http:
        await routes._tessellate_step_via_pool(b"part", ".step", "part.step")
    assert http.value.status_code == 429 and http.value.detail["code"] == "server_busy"
    assert isinstance(http.value, compute_budget.MeshBusy)


@pytest.mark.asyncio
async def test_a_rung_that_used_its_cpu_budget_advances(monkeypatch):
    """A rung that used up its CPU cap doesn't converge (on any load): the next strategy runs."""
    tried = []

    async def _grind0(data, suffix, cap, loop):
        tried.append(0)
        raise parse_pool._RungTimeout("rung 0 used its 24s of CPU")

    async def _recovery(data, suffix, idx, cap):
        tried.append(idx)
        return trimesh.creation.box(extents=(10, 10, 10))

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _grind0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _recovery)
    mesh = await parse_pool.submit_async(b"part", ".step")
    assert tried == [0, 1] and mesh.is_watertight


@pytest.mark.asyncio
async def test_a_geometry_failure_still_advances_and_all_failing_is_the_honest_400(monkeypatch):
    tried = []

    async def _fail0(data, suffix, cap, loop):
        tried.append(0)
        raise RuntimeError("gmsh: no surfaces")

    async def _fail(data, suffix, idx, cap):
        tried.append(idx)
        raise RuntimeError("gmsh: no surfaces")

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _fail0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", _fail)
    with pytest.raises(ValueError) as ei:
        await parse_pool.submit_async(b"part", ".step")
    assert not isinstance(ei.value, parse_pool.ParseBusy)
    assert tried == [0, 1, 2]
    monkeypatch.setattr(routes, "is_step_supported", lambda: True)
    with pytest.raises(HTTPException) as http:
        await routes._tessellate_step_via_pool(b"part", ".step", "part.step")
    assert http.value.status_code == 400
    assert "could not tessellate" in str(http.value.detail).lower()


def _burn(report: str, seconds: float) -> str:
    """A rung's worker that computes (CPU) for ``seconds``."""
    parse_pool._report_start(report)
    end = time.process_time() + seconds
    while time.process_time() < end:
        pass
    return "burned"


def _nap(report: str, seconds: float) -> str:
    """A rung's worker that gets no CPU (as on a starved box) for ``seconds``."""
    parse_pool._report_start(report)
    time.sleep(seconds)
    return "napped"


def _slow_start(report: str, seconds: float, delay: float = 3.0) -> str:
    """A rung's worker that takes ``delay`` s to start (a starved spawn), then computes ``seconds``."""
    time.sleep(delay)
    return _burn(report, seconds)


async def _await_in_own_process(fn, seconds: float, cpu_cap: float, deadline_s: float):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    ex = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    report = parse_pool._new_report()
    token = parse_pool.ladder_clock(deadline_s)
    try:
        cfut = ex.submit(fn, report, seconds)
        return await parse_pool._await_rung(cfut, report, 0, cpu_cap)
    finally:
        parse_pool._LADDER_CLOCK.reset(token)
        parse_pool._hard_kill(ex)
        ex.shutdown(wait=False, cancel_futures=True)
        parse_pool._drop_report(report)


@pytest.mark.asyncio
async def test_the_rung_cap_is_the_workers_cpu_time_not_wall_time():
    # 1 s of CPU against a 0.5 s CPU cap: the cap, well inside a 60 s deadline.
    with pytest.raises(parse_pool._RungTimeout):
        await _await_in_own_process(_burn, 1.0, cpu_cap=0.5, deadline_s=60)
    # Asleep (no CPU) far past the cap's seconds: not the cap, but the deadline: starved.
    t0 = time.monotonic()
    with pytest.raises(parse_pool._RungStarved):
        await _await_in_own_process(_nap, 30.0, cpu_cap=0.5, deadline_s=8)
    assert time.monotonic() - t0 < 20
    # Within both: the result.
    assert await _await_in_own_process(_nap, 0.2, cpu_cap=0.5, deadline_s=60) == "napped"


@pytest.mark.asyncio
async def test_a_slow_to_start_worker_does_not_spend_the_ladders_time():
    """A spawn and its imports on a starved box are not the part's time: a 3 s start
    against a 2 s ladder, then 0.3 s of work, still meshes (the clock starts at the rung)."""
    assert await _await_in_own_process(_slow_start, 0.3, cpu_cap=5.0, deadline_s=2.0) == "burned"


@pytest.mark.asyncio
async def test_a_rung_that_never_starts_is_busy_in_plain_words(monkeypatch):
    monkeypatch.setattr(parse_pool, "STARTUP_LIMIT_SEC", 1.0)
    with pytest.raises(parse_pool._RungStarved) as ei:
        await _await_in_own_process(_slow_start, 0.3, cpu_cap=5.0, deadline_s=60.0)
    assert not ei.value.started
    assert ei.value.plain() == "ScaleCAD is busy; this part didn't get started. Try again."


@pytest.mark.asyncio
async def test_the_ladder_says_it_never_started_when_its_rung_got_no_cpu(monkeypatch):
    async def _never0(data, suffix, cap, loop):
        raise parse_pool._RungStarved(0, cap=cap, started=False)

    monkeypatch.setattr(parse_pool, "_rung0_via_pool", _never0)
    monkeypatch.setattr(parse_pool, "_run_rung_killable", lambda *a: pytest.fail("never advances because of time"))
    with pytest.raises(parse_pool.ParseBusy) as ei:
        await parse_pool.submit_async(b"part", ".step")
    assert str(ei.value) == "ScaleCAD is busy; this part didn't get started. Try again."


@pytest.mark.asyncio
async def test_taking_a_pool_slot_warms_a_fresh_pool_first(fresh_pool, monkeypatch):
    """The slot is taken before the caller's timer: a cold pool's spawn is paid there."""
    async with parse_pool.pool_slot():
        pool = parse_pool._get_pool()
        warm = parse_pool._WARMING.get(id(pool))
        assert warm and all(f.done() for f in warm)


def test_a_busy_mesh_is_a_catalog_timeout_checked_again_later():
    from src.jobs.batch_tasks import _timed_out

    assert _timed_out(compute_budget.MeshBusy())
    assert not _timed_out(compute_budget.ComputeBusy())
