"""A catalog run survives load: a transient failure never ends it.

Against live Postgres (the real coordinator, item task, orphan sweep and
re-check endpoint), with an in-memory stand-in for the arq queue that keeps
arq's own rules: a job id already queued (or recently finished) is not queued
again. The item's engine work is a stand-in; the run's state machine is real.

Skipped unless DATABASE_URL is PostgreSQL at schema head.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = pytest.mark.skipif(not _PG, reason="requires PostgreSQL at schema head (DATABASE_URL=postgresql://...)")


class FakeArq:
    """The parts of ArqRedis the batch tasks use: get/set and enqueue_job with job-id dedup."""

    def __init__(self):
        self.kv: dict[str, bytes] = {}
        self.queue: list[tuple[str, tuple, dict]] = []
        self.ids: set[str] = set()
        self.enqueued: list[tuple[str, tuple, dict]] = []

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ex=None, **_kw):
        self.kv[key] = value.encode() if isinstance(value, str) else value
        return True

    async def enqueue_job(self, name, *args, _job_id=None, _defer_by=None, **kwargs):
        if _job_id is not None and _job_id in self.ids:
            return None
        if _job_id is not None:
            self.ids.add(_job_id)
        self.queue.append((name, args, kwargs))
        self.enqueued.append((name, args, {**kwargs, "_defer_by": _defer_by, "_job_id": _job_id}))
        return object()


@pytest_asyncio.fixture
async def run_world(monkeypatch, tmp_path):
    """An org, a pilot user and a helper that makes a catalog run of N stored parts."""
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    monkeypatch.setenv("OBJECT_STORE_LOCAL_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("BATCH_BLOB_DIR", str(tmp_path / "batch"))
    await eng.dispose_engine()
    tag = uuid.uuid4().hex[:10]
    org = str(ULID())
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"),
                        {"id": org, "n": f"reliab-{tag}"})
        uid = (await s.execute(text(
            "INSERT INTO users (email, email_lower, role, auth_provider, plan, phone_verified_at, current_org_id) "
            "VALUES (:e, :e, 'analyst', 'password', 'pilot', now(), :o) RETURNING id"
        ), {"e": f"pilot-{tag}@acme-aero.com", "o": org})).scalar_one()
        await s.execute(text(
            "INSERT INTO memberships (id, org_id, user_id, org_role, created_at) VALUES (:id, :o, :u, 'admin', now())"
        ), {"id": str(ULID()), "o": org, "u": uid})

    async def make_run(n: int, *, status: str = "processing", blobs: bool = True, concurrency: int = 3) -> str:
        from src.db.models import Batch, BatchItem
        from src.services import batch_service

        ulid = str(ULID())
        names = [f"part-{i:03d}.stl" for i in range(n)]
        if blobs:
            store = batch_service._batch_store()
            for name in names:
                store.put(batch_service._batch_key(ulid, name), f"solid {name}\nendsolid\n".encode())
        async with eng.get_session_factory()() as s, s.begin():
            batch = Batch(ulid=ulid, user_id=uid, org_id=org, input_mode="zip", job_type="catalog",
                          status=status, total_items=n, concurrency_limit=concurrency,
                          started_at=datetime.now(timezone.utc) if status != "pending" else None,
                          manifest_json={"catalog": {"free": False, "name": "Reliability run", "quantity": 100}})
            s.add(batch)
            await s.flush()
            for name in names:
                s.add(BatchItem(batch_id=batch.id, org_id=org, filename=name, status="pending", priority="normal"))
        return ulid

    try:
        yield {"org": org, "uid": uid, "make_run": make_run}
    finally:
        async with eng.get_session_factory()() as s, s.begin():
            await s.execute(text("DELETE FROM notifications WHERE org_id = :o"), {"o": org})
            await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
            await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await eng.dispose_engine()


async def _batch(ulid: str) -> dict:
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        row = (await s.execute(text(
            "SELECT id, status, total_items, completed_items, failed_items, manifest_json FROM batches WHERE ulid = :u"
        ), {"u": ulid})).mappings().one()
        items = (await s.execute(text(
            "SELECT ulid, filename, status, attempt_count, error_message FROM batch_items WHERE batch_id = :b ORDER BY id"
        ), {"b": row["id"]})).mappings().all()
    return {**dict(row), "items": [dict(i) for i in items]}


def _install_part_check(monkeypatch, *, cancel_once: set[str] | None = None):
    """The engine's part check, stood in: completes the item like _check_catalog_part does.

    ``cancel_once``: filenames whose first try is cancelled mid-check (the arq
    job timeout), as in the incident.
    """
    from src.jobs import batch_tasks
    from src.services import batch_service

    cancelled: set[str] = set()

    async def fake_part(session, batch, item):
        name = item.filename
        if cancel_once and name in cancel_once and name not in cancelled:
            cancelled.add(name)
            raise asyncio.CancelledError()
        await session.refresh(item)
        await session.refresh(batch)
        item.status = "completed"
        item.completed_at = datetime.now(timezone.utc)
        item.lease_started_at = None
        await batch_service.update_batch_counters(session, batch.id, "completed_items")
        batch_service.touch_batch_heartbeat(batch)
        await session.commit()
        return {}

    monkeypatch.setattr(batch_tasks, "_run_catalog_item", fake_part)
    return cancelled


async def _drive(pool: FakeArq, *, max_jobs: int = 400, before_job=None) -> list[str]:
    """Run queued jobs in order, the way one arq worker would (errors are logged, not raised)."""
    from src.jobs import batch_tasks

    ran: list[str] = []
    while pool.queue and len(ran) < max_jobs:
        name, args, kwargs = pool.queue.pop(0)
        if before_job is not None:
            before_job(name, args, kwargs)
        fn = getattr(batch_tasks, name)
        try:
            await fn({"redis": pool, "job_try": 1}, *args, **kwargs)
        except (Exception, asyncio.CancelledError):
            pass
        ran.append(name)
    return ran


def _inject_db_timeout(monkeypatch):
    """Make the next session the coordinator opens time out on connect (asyncpg's TimeoutError)."""
    from src.jobs import batch_tasks

    real = batch_tasks.get_session_factory
    armed = {"coordinator": False, "fired": 0}

    class _TimingOut:
        async def __aenter__(self):
            armed["coordinator"] = False
            armed["fired"] += 1
            raise TimeoutError()

        async def __aexit__(self, *exc):
            return False

    def factory():
        inner = real()
        if armed["coordinator"]:
            return lambda: _TimingOut()
        return inner

    monkeypatch.setattr(batch_tasks, "get_session_factory", factory)
    return armed


# ---------------------------------------------------------------------------
# 1. A transient failure never ends a run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_coordinator_db_timeout_mid_run_does_not_end_the_run(run_world, monkeypatch):
    _install_part_check(monkeypatch)
    armed = _inject_db_timeout(monkeypatch)
    pool = FakeArq()
    ulid = await run_world["make_run"](9, status="pending")
    await pool.enqueue_job("run_batch_coordinator", ulid)

    ticks = {"n": 0}

    def before(name, _args, _kwargs):
        if name == "run_batch_coordinator":
            ticks["n"] += 1
            if ticks["n"] == 3:  # mid-run: some parts checked, most still to go
                armed["coordinator"] = True

    await _drive(pool, before_job=before)
    state = await _batch(ulid)
    assert armed["fired"] == 1
    assert state["status"] == "completed", state
    assert state["completed_items"] == 9
    assert all(i["status"] == "completed" for i in state["items"])
    # One coordinator chain carried the run, through the failed tick.
    chains = {kw.get("chain") for name, _a, kw in pool.enqueued if name == "run_batch_coordinator" and kw.get("chain")}
    assert len(chains) == 1


@pytest.mark.asyncio
async def test_a_cancelled_coordinator_tick_keeps_the_chain(run_world, monkeypatch):
    """arq cancels a tick at job_timeout (or a worker restart): the next tick is already queued."""
    from src.jobs import batch_tasks

    _install_part_check(monkeypatch)
    pool = FakeArq()
    ulid = await run_world["make_run"](4)
    real_tick = batch_tasks._coordinator_tick
    calls = {"n": 0}

    async def tick(ctx, batch_ulid):
        calls["n"] += 1
        if calls["n"] == 2:
            raise asyncio.CancelledError()
        return await real_tick(ctx, batch_ulid)

    monkeypatch.setattr(batch_tasks, "_coordinator_tick", tick)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool)
    state = await _batch(ulid)
    assert state["status"] == "completed", state


