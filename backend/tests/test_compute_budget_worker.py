"""A catalog run in the worker's compute budget: an abandoned part's thread keeps its room.

Against live Postgres with the real coordinator, item task and catalog-part
wrapper (the run's state machine and the budget are real; the part's engine
work is a stand-in that computes in an executor thread, as the engine does).

Skipped unless DATABASE_URL is PostgreSQL at schema head.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest

from src.services import compute_budget
from tests.test_batch_run_reliability import FakeArq, _batch, _drive, _PG, run_world  # noqa: F401

pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")


def _install_compute(monkeypatch, *, slow_first: set[str] = frozenset(), slow_s: float = 1.0, limit_s: float = 0.2):
    """``_check_catalog_part`` stood in by an executor computation under the part's time limit.

    The first try of each name in ``slow_first`` runs ``slow_s`` seconds, past
    its ``limit_s`` limit: the await gives up (the part is checked again after
    the rest of the run) while its thread runs on, as a real parse or price does.
    """
    from src.jobs import batch_tasks
    from src.services import batch_service

    log: list[tuple[str, int, float, float]] = []
    tries: dict[str, int] = {}
    lock = threading.Lock()

    async def fake_check(session, batch, item, file_bytes, user, **kw):
        name = kw["item_filename"]
        n = tries[name] = tries.get(name, 0) + 1
        slow = name in slow_first and n == 1

        def compute():
            t0 = time.monotonic()
            time.sleep(slow_s if slow else 0.05)
            with lock:
                log.append((name, n, t0, time.monotonic()))

        try:
            await compute_budget.run_within_budget(compute, timeout=limit_s, label=name)
        except asyncio.TimeoutError as exc:
            raise batch_tasks.CatalogPartTimedOut("ran past its time limit") from exc
        await session.refresh(item)
        await session.refresh(batch)
        item.status = "completed"
        item.completed_at = datetime.now(timezone.utc)
        item.lease_started_at = None
        await batch_service.update_batch_counters(session, batch.id, "completed_items")
        batch_service.touch_batch_heartbeat(batch)
        await session.commit()
        return {}

    monkeypatch.setattr(batch_tasks, "_check_catalog_part", fake_check)
    return log, tries


async def _settled(timeout: float = 5.0) -> dict:
    """The budget once every thread has ended."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = compute_budget.budget().snapshot()
        if snap["running"] == 0:
            return snap
        await asyncio.sleep(0.02)
    return compute_budget.budget().snapshot()


@pytest.mark.asyncio
async def test_the_next_part_waits_until_a_timed_out_part_really_ends(run_world, monkeypatch):
    # One tiny part needs ~165 MB in the memory model: 200 MB holds one at a time.
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "200")
    log, tries = _install_compute(monkeypatch, slow_first={"part-000.stl"})
    pool = FakeArq()
    ulid = await run_world["make_run"](3)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool)

    state = await _batch(ulid)
    assert state["status"] == "completed", state
    assert all(i["status"] == "completed" for i in state["items"]), state["items"]
    # The part that ran past its limit was checked again, after the rest of the run.
    assert tries == {"part-000.stl": 2, "part-001.stl": 1, "part-002.stl": 1}
    # Its first thread ran on after the await gave up; nothing computed beside it,
    # its own retry included: the computations never overlap.
    runs = sorted(log, key=lambda r: r[2])
    first = next(r for r in runs if r[0] == "part-000.stl" and r[1] == 1)
    assert first[3] - first[2] >= 0.9
    for before, after in zip(runs, runs[1:]):
        assert after[2] >= before[3] - 0.01, (before, after)
    nxt = next(r for r in runs if r[0] == "part-001.stl")
    assert nxt[2] >= first[3] - 0.01
    snap = await _settled()
    assert snap["used_bytes"] == 0 and snap["running"] == 0


@pytest.mark.asyncio
async def test_a_retry_runs_beside_its_abandoned_try_only_when_both_fit(run_world, monkeypatch):
    # Room for two tiny parts: the retry may run beside its first try, never a third.
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "340")
    peak = {"running": 0}
    real_reserve = compute_budget.ComputeBudget.reserve

    async def watching(self, need_bytes, *, wait, label="cad"):
        res = await real_reserve(self, need_bytes, wait=wait, label=label)
        peak["running"] = max(peak["running"], self.snapshot()["running"])
        assert self.snapshot()["used_bytes"] <= 340 * compute_budget.MB
        return res

    monkeypatch.setattr(compute_budget.ComputeBudget, "reserve", watching)
    log, tries = _install_compute(monkeypatch, slow_first={"part-000.stl", "part-001.stl"}, slow_s=0.8)
    pool = FakeArq()
    ulid = await run_world["make_run"](3)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool)

    state = await _batch(ulid)
    assert state["status"] == "completed", state
    assert tries["part-000.stl"] == 2 and tries["part-001.stl"] == 2
    assert peak["running"] <= 2
    await _settled()


