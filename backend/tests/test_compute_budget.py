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


def _host(monkeypatch, cpus, *, affinity=None, cgroup=None, tmp_path=None):
    """A host of ``cpus`` CPUs, this process allowed on ``affinity`` of them, in a cgroup with ``cgroup`` (cpu.max)."""
    monkeypatch.setattr(cb.os, "cpu_count", lambda: cpus)
    monkeypatch.setattr(cb.os, "sched_getaffinity", lambda _pid: set(range(affinity or cpus or 1)))
    if cgroup is None:
        monkeypatch.setattr(cb, "CGROUP_CPU_FILES", ())
        monkeypatch.setattr(cb, "CGROUP_V1_CPU_FILES", ("/nonexistent/quota", "/nonexistent/period"))
    else:
        f = tmp_path / "cpu.max"
        f.write_text(cgroup + "\n")
        monkeypatch.setattr(cb, "CGROUP_CPU_FILES", (str(f),))


def test_slots_default_to_the_cpus_and_at_least_two(monkeypatch):
    monkeypatch.delenv("COMPUTE_SLOTS", raising=False)
    _host(monkeypatch, 4)
    assert cb.compute_slots() == 4
    _host(monkeypatch, 1)
    assert cb.compute_slots() == 2
    _host(monkeypatch, None)
    assert cb.compute_slots() == 2
    monkeypatch.setenv("COMPUTE_SLOTS", "6")
    assert cb.compute_slots() == 6
    monkeypatch.setenv("COMPUTE_SLOTS", "0")
    assert cb.compute_slots() == 1
    monkeypatch.setenv("COMPUTE_SLOTS", "x")
    _host(monkeypatch, 8)
    assert cb.compute_slots() == 8


def test_slots_come_from_the_containers_cpu_quota_not_the_host(monkeypatch, tmp_path):
    monkeypatch.delenv("COMPUTE_SLOTS", raising=False)
    # A 2-CPU container on a 16-CPU host: os.cpu_count() says 16, cpu.max says 2.
    _host(monkeypatch, 16, cgroup="200000 100000", tmp_path=tmp_path)
    assert cb.available_cpus() == 2
    assert cb.compute_slots() == 2
    # A fractional quota rounds up; no quota ("max") leaves the CPUs the process may use.
    _host(monkeypatch, 16, cgroup="150000 100000", tmp_path=tmp_path)
    assert cb.available_cpus() == 2
    _host(monkeypatch, 16, cgroup="50000 100000", tmp_path=tmp_path)
    assert cb.available_cpus() == 1
    assert cb.compute_slots() == 2  # never fewer than two
    _host(monkeypatch, 16, cgroup="max 100000", tmp_path=tmp_path)
    assert cb.available_cpus() == 16
    # Pinned to 2 CPUs (taskset, a cpuset): 2, whatever the host has.
    _host(monkeypatch, 16, affinity=2, cgroup="max 100000", tmp_path=tmp_path)
    assert cb.available_cpus() == 2
    # cgroup v1: cfs quota over period.
    _host(monkeypatch, 16)
    q, per = tmp_path / "quota", tmp_path / "period"
    q.write_text("400000\n")
    per.write_text("100000\n")
    monkeypatch.setattr(cb, "CGROUP_V1_CPU_FILES", (str(q), str(per)))
    assert cb.available_cpus() == 4
    q.write_text("-1\n")  # unlimited
    assert cb.available_cpus() == 16
    # The env override stays.
    monkeypatch.setenv("COMPUTE_SLOTS", "3")
    assert cb.compute_slots() == 3


def test_the_parse_pool_sizes_from_the_container_too(monkeypatch, tmp_path):
    from src.parsers import parse_pool

    monkeypatch.delenv("PARSE_POOL_WORKERS", raising=False)
    _host(monkeypatch, 16, cgroup="200000 100000", tmp_path=tmp_path)
    assert parse_pool.worker_count() == 1  # 2 CPUs less one for the event loop
    _host(monkeypatch, 16, cgroup="400000 100000", tmp_path=tmp_path)
    assert parse_pool.worker_count() == 3
    monkeypatch.setenv("PARSE_POOL_WORKERS", "2")
    assert parse_pool.worker_count() == 2