@pytest.mark.asyncio
async def test_a_superseded_chain_stops_and_a_rerun_tick_does_not_fork_the_chain(run_world, monkeypatch):
    from src.jobs import batch_tasks

    pool = FakeArq()
    ulid = await run_world["make_run"](3)
    await batch_tasks.run_batch_coordinator({"redis": pool}, ulid)
    first = [j for j in pool.enqueued if j[0] == "run_batch_coordinator"]
    assert len(first) == 1 and first[0][2]["chain"]
    chain, seq = first[0][2]["chain"], first[0][2]["seq"]
    # The same tick delivered again (arq re-runs a tick cancelled at shutdown): no second next tick.
    await batch_tasks.run_batch_coordinator({"redis": pool}, ulid, chain=chain, seq=seq - 1)
    assert len([j for j in pool.enqueued if j[0] == "run_batch_coordinator"]) == 1
    # A new chain (a kick or a resume) takes over; the old chain's next tick stops.
    await batch_tasks.run_batch_coordinator({"redis": pool}, ulid)
    before = len(pool.enqueued)
    await batch_tasks.run_batch_coordinator({"redis": pool}, ulid, chain=chain, seq=seq)
    assert len(pool.enqueued) == before


@pytest.mark.asyncio
async def test_the_minute_cron_restarts_a_run_whose_coordinator_is_gone(run_world, monkeypatch):
    from src.jobs import batch_tasks

    _install_part_check(monkeypatch)
    pool = FakeArq()
    ulid = await run_world["make_run"](5)
    await batch_tasks.run_batch_coordinator({"redis": pool}, ulid)
    # The chain's next tick is lost (Redis restarted, a publish failed); the parts' jobs are not.
    pool.queue = [j for j in pool.queue if j[0] != "run_batch_coordinator"]
    # Fresh: nothing to do yet.
    assert await batch_tasks.rekick_batch_coordinators({"redis": pool}) == 0
    # Two minutes without a tick: the cron starts a coordinator, once.
    key = batch_tasks._chain_key(ulid)
    state = json.loads(pool.kv[key])
    state["at"] -= 600
    pool.kv[key] = json.dumps(state).encode()
    assert await batch_tasks.rekick_batch_coordinators({"redis": pool}) == 1
    assert await batch_tasks.rekick_batch_coordinators({"redis": pool}) == 0
    await _drive(pool)
    assert (await _batch(ulid))["status"] == "completed"