@pytest.mark.asyncio
async def test_a_part_with_no_room_in_its_wait_goes_back_without_spending_a_try(run_world, monkeypatch):
    from src.jobs import batch_tasks

    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "200")
    monkeypatch.setattr(batch_tasks, "_item_wait_seconds", lambda work_seconds: 0.2)
    log, tries = _install_compute(monkeypatch)
    # Other work holds the whole budget for the part's first two deliveries.
    other = await compute_budget.budget().reserve(200 * compute_budget.MB, wait=None, label="other work")
    deliveries = {"n": 0}

    def before(name, _args, _kwargs):
        if name == "run_batch_item":
            deliveries["n"] += 1
            if deliveries["n"] == 3:
                other.leave()

    pool = FakeArq()
    ulid = await run_world["make_run"](1)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool, before_job=before)

    state = await _batch(ulid)
    item = state["items"][0]
    assert state["status"] == "completed", state
    assert item["status"] == "completed"
    assert deliveries["n"] == 3
    # Two deliveries found no room and went back; only the one that ran is a try.
    assert item["attempt_count"] == 1
    assert tries == {"part-000.stl": 1}


@pytest.mark.asyncio
async def test_catalog_parts_are_batch_work_in_the_budget(run_world, monkeypatch):
    from src.jobs import batch_tasks

    seen = []
    log, tries = _install_compute(monkeypatch)
    real = batch_tasks._check_catalog_part

    async def recording(*a, **kw):
        seen.append(compute_budget._PRIORITY.get())
        return await real(*a, **kw)

    monkeypatch.setattr(batch_tasks, "_check_catalog_part", recording)
    pool = FakeArq()
    ulid = await run_world["make_run"](2)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool)
    assert (await _batch(ulid))["status"] == "completed"
    assert seen and set(seen) == {compute_budget.BATCH}
    # The job's priority stays with its own task: the worker's other work is interactive.
    assert compute_budget._PRIORITY.get() == compute_budget.INTERACTIVE


@pytest.mark.asyncio
async def test_batch_items_leave_job_slots_for_interactive_jobs(run_world, monkeypatch):
    from src.jobs import batch_tasks

    monkeypatch.setenv("BATCH_ITEM_JOB_SLOTS", "1")
    log, tries = _install_compute(monkeypatch)
    deliveries = {"n": 0}

    def before(name, _args, _kwargs):
        # Another batch item holds the worker's one batch slot for the first two deliveries.
        if name == "run_batch_item":
            deliveries["n"] += 1
            batch_tasks._ITEMS_IN_FLIGHT = 1 if deliveries["n"] <= 2 else 0

    pool = FakeArq()
    ulid = await run_world["make_run"](1)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    try:
        await _drive(pool, before_job=before)
    finally:
        batch_tasks._ITEMS_IN_FLIGHT = 0
    state = await _batch(ulid)
    item = state["items"][0]
    assert state["status"] == "completed", state
    assert deliveries["n"] == 3
    # Two deliveries found every batch slot taken and went back; only the one that ran is a try.
    assert item["attempt_count"] == 1
    assert tries == {"part-000.stl": 1}


def test_batch_item_slots_default_to_max_jobs_less_the_interactive_ones(monkeypatch):
    from src.jobs import batch_tasks
    from src.jobs.worker import WorkerSettings

    monkeypatch.delenv("BATCH_ITEM_JOB_SLOTS", raising=False)
    assert batch_tasks.batch_item_job_slots() == WorkerSettings.max_jobs - batch_tasks.INTERACTIVE_JOB_SLOTS
    monkeypatch.setenv("BATCH_ITEM_JOB_SLOTS", "0")
    assert batch_tasks.batch_item_job_slots() == 1


@pytest.mark.asyncio
async def test_jobs_a_person_waits_for_are_queued_ahead_of_batch_items(monkeypatch):
    """arq starts due jobs in score order; a design or a big file's check is queued an hour early."""
    from datetime import timedelta

    from src.jobs import arq_backend
    from src.services import design_service

    calls = []

    class _Pool:
        async def enqueue_job(self, name, *args, **kw):
            calls.append((name, kw))
            return object()

    async def _pool():
        return _Pool()

    monkeypatch.setattr(arq_backend, "get_arq_pool", _pool)

    class _Job:
        ulid = "01DESIGNJOBULID0000000000A"

    before = datetime.now(timezone.utc)
    await design_service._enqueue(_Job())
    name, kw = calls[-1]
    assert name == "run_design_generation_job"
    assert kw["_defer_until"] <= before - timedelta(minutes=59)
    assert arq_backend.INTERACTIVE_JOB_TYPES >= {"design_generation", "stored_check"}
    assert "sam3d" not in arq_backend.INTERACTIVE_JOB_TYPES