def test_wait_seconds_default_and_worker_mode(monkeypatch):
    monkeypatch.delenv("COMPUTE_WAIT_SECONDS", raising=False)
    assert cb.compute_wait_seconds() == 30.0
    assert cb.default_wait() == 30.0
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "2.5")
    assert cb.default_wait() == 2.5
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "-3")
    assert cb.compute_wait_seconds() == 0.0
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "soon")
    assert cb.compute_wait_seconds() == 30.0
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


# ---------------------------------------------------------------------------
# The process's own baseline, and memory given back after work
# ---------------------------------------------------------------------------


def test_capacity_leaves_room_for_the_process_baseline(monkeypatch):
    monkeypatch.delenv("COMPUTE_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.delenv("COMPUTE_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(cb, "_machine_memory_bytes", lambda: 4 * 1024**3)
    # A 4 GB machine whose process kept 2.4 GB after earlier checks: 0.9 x 4 GB - 2.4 GB.
    monkeypatch.setattr(cb, "_tree_rss_bytes", lambda: int(2.4 * 1024**3))
    b = cb.ComputeBudget()
    assert b.capacity_bytes == int(4 * 1024**3 * cb.MACHINE_SHARE) - int(2.4 * 1024**3)
    # A lean baseline: the configured 0.7 of the machine is the limit.
    monkeypatch.setattr(cb, "_tree_rss_bytes", lambda: 300 * MB)
    assert cb.ComputeBudget().capacity_bytes == int(4 * 1024**3 * 0.7)


@pytest.mark.asyncio
async def test_finished_work_gives_memory_back_and_measures_the_idle_baseline(small_budget, monkeypatch):
    trims = []
    monkeypatch.setattr(cb, "give_memory_back", lambda: trims.append(time.monotonic()))
    monkeypatch.setattr(cb, "_tree_rss_bytes", lambda: 777 * MB)
    await cb.run_within_budget(lambda: None, need_bytes=100 * MB)
    for _ in range(100):
        if trims and small_budget.snapshot()["idle_baseline_bytes"] == 777 * MB:
            break
        await asyncio.sleep(0.01)
    assert trims
    assert small_budget.snapshot()["idle_baseline_bytes"] == 777 * MB


def test_capacity_counts_resident_memory_no_reservation_explains(monkeypatch):
    monkeypatch.delenv("COMPUTE_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.delenv("COMPUTE_MEMORY_FRACTION", raising=False)
    monkeypatch.setattr(cb, "_machine_memory_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(cb, "_tree_rss_bytes", lambda: 500 * MB)
    b = cb.ComputeBudget()
    assert b.capacity_bytes == int(8 * 1024**3 * 0.7)  # lean: the configured share
    # Busy: 3.8 GB resident with 0.9 GB reserved leaves 2.9 GB nobody reserved
    # (the heap kept from earlier parts): the room shrinks to what's really left.
    b.used_bytes = 900 * MB
    assert b._capacity(3800 * MB) == int(8 * 1024**3 * cb.MACHINE_SHARE) - 2900 * MB


# ---------------------------------------------------------------------------
# One check, one reservation (the probe, preview, /validate and /validate/cost)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_calls_of_one_check_share_one_reservation(small_budget):
    with cb.check_scope("org:1:abc"):
        preview = await small_budget.reserve(400 * MB, wait=0, label="preview mesh")
        analysis = await small_budget.reserve(400 * MB, wait=0, label="analysis")
    # One slot and the largest single need, not 800 MB and two slots.
    assert small_budget.snapshot()["used_slots"] == 1
    assert small_budget.snapshot()["used_bytes"] == 400 * MB
    assert preview.reservation is analysis.reservation
    # Another person's check of other bytes has its own.
    with cb.check_scope("org:2:def"):
        other = await small_budget.reserve(300 * MB, wait=0, label="analysis")
    assert small_budget.snapshot()["used_slots"] == 2
    preview.leave()
    assert small_budget.snapshot()["used_bytes"] == 700 * MB  # the analysis still holds the check's room
    analysis.leave()
    assert small_budget.snapshot()["used_bytes"] == 300 * MB
    assert small_budget.snapshot()["used_slots"] == 1
    other.leave()
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_a_second_copy_of_the_same_heavy_work_adds_its_need(small_budget):
    with cb.check_scope("org:1:abc"):
        first = await small_budget.reserve(300 * MB, wait=0, label="analysis")
        second = await small_budget.reserve(300 * MB, wait=0, label="analysis")  # e.g. another orientation
        price = await small_budget.reserve(200 * MB, wait=0, label="cost")
        preview = await small_budget.reserve(300 * MB, wait=0, label="preview mesh")
    # Two analyses and a price at once: their needs add; the preview reads the same mesh.
    assert small_budget.snapshot()["used_bytes"] == 800 * MB
    assert small_budget.snapshot()["used_slots"] == 1
    second.leave()
    assert small_budget.snapshot()["used_bytes"] == 500 * MB
    for h in (first, price, preview):
        h.leave()
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_a_call_that_joins_its_check_never_takes_a_second_slot(small_budget, monkeypatch):
    monkeypatch.setenv("COMPUTE_SLOTS", "2")
    a = await small_budget.reserve(100 * MB, wait=0, label="other")
    with cb.check_scope("org:1:abc"):
        probe = await small_budget.reserve(400 * MB, wait=0, label="assembly json")
        # Both slots are taken, yet the check's next call runs: it shares its check's slot.
        analysis = await small_budget.reserve(400 * MB, wait=0, label="analysis")
    with pytest.raises(cb.ComputeBusy):
        await small_budget.reserve(10 * MB, wait=0.05, label="third")
    for h in (a, probe, analysis):
        h.leave()


@pytest.mark.asyncio
async def test_a_check_waiting_for_room_waits_in_one_place_in_line(small_budget):
    held = await small_budget.reserve(800 * MB, wait=None, label="other")
    with cb.check_scope("org:1:abc"):
        preview = asyncio.create_task(small_budget.reserve(400 * MB, wait=5, label="preview mesh"))
        analysis = asyncio.create_task(small_budget.reserve(400 * MB, wait=5, label="analysis"))
    await asyncio.sleep(0.05)
    assert small_budget.snapshot()["waiting"] == 1  # one waiter, two calls
    held.leave()
    p, a = await asyncio.wait_for(asyncio.gather(preview, analysis), 2)
    assert p.reservation is a.reservation
    assert small_budget.snapshot()["used_bytes"] == 400 * MB
    p.leave()
    a.leave()
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_hold_uses_the_check_admission_named(small_budget):
    with cb.check_scope("org:1:abc"):
        async with cb.hold(400 * MB, label="preview mesh") as h1:
            async with cb.deferred_hold(label="analysis") as room:
                # A different task of the same check (a parallel call), not a nested hold.
                other = await asyncio.create_task(small_budget.reserve(400 * MB, wait=0, label="analysis"))
                assert other.reservation is h1.reservation
                other.leave()
                await room.take(400 * MB)
                assert room.reservation is h1  # nested: joins the outer hold
    assert small_budget.snapshot()["used_bytes"] == 0
    assert cb.check_key() is None


# ---------------------------------------------------------------------------
# STEP and IGES re-sized from the mesh
# ---------------------------------------------------------------------------


def _step(kb: int) -> bytes:
    return b"ISO-10303-21;\n" + b"x" * (kb * 1024)


def test_a_small_step_reserves_its_parse_then_what_its_mesh_needs():
    from src.services.stored_check_service import MEMORY_HEADROOM, STL_MEMORY_POINTS, _interp

    data = _step(30)
    assert cb.need_for_data(data, "p.step") == int(820 * MEMORY_HEADROOM * MB)  # the face-budget floor
    assert cb.parse_need_for_data(data, "p.step") == int(cb.PARSE_MEMORY_MB * MEMORY_HEADROOM * MB)
    assert cb.parse_need_for_data(data, "p.igs") == cb.parse_need_for_data(data, "p.step")
    # 149,486 faces (the 30 KB RFS-21368): sized as an STL of that many triangles.
    assert cb.need_for_mesh(149_486, len(data), "p.step") == int(
        _interp(STL_MEMORY_POINTS, 149_486) * MEMORY_HEADROOM * MB)
    # At the mesher's 250,000-face budget it is the 820 MB floor again (813 MB on the STL curve).
    assert abs(cb.need_for_mesh(250_000, len(data), "p.step") - cb.need_for_data(data, "p.step")) < 10 * MB
    # A many-body file needs at least what assemblies of its size needed.
    big = 5 * 1024 * 1024
    assert cb.need_for_mesh(100_000, big, "a.step") > cb.need_for_mesh(100_000, len(data), "a.step")
    assert cb.need_for_mesh(100_000, big, "a.stl") == cb.need_for_mesh(100_000, len(data), "a.stl")
    # STL and larger STEP files reserve the file model before the parse, as before.
    stl = b"\0" * 80 + (1000).to_bytes(4, "little") + b"\0" * 50 * 1000
    assert cb.parse_need_for_data(stl, "p.stl") == cb.need_for_data(stl, "p.stl")
    two_mb = _step(2048)
    assert cb.parse_need_for_data(two_mb, "p.step") == cb.need_for_data(two_mb, "p.step")


class _Mesh:
    def __init__(self, faces):
        self.faces = [None] * faces


@pytest.mark.asyncio
async def test_size_to_mesh_gives_back_what_a_small_mesh_doesnt_need(small_budget, monkeypatch):
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "3000")
    small_budget._refresh()
    data = _step(30)
    async with cb.hold_for_data(data, "p.step", label="analysis", provisional=True):
        assert small_budget.snapshot()["used_bytes"] == cb.parse_need_for_data(data, "p.step")
        await cb.size_to_mesh(_Mesh(20_000), data, "p.step")
        assert small_budget.snapshot()["used_bytes"] == cb.need_for_mesh(20_000, len(data), "p.step")
        assert small_budget.snapshot()["used_bytes"] < cb.parse_need_for_data(data, "p.step")
        await cb.size_to_mesh(_Mesh(149_486), data, "p.step")  # grows: there is room
        assert small_budget.snapshot()["used_bytes"] == cb.need_for_mesh(149_486, len(data), "p.step")
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_growth_waits_for_room_ahead_of_newcomers(small_budget):
    other = await small_budget.reserve(500 * MB, wait=None, label="other")
    async with cb.hold(400 * MB, label="analysis") as h:
        grow = asyncio.create_task(small_budget.resize(h, 600 * MB, wait=5))
        await asyncio.sleep(0.05)
        newcomer = asyncio.create_task(small_budget.reserve(100 * MB, wait=5, label="newcomer"))
        await asyncio.sleep(0.05)
        # 100 MB would fit (900 of 1000 used), but the growing check is ahead of it.
        assert not grow.done() and not newcomer.done()
        assert small_budget.snapshot()["used_bytes"] == 900 * MB
        other.leave()
        await asyncio.wait_for(grow, 2)
        assert h.need_bytes == 600 * MB
        n = await asyncio.wait_for(newcomer, 2)
        assert small_budget.snapshot()["used_bytes"] == 700 * MB
        n.leave()
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_growth_never_overshoots_and_answers_busy_in_time(small_budget):
    other = await small_budget.reserve(500 * MB, wait=None, label="other")
    async with cb.hold(400 * MB, label="analysis") as h:
        t0 = time.monotonic()
        with pytest.raises(cb.ComputeBusy):
            await cb.budget().resize(h, 700 * MB, wait=0.2)
        assert time.monotonic() - t0 < 1
        # It kept its old size; nothing went past the capacity.
        assert h.need_bytes == 400 * MB
        assert small_budget.snapshot()["used_bytes"] == 900 * MB
        assert small_budget.snapshot()["waiting"] == 0
    other.leave()
    # Alone, a check may grow past the budget (work bigger than the budget runs alone).
    async with cb.hold(400 * MB, label="analysis") as h:
        await small_budget.resize(h, 1500 * MB, wait=0)
        assert small_budget.snapshot()["used_bytes"] == 1500 * MB
        with pytest.raises(cb.ComputeBusy):
            await small_budget.reserve(1 * MB, wait=0.05)
    assert small_budget.snapshot()["used_bytes"] == 0


@pytest.mark.asyncio
async def test_a_busy_growth_inside_a_hold_releases_the_room(small_budget):
    other = await small_budget.reserve(700 * MB, wait=None, label="other")
    data = _step(30)
    with pytest.raises(cb.ComputeBusy):
        async with cb.hold(250 * MB, label="analysis", provisional=True):
            await cb.size_to_mesh(_Mesh(149_486), data, "p.step", wait=0.1)
    assert small_budget.snapshot()["used_bytes"] == 700 * MB
    other.leave()


@pytest.mark.asyncio
async def test_a_job_sized_by_its_file_keeps_its_size(small_budget):
    # A catalog part's or a big file's hold covers its whole job: an analysis
    # inside it re-sizes nothing (only provisional holds are sized to the mesh).
    data = _step(30)
    async with cb.hold(902 * MB, label="catalog part") as job:
        async with cb.deferred_hold(label="analysis") as room:
            await room.take_for_data(data, "p.step", provisional=True)
            await cb.size_to_mesh(_Mesh(20_000), data, "p.step")
        assert job.need_bytes == 902 * MB
        assert small_budget.snapshot()["used_bytes"] == 902 * MB


# ---------------------------------------------------------------------------
# Fairness: a retried part keeps its place in line
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retry_after_busy_resumes_its_place_ahead_of_newcomers(small_budget):
    held = await small_budget.reserve(900 * MB, wait=None, label="other")
    with cb.check_scope("org:1:big-part"):
        with pytest.raises(cb.ComputeBusy):
            await small_budget.reserve(600 * MB, wait=0.05, label="analysis")  # answered busy
    # Others arrive while the person reads the busy answer.
    newcomer = asyncio.create_task(small_budget.reserve(600 * MB, wait=5, label="newcomer"))
    await asyncio.sleep(0.05)
    with cb.check_scope("org:1:big-part"):
        retry = asyncio.create_task(small_budget.reserve(600 * MB, wait=5, label="analysis"))
    await asyncio.sleep(0.05)
    held.leave()
    first = await asyncio.wait_for(retry, 2)  # the retry goes first: it came before the newcomer
    await asyncio.sleep(0.05)
    assert not newcomer.done()
    first.leave()
    (await asyncio.wait_for(newcomer, 2)).leave()


@pytest.mark.asyncio
async def test_a_place_in_line_lasts_about_a_minute(small_budget, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(cb, "_clock", lambda: clock[0])
    held = await small_budget.reserve(900 * MB, wait=None, label="other")
    with cb.check_scope("org:1:big-part"):
        try:
            await small_budget.reserve(600 * MB, wait=0, label="analysis")
        except cb.ComputeBusy:
            pass
    ticket = small_budget._tickets["org:1:big-part"][0]
    newcomer = asyncio.create_task(small_budget.reserve(600 * MB, wait=None, label="newcomer"))
    await asyncio.sleep(0.01)
    clock[0] += cb.TICKET_SECONDS + 1  # back after the ticket expired: behind the newcomer
    with cb.check_scope("org:1:big-part"):
        late = asyncio.create_task(small_budget.reserve(600 * MB, wait=None, label="analysis"))
    await asyncio.sleep(0.01)
    seqs = [w.seq for w in small_budget._queue]
    assert seqs[0] > ticket and seqs == sorted(seqs) and len(seqs) == 2
    held.leave()
    (await asyncio.wait_for(newcomer, 2)).leave()
    (await asyncio.wait_for(late, 2)).leave()


# ---------------------------------------------------------------------------
# Interactive work before batch and catalog items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interactive_work_is_served_before_batch_items(small_budget):
    held = await small_budget.reserve(900 * MB, wait=None, label="other")
    with cb.batch_work():
        item = asyncio.create_task(small_budget.reserve(600 * MB, wait=5, label="catalog part"))
    await asyncio.sleep(0.05)
    design = asyncio.create_task(small_budget.reserve(600 * MB, wait=5, label="design generation"))
    await asyncio.sleep(0.05)
    held.leave()
    d = await asyncio.wait_for(design, 2)  # it came second, it goes first
    await asyncio.sleep(0.05)
    assert not item.done()
    d.leave()
    (await asyncio.wait_for(item, 2)).leave()


@pytest.mark.asyncio
async def test_batch_items_leave_one_slot_for_interactive_work(small_budget):
    with cb.batch_work():
        items = [await small_budget.reserve(10 * MB, wait=0, label="catalog part") for _ in range(3)]
        with pytest.raises(cb.ComputeBusy):
            await small_budget.reserve(10 * MB, wait=0.05, label="catalog part")
    # The fourth slot is there for a design, a big file's check or a kept part.
    design = await small_budget.reserve(10 * MB, wait=0, label="design generation")
    assert small_budget.snapshot()["used_slots"] == 4
    for h in items + [design]:
        h.leave()