@pytest.mark.asyncio
async def test_a_cancelled_part_is_checked_again_with_the_attempt_counted(run_world, monkeypatch):
    cancelled = _install_part_check(monkeypatch, cancel_once={"part-001.stl"})
    pool = FakeArq()
    ulid = await run_world["make_run"](3)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool)
    state = await _batch(ulid)
    assert cancelled == {"part-001.stl"}
    assert state["status"] == "completed"
    part = next(i for i in state["items"] if i["filename"] == "part-001.stl")
    assert part["status"] == "completed" and part["attempt_count"] == 2


@pytest.mark.asyncio
async def test_a_part_stopped_every_try_fails_with_a_plain_reason(run_world, monkeypatch):
    from src.jobs import batch_tasks

    async def always_cancelled(session, batch, item):
        raise asyncio.CancelledError()

    monkeypatch.setattr(batch_tasks, "_run_catalog_item", always_cancelled)
    pool = FakeArq()
    ulid = await run_world["make_run"](1)
    await pool.enqueue_job("run_batch_coordinator", ulid)
    await _drive(pool)
    state = await _batch(ulid)
    item = state["items"][0]
    assert state["status"] == "completed"
    assert item["status"] == "failed" and item["attempt_count"] == 3
    assert "stopped before it finished" in item["error_message"]
    assert "database" not in item["error_message"].lower()
