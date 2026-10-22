"""The process-wide compute budget (src.services.compute_budget).

Memory and compute slots for the CAD work in flight. A reservation is held
until the executor thread really ends, not when an await gives up on it.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from src.services import compute_budget as cb

MB = cb.MB


@pytest.fixture
def small_budget(monkeypatch):
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "1000")
    monkeypatch.setenv("COMPUTE_SLOTS", "4")
    cb.reset_for_tests()
    return cb.budget()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_capacity_from_budget_mb_wins_over_the_fraction(monkeypatch):
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "4900")
    monkeypatch.setenv("COMPUTE_MEMORY_FRACTION", "0.2")
    assert cb.memory_capacity_bytes() == 4900 * MB


def test_capacity_is_a_fraction_of_the_machine_by_default(monkeypatch):
    monkeypatch.delenv("COMPUTE_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.delenv("COMPUTE_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(cb, "_machine_memory_bytes", lambda: 8 * 1024**3)
    assert cb.memory_capacity_bytes() == int(8 * 1024**3 * 0.7)
    monkeypatch.setenv("COMPUTE_MEMORY_FRACTION", "0.5")
    assert cb.memory_capacity_bytes() == 4 * 1024**3


def test_bad_or_extreme_values_fall_back_or_clamp(monkeypatch):
    monkeypatch.setattr(cb, "_machine_memory_bytes", lambda: 10 * 1024**3)
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "lots")
    monkeypatch.setenv("COMPUTE_MEMORY_FRACTION", "nope")
    assert cb.memory_capacity_bytes() == int(10 * 1024**3 * 0.7)
    monkeypatch.delenv("COMPUTE_MEMORY_BUDGET_MB")
    monkeypatch.setenv("COMPUTE_MEMORY_FRACTION", "5")
    assert cb.memory_capacity_bytes() == int(10 * 1024**3 * 0.95)
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "1")
    assert cb.memory_capacity_bytes() == 64 * MB
    # Unknown machine memory: 2 GB is assumed, as the per-check budget does.
    monkeypatch.delenv("COMPUTE_MEMORY_BUDGET_MB")
    monkeypatch.delenv("COMPUTE_MEMORY_FRACTION")
    monkeypatch.setattr(cb, "_machine_memory_bytes", lambda: None)
    assert cb.memory_capacity_bytes() == int(2 * 1024**3 * 0.7)


def test_slots_default_to_the_cpus_and_at_least_two(monkeypatch):
    monkeypatch.delenv("COMPUTE_SLOTS", raising=False)
    monkeypatch.setattr(cb.os, "cpu_count", lambda: 4)
    assert cb.compute_slots() == 4
    monkeypatch.setattr(cb.os, "cpu_count", lambda: 1)
    assert cb.compute_slots() == 2
    monkeypatch.setattr(cb.os, "cpu_count", lambda: None)
    assert cb.compute_slots() == 2
    monkeypatch.setenv("COMPUTE_SLOTS", "6")
    assert cb.compute_slots() == 6
    monkeypatch.setenv("COMPUTE_SLOTS", "0")
    assert cb.compute_slots() == 1
    monkeypatch.setenv("COMPUTE_SLOTS", "x")
    monkeypatch.setattr(cb.os, "cpu_count", lambda: 8)
    assert cb.compute_slots() == 8


def test_wait_seconds_default_and_worker_mode(monkeypatch):
    monkeypatch.delenv("COMPUTE_WAIT_SECONDS", raising=False)
    assert cb.compute_wait_seconds() == 15.0
    assert cb.default_wait() == 15.0
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "2.5")
    assert cb.default_wait() == 2.5
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "-3")
    assert cb.compute_wait_seconds() == 0.0
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "soon")
    assert cb.compute_wait_seconds() == 15.0
    cb.worker_process()
    assert cb.default_wait() is None  # the worker waits, it never fails for room


def test_job_wait_leaves_the_job_time_for_its_work():
    now = time.monotonic()
    # A 600 s job with 360 s of work left: 600 - 360 - 30.
    assert cb.job_wait_seconds(now, 360, 600) == pytest.approx(210, abs=1)
    # Work that nearly fills the job still waits the floor...
    assert cb.job_wait_seconds(now, 590, 600) == pytest.approx(30, abs=1)
    # ...but never so long that the wait reaches the job's own timeout.
    assert cb.job_wait_seconds(now - 560, 10, 600) == 0.0
    assert cb.job_wait_seconds(now - 500, 10, 600) == pytest.approx(40, abs=1)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_release_from_another_thread_wakes_a_waiter(small_budget):
    held = await small_budget.reserve(800 * MB, wait=None, label="first")
    waiter = asyncio.create_task(small_budget.reserve(500 * MB, wait=5, label="second"))
    await asyncio.sleep(0.1)
    assert not waiter.done()
    assert small_budget.snapshot()["waiting"] == 1

    t = threading.Thread(target=lambda: (time.sleep(0.1), held.leave()))
    t0 = time.monotonic()
    t.start()
    second = await asyncio.wait_for(waiter, 2)
    t.join()
    assert time.monotonic() - t0 < 1.0
    assert small_budget.snapshot()["used_bytes"] == 500 * MB
    second.leave()
    assert small_budget.snapshot() == {**small_budget.snapshot(), "used_bytes": 0, "used_slots": 0, "running": 0}


@pytest.mark.asyncio
async def test_a_timed_out_call_keeps_its_room_until_its_thread_returns(small_budget):
    finish = threading.Event()
    ended = threading.Event()

    def compute():
        finish.wait(5)
        ended.set()
        return "done late"

    with pytest.raises(asyncio.TimeoutError):
        await cb.run_within_budget(compute, need_bytes=700 * MB, timeout=0.1, label="slow")
    # The await gave up; the thread did not: its 700 MB is still counted.
    assert small_budget.snapshot()["used_bytes"] == 700 * MB
    with pytest.raises(cb.ComputeBusy):
        await cb.run_within_budget(lambda: 1, need_bytes=700 * MB, wait=0.2)
    assert not ended.is_set()

    # Once it really ends, the room comes back and the next call runs.
    late = asyncio.create_task(cb.run_within_budget(lambda: "next", need_bytes=700 * MB, wait=5))
    await asyncio.sleep(0.05)
    assert not late.done()
    finish.set()
    assert await asyncio.wait_for(late, 2) == "next"
    assert ended.is_set()
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_a_cancelled_await_keeps_the_room_too(small_budget):
    finish = threading.Event()
    task = asyncio.create_task(cb.run_within_budget(lambda: finish.wait(5), need_bytes=300 * MB))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert small_budget.snapshot()["used_bytes"] == 300 * MB
    finish.set()
    for _ in range(100):
        if small_budget.snapshot()["used_bytes"] == 0:
            break
        await asyncio.sleep(0.01)
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_work_bigger_than_the_budget_runs_alone(small_budget):
    small = await small_budget.reserve(100 * MB, wait=None)
    # 3 GB never fits a 1 GB budget: it waits until nothing else runs...
    big = asyncio.create_task(small_budget.reserve(3000 * MB, wait=5, label="big"))
    await asyncio.sleep(0.1)
    assert not big.done()
    small.leave()
    big_res = await asyncio.wait_for(big, 2)
    assert small_budget.snapshot()["running"] == 1
    # ...and nothing else starts beside it, however small.
    with pytest.raises(cb.ComputeBusy):
        await small_budget.reserve(1 * MB, wait=0.1)
    big_res.leave()
    tiny = await small_budget.reserve(1 * MB, wait=0)
    tiny.leave()


@pytest.mark.asyncio
async def test_the_slot_limit(small_budget, monkeypatch):
    monkeypatch.setenv("COMPUTE_SLOTS", "2")
    a = await small_budget.reserve(1 * MB, wait=0)
    b = await small_budget.reserve(1 * MB, wait=0)
    with pytest.raises(cb.ComputeBusy):
        await small_budget.reserve(1 * MB, wait=0.1)
    a.leave()
    c = await small_budget.reserve(1 * MB, wait=0)
    assert small_budget.snapshot()["used_slots"] == 2
    b.leave()
    c.leave()


@pytest.mark.asyncio
async def test_waiters_are_served_in_order_so_a_big_part_is_not_starved(small_budget):
    first = await small_budget.reserve(600 * MB, wait=None)
    big = asyncio.create_task(small_budget.reserve(900 * MB, wait=5, label="big"))
    await asyncio.sleep(0.05)
    # 300 MB would fit beside the first, but the big part is ahead of it in line.
    small = asyncio.create_task(small_budget.reserve(300 * MB, wait=5, label="small"))
    await asyncio.sleep(0.05)
    assert not big.done() and not small.done()
    first.leave()
    big_res = await asyncio.wait_for(big, 2)
    await asyncio.sleep(0.05)
    assert not small.done()
    big_res.leave()
    (await asyncio.wait_for(small, 2)).leave()


@pytest.mark.asyncio
async def test_a_waiter_that_gives_up_lets_the_next_one_in(small_budget):
    first = await small_budget.reserve(600 * MB, wait=None)
    big = asyncio.create_task(small_budget.reserve(900 * MB, wait=0.2, label="big"))
    await asyncio.sleep(0.05)
    small = asyncio.create_task(small_budget.reserve(300 * MB, wait=5, label="small"))
    with pytest.raises(cb.ComputeBusy):
        await big
    # The head left the line: the small one fits beside the first and goes now.
    (await asyncio.wait_for(small, 1)).leave()
    first.leave()
    assert small_budget.snapshot()["waiting"] == 0


def test_busy_is_the_apis_429_server_busy_with_retry_after():
    exc = cb.ComputeBusy(3.0)
    assert exc.status_code == 429
    assert exc.detail["code"] == "server_busy"
    assert exc.detail["message"] == "server is at capacity, retry shortly"
    assert int(exc.headers["Retry-After"]) >= 1


# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_hold_inside_a_hold_joins_it(small_budget):
    async with cb.hold(400 * MB, label="outer") as outer:
        async with cb.hold(400 * MB, label="inner") as inner:
            assert inner is outer
            seen = await cb.run_within_budget(cb.current)
            assert seen is outer
        assert small_budget.snapshot()["used_bytes"] == 400 * MB
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_a_hold_keeps_its_room_for_a_thread_that_outlives_it(small_budget):
    finish = threading.Event()
    async with cb.hold(500 * MB, label="part"):
        with pytest.raises(asyncio.TimeoutError):
            await cb.run_within_budget(lambda: finish.wait(5), timeout=0.05)
    # The block ended; its abandoned thread still holds the part's room.
    assert small_budget.snapshot()["used_bytes"] == 500 * MB
    finish.set()
    for _ in range(100):
        if small_budget.snapshot()["used_bytes"] == 0:
            break
        await asyncio.sleep(0.01)
    assert small_budget.snapshot() == {**small_budget.snapshot(), "used_bytes": 0, "running": 0}


@pytest.mark.asyncio
async def test_a_deferred_hold_takes_room_only_when_the_work_starts(small_budget):
    async with cb.deferred_hold(label="analysis") as room:
        assert small_budget.snapshot()["running"] == 0  # a cached answer would end here
        await room.take(200 * MB)
        assert cb.current() is room.reservation
        assert small_budget.snapshot()["used_bytes"] == 200 * MB
    assert cb.current() is None
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_the_wait_is_not_part_of_the_time_limit(small_budget):
    held = await small_budget.reserve(900 * MB, wait=None)
    threading.Timer(0.3, held.leave).start()
    t0 = time.monotonic()
    # 0.3 s waiting for room, then 0.1 s of work under a 0.2 s limit: no timeout.
    out = await cb.run_within_budget(lambda: (time.sleep(0.1), "ok")[1], need_bytes=500 * MB, timeout=0.2, wait=5)
    assert out == "ok"
    assert time.monotonic() - t0 >= 0.3


@pytest.mark.asyncio
async def test_need_for_data_uses_the_memory_model():
    from src.services.stored_check_service import estimate_memory_bytes_for_data

    stl = b"solid x\n" + b"facet normal 0 0 1\n" * 100 + b"endsolid\n"
    assert cb.need_for_data(stl, "x.stl") == estimate_memory_bytes_for_data(stl, "x.stl")[0]
    assert cb.need_for_data(b"ISO-10303-21;" * 10, "x.step") >= cb.default_need()
