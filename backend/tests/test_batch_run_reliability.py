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
    def kicks() -> int:  # this run's kicks (other runs in the database are not this test's)
        return sum(1 for name, args, kw in pool.enqueued if name == "run_batch_coordinator" and args == (ulid,)
                   and str(kw.get("_job_id") or "").startswith("batch-coordinator-kick:"))

    # Fresh: nothing to do yet.
    await batch_tasks.rekick_batch_coordinators({"redis": pool})
    assert kicks() == 0
    # Two minutes without a tick: the cron starts a coordinator, once.
    key = batch_tasks._chain_key(ulid)
    state = json.loads(pool.kv[key])
    state["at"] -= 600
    pool.kv[key] = json.dumps(state).encode()
    await batch_tasks.rekick_batch_coordinators({"redis": pool})
    assert kicks() == 1
    await batch_tasks.rekick_batch_coordinators({"redis": pool})
    assert kicks() == 1
    pool.queue = [j for j in pool.queue if j[0] != "run_batch_coordinator" or j[1] == (ulid,)]
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


# ---------------------------------------------------------------------------
# 2. The orphan sweep recovers before it fails
# ---------------------------------------------------------------------------


async def _age_run(ulid: str, *, heartbeat_minutes: int, stuck: int = 0, manifest_extra: dict | None = None) -> None:
    """Make the run look like the incident: no heartbeat for a while, some parts stuck mid-check."""
    from sqlalchemy import text

    import src.db.engine as eng

    hb = (datetime.now(timezone.utc) - timedelta(minutes=heartbeat_minutes)).isoformat()
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text(
            "UPDATE batches SET manifest_json = manifest_json || CAST(:m AS jsonb) WHERE ulid = :u"
        ), {"u": ulid, "m": json.dumps({"heartbeat_at": hb, **(manifest_extra or {})})})
        if stuck:
            await s.execute(text(
                "UPDATE batch_items SET status = 'processing', attempt_count = 1, "
                "started_at = now() - interval '20 minutes', lease_started_at = now() - interval '20 minutes' "
                "WHERE id IN (SELECT bi.id FROM batch_items bi JOIN batches b ON b.id = bi.batch_id "
                "WHERE b.ulid = :u ORDER BY bi.id LIMIT :n)"
            ), {"u": ulid, "n": stuck})


@pytest.mark.asyncio
async def test_a_stale_run_with_its_parts_stored_is_resumed_not_failed(run_world, monkeypatch):
    from src.jobs import batch_tasks

    _install_part_check(monkeypatch)
    pool = FakeArq()
    ulid = await run_world["make_run"](6)
    await _age_run(ulid, heartbeat_minutes=15, stuck=2)

    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 0
    state = await _batch(ulid)
    assert state["status"] == "processing"
    stuck = state["items"][:2]
    assert all(i["status"] == "pending" and i["attempt_count"] == 1 for i in stuck), stuck
    resumes = state["manifest_json"]["resumes"]
    assert resumes["count"] == 1 and resumes["done"] == 0
    hb = datetime.fromisoformat(state["manifest_json"]["heartbeat_at"])
    assert datetime.now(timezone.utc) - hb < timedelta(minutes=1)
    assert [j[0] for j in pool.queue] == ["run_batch_coordinator"]

    await _drive(pool)
    state = await _batch(ulid)
    assert state["status"] == "completed" and state["completed_items"] == 6


@pytest.mark.asyncio
async def test_a_stale_run_whose_files_are_gone_stops_with_the_reason_on_each_part(run_world):
    from src.jobs import batch_tasks

    pool = FakeArq()
    ulid = await run_world["make_run"](4, blobs=False)
    await _age_run(ulid, heartbeat_minutes=15)

    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 1
    state = await _batch(ulid)
    assert state["status"] == "failed"
    assert not pool.queue
    failure = state["manifest_json"]["failure"]
    assert failure["code"] == "run_stopped" and "no longer stored" in failure["message"]
    for item in state["items"]:
        assert item["status"] == "skipped"
        assert item["error_message"].startswith("The run stopped before this part was checked: ")


@pytest.mark.asyncio
async def test_a_run_resumed_without_progress_stops_after_the_limit(run_world):
    from src.jobs import batch_tasks

    pool = FakeArq()
    ulid = await run_world["make_run"](3)
    await _age_run(ulid, heartbeat_minutes=15, manifest_extra={"resumes": {"count": 3, "done": 0}})

    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 1
    state = await _batch(ulid)
    assert state["status"] == "failed"
    assert "no progress" in state["manifest_json"]["failure"]["message"]
    assert all(i["error_message"].startswith("The run stopped before this part was checked: ")
               for i in state["items"])


@pytest.mark.asyncio
async def test_a_resumed_run_that_made_progress_starts_its_count_again(run_world):
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs import batch_tasks

    pool = FakeArq()
    ulid = await run_world["make_run"](3)
    await _age_run(ulid, heartbeat_minutes=15, manifest_extra={"resumes": {"count": 3, "done": 0}})
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("UPDATE batches SET completed_items = 1 WHERE ulid = :u"), {"u": ulid})
        await s.execute(text(
            "UPDATE batch_items SET status = 'completed' WHERE id = (SELECT min(bi.id) FROM batch_items bi "
            "JOIN batches b ON b.id = bi.batch_id WHERE b.ulid = :u)"), {"u": ulid})

    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 0
    state = await _batch(ulid)
    assert state["status"] == "processing"
    assert state["manifest_json"]["resumes"] == {**state["manifest_json"]["resumes"], "count": 1, "done": 1}


@pytest.mark.asyncio
async def test_a_stopped_run_sends_one_notification_saying_so(run_world):
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs import batch_tasks

    pool = FakeArq()
    ulid = await run_world["make_run"](4, blobs=False)
    await _age_run(ulid, heartbeat_minutes=15)
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("UPDATE batches SET completed_items = 1 WHERE ulid = :u"), {"u": ulid})
        await s.execute(text(
            "UPDATE batch_items SET status = 'completed' WHERE id = (SELECT min(bi.id) FROM batch_items bi "
            "JOIN batches b ON b.id = bi.batch_id WHERE b.ulid = :u)"), {"u": ulid})

    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 1
    await batch_tasks._notify_run_stopped(ulid)  # a second sweep, or a retry: still one
    async with eng.get_session_factory()() as s:
        rows = (await s.execute(text(
            "SELECT kind, title, body FROM notifications WHERE org_id = :o AND source_id = :u"
        ), {"o": run_world["org"], "u": ulid})).mappings().all()
    assert len(rows) == 1
    assert rows[0]["kind"] == "catalog.run_stopped"
    assert rows[0]["title"] == "Catalog run stopped - Reliability run"
    # The run page's breakdown and the reason the run kept (op-25, op-28).
    assert rows[0]["body"] == ("1 of 4 checked; 3 not checked. The run stopped before every part was checked: its "
                               "files are no longer stored, so its parts can't be checked again here. Start a new "
                               "run with them.")


# ---------------------------------------------------------------------------
# 3. "Check again" works on a stopped run (op-17)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def api(run_world, monkeypatch):
    from fastapi import FastAPI

    import src.jobs.arq_backend as arq_backend
    from src.api.batch_router import router as batch_router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key

    pool = FakeArq()

    async def _get_pool():
        return pool

    monkeypatch.setattr(arq_backend, "get_arq_pool", _get_pool)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(batch_router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=run_world["uid"], api_key_id=0, key_prefix="session", role="analyst"
    )
    return {"app": app, "pool": pool}


async def _recheck(app, ulid: str, item_ids=None):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(f"/api/v1/batch/{ulid}/catalog/recheck", json={"item_ids": item_ids} if item_ids else {})


async def _stop_run(ulid: str, *, checked: int) -> None:
    """The run as batch 23 was left: failed by the sweep, the first parts checked, the rest skipped."""
    from sqlalchemy import text

    import src.db.engine as eng

    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text(
            "UPDATE batch_items SET status = 'completed', attempt_count = 1, completed_at = now() "
            "WHERE id IN (SELECT bi.id FROM batch_items bi JOIN batches b ON b.id = bi.batch_id "
            "WHERE b.ulid = :u ORDER BY bi.id LIMIT :n)"), {"u": ulid, "n": checked})
        await s.execute(text(
            "UPDATE batch_items SET status = 'skipped', attempt_count = 2, completed_at = now(), "
            "error_message = 'The run stopped before this part was checked: x.' "
            "WHERE status = 'pending' AND batch_id = (SELECT id FROM batches WHERE ulid = :u)"), {"u": ulid})
        await s.execute(text(
            "UPDATE batches SET status = 'failed', completed_at = now(), completed_items = :n, "
            "manifest_json = manifest_json || CAST(:m AS jsonb) WHERE ulid = :u"),
            {"u": ulid, "n": checked, "m": json.dumps({
                "failure_reason": "orphaned", "resumes": {"count": 3, "done": checked},
                "failure": {"code": "run_stopped", "message": "The run stopped before every part was checked."}})})


@pytest.mark.asyncio
async def test_check_all_again_on_a_stopped_run_puts_its_parts_back_and_it_finishes(run_world, api, monkeypatch):
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs import batch_tasks

    _install_part_check(monkeypatch)
    ulid = await run_world["make_run"](5)
    await _stop_run(ulid, checked=2)
    await batch_tasks._notify_run_stopped(ulid)

    r = await _recheck(api["app"], ulid)
    assert r.status_code == 202, r.text
    body = r.json()
    assert len(body["rechecking"]) == 3 and body["status"] == "processing"
    state = await _batch(ulid)
    assert state["status"] == "processing"
    assert "failure" not in state["manifest_json"] and "failure_reason" not in state["manifest_json"]
    assert "resumes" not in state["manifest_json"]
    assert [i["status"] for i in state["items"]] == ["completed", "completed", "pending", "pending", "pending"]
    assert all(i["error_message"] is None and i["attempt_count"] == 0 for i in state["items"][2:])
    assert [j[0] for j in api["pool"].queue] == ["run_batch_coordinator"]

    await _drive(api["pool"])
    state = await _batch(ulid)
    assert state["status"] == "completed" and state["completed_items"] == 5
    # The run finished after all: its "stopped" notification is resolved, the "finished" one is open.
    async with eng.get_session_factory()() as s:
        notes = dict((await s.execute(text(
            "SELECT kind, status FROM notifications WHERE source_id = :u"), {"u": ulid})).all())
    assert notes == {"catalog.run_stopped": "resolved", "catalog.run_finished": "open"}


@pytest.mark.asyncio
async def test_check_again_on_one_part_of_a_stopped_run(run_world, api, monkeypatch):
    _install_part_check(monkeypatch)
    ulid = await run_world["make_run"](4)
    await _stop_run(ulid, checked=1)
    one = (await _batch(ulid))["items"][3]["ulid"]

    r = await _recheck(api["app"], ulid, [one])
    assert r.status_code == 202, r.text
    assert r.json()["rechecking"] == [one]
    await _drive(api["pool"])
    state = await _batch(ulid)
    assert [i["status"] for i in state["items"]] == ["completed", "skipped", "skipped", "completed"]
    assert state["status"] == "completed"


@pytest.mark.asyncio
async def test_check_again_when_the_runs_files_are_gone_says_so(run_world, api):
    ulid = await run_world["make_run"](3, blobs=False)
    await _stop_run(ulid, checked=0)

    r = await _recheck(api["app"], ulid)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "catalog_run_files_gone"
    assert "no longer stored" in detail["message"] and "never unpacked" not in detail["message"]
    assert (await _batch(ulid))["status"] == "failed"
    assert not api["pool"].queue


@pytest.mark.asyncio
async def test_check_again_on_a_run_whose_zip_was_never_unpacked(run_world, api):
    from sqlalchemy import text

    import src.db.engine as eng

    ulid = await run_world["make_run"](0, status="failed", blobs=False)
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("UPDATE batches SET input_mode = 'direct_upload' WHERE ulid = :u"), {"u": ulid})
    r = await _recheck(api["app"], ulid)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "catalog_run_not_ready"


async def _board(app, ulid: str) -> dict:
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return (await ac.get(f"/api/v1/batch/{ulid}/catalog")).json()


@pytest.mark.asyncio
async def test_a_run_the_sweep_stops_says_why_on_its_board_and_every_skipped_part_with_one_notification(run_world, api):
    """op-25: a run stopped under the new code keeps its reason, and its owner hears once."""
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs import batch_tasks

    pool = FakeArq()
    ulid = await run_world["make_run"](4, blobs=False)
    await _age_run(ulid, heartbeat_minutes=15)
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("UPDATE batches SET completed_items = 1 WHERE ulid = :u"), {"u": ulid})
        await s.execute(text(
            "UPDATE batch_items SET status = 'completed', completed_at = now() WHERE id = (SELECT min(bi.id) "
            "FROM batch_items bi JOIN batches b ON b.id = bi.batch_id WHERE b.ulid = :u)"), {"u": ulid})

    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 1
    assert await batch_tasks.sweep_orphaned_batches({"redis": pool}) == 0  # the next sweep finds it stopped
    board = await _board(api["app"], ulid)
    assert board["status"] == "failed"
    assert board["failure"]["message"] == (
        "The run stopped before every part was checked: its files are no longer stored, so its parts "
        "can't be checked again here. Start a new run with them.")
    skipped = [r for r in board["rows"] if r["bucket"] == "not_checked"]
    assert len(skipped) == 3
    for r in skipped:
        assert r["reason"] == ("The run stopped before this part was checked: the run's files are no longer "
                               "stored")
    async with eng.get_session_factory()() as s:
        notes = (await s.execute(text(
            "SELECT kind, body, metadata_json FROM notifications WHERE org_id = :o AND source_id = :u"
        ), {"o": run_world["org"], "u": ulid})).mappings().all()
    assert [n["kind"] for n in notes] == ["catalog.run_stopped"]
    assert "no longer stored" in (notes[0]["metadata_json"] or {}).get("reason", "")


@pytest.mark.asyncio
async def test_a_stale_run_that_cant_be_resumed_always_keeps_a_reason(run_world):
    """A run the sweep can't resume (not unpacked parts) stops with why, never without one."""
    from sqlalchemy import text

    import src.db.engine as eng
    from src.jobs import batch_tasks

    ulid = await run_world["make_run"](2)
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text("UPDATE batches SET input_mode = 'manifest' WHERE ulid = :u"), {"u": ulid})
    await _age_run(ulid, heartbeat_minutes=15)
    assert await batch_tasks.sweep_orphaned_batches({"redis": FakeArq()}) == 1
    state = await _batch(ulid)
    assert state["manifest_json"]["failure"] == {
        "code": "run_stopped",
        "message": "The run stopped before every part was checked: its worker stopped and the run couldn't be "
                   "resumed. Check the parts again."}


@pytest.mark.asyncio
async def test_a_run_the_old_code_stopped_says_it_kept_no_reason(run_world, api):
    """op-25: batch 23 was stopped before runs kept a reason; its parts say so instead of "Skipped"."""
    from sqlalchemy import text

    import src.db.engine as eng

    ulid = await run_world["make_run"](3)
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text(
            "UPDATE batch_items SET status = 'skipped', completed_at = now(), error_message = NULL "
            "WHERE batch_id = (SELECT id FROM batches WHERE ulid = :u)"), {"u": ulid})
        await s.execute(text(
            "UPDATE batches SET status = 'failed', completed_at = now(), "
            "manifest_json = manifest_json || '{\"failure_reason\": \"orphaned\"}'::jsonb WHERE ulid = :u"), {"u": ulid})
    board = await _board(api["app"], ulid)
    assert board["failure"] is None
    assert {r["reason"] for r in board["rows"]} == {"The run stopped before ScaleCAD kept a reason"}


@pytest.mark.asyncio
async def test_the_board_the_progress_read_and_the_run_list_count_the_files_one_way(run_world, api):
    """op-28: with a parts list, the run's counts cover the list's files and name the rest apart."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng

    ulid = await run_world["make_run"](5)
    meta = {"parts_list": {"name": "list.csv", "rows": 4, "matched": 4, "unmatched": 0},
            "items": {f"part-{i:03d}.stl": {"row": i + 2} for i in range(4)}}
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text(
            "UPDATE batches SET manifest_json = jsonb_set(manifest_json, '{catalog}', "
            "(manifest_json->'catalog') || CAST(:m AS jsonb)) WHERE ulid = :u"), {"u": ulid, "m": json.dumps(meta)})
    await _stop_run(ulid, checked=1)
    want = {"total": 4, "checked": 1, "not_checked": 3, "to_go": 0, "checking": 0,
            "unlisted": 1, "unlisted_checked": 0, "unlisted_not_checked": 1, "unlisted_to_go": 0}
    async with AsyncClient(transport=ASGITransport(app=api["app"]), base_url="http://test") as ac:
        board = (await ac.get(f"/api/v1/batch/{ulid}/catalog")).json()
        progress = (await ac.get(f"/api/v1/batch/{ulid}")).json()
        listed = (await ac.get("/api/v1/batches")).json()
    assert board["run_counts"] == want
    assert progress["run_counts"] == want
    assert next(b for b in listed["batches"] if b["batch_ulid"] == ulid)["run_counts"] == want


# ---------------------------------------------------------------------------
# 4. Honest status: the time left comes from the measured pace (op-11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_carries_the_measured_pace_and_the_time_left(run_world):
    from sqlalchemy import text

    import src.db.engine as eng
    from src.services import batch_service

    ulid = await run_world["make_run"](10)
    # Four parts finished over the last 8 minutes (2 s, 2, 5 and 8 min ago): 4 in 8 min = 30 an hour.
    async with eng.get_session_factory()() as s, s.begin():
        await s.execute(text(
            "UPDATE batch_items SET status = 'completed', completed_at = now() - (interval '1 minute' * m.mins) "
            "FROM (SELECT bi.id, (ARRAY[8, 5, 2, 0.03])[row_number() OVER (ORDER BY bi.id)] AS mins "
            "      FROM batch_items bi JOIN batches b ON b.id = bi.batch_id WHERE b.ulid = :u ORDER BY bi.id LIMIT 4) m "
            "WHERE batch_items.id = m.id"), {"u": ulid})
        await s.execute(text("UPDATE batches SET completed_items = 4 WHERE ulid = :u"), {"u": ulid})
    async with eng.get_session_factory()() as s:
        p = await batch_service.get_batch_progress(s, ulid, run_world["uid"])
    assert p["completed_items"] == 4 and p["pending_items"] == 6
    assert p["pace_per_hour"] == pytest.approx(30, rel=0.05)
    assert p["eta_seconds"] == pytest.approx(6 / 30 * 3600, rel=0.05)


@pytest.mark.asyncio
async def test_no_time_left_until_the_pace_is_measured(run_world):
    from src.services import batch_service

    import src.db.engine as eng

    ulid = await run_world["make_run"](10)
    async with eng.get_session_factory()() as s:
        p = await batch_service.get_batch_progress(s, ulid, run_world["uid"])
    assert p["pace_per_hour"] is None and p["eta_seconds"] is None


# ---------------------------------------------------------------------------
# A batch item is priced at the org's published rate card, as a single check is
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cost_batch_item_is_priced_at_the_orgs_published_rate_card(run_world, monkeypatch):
    import copy

    import trimesh
    from sqlalchemy import select

    import src.db.engine as eng
    from src.costing.rates import RATE_CARD_V0
    from src.db.models import Batch, BatchItem, CostDecision, RateCardVersion
    from src.jobs import batch_tasks
    from src.services import batch_service, rate_library_service

    monkeypatch.setenv("RATE_LIBRARY_ENABLED", "1")
    org, uid = run_world["org"], run_world["uid"]
    rate_library_service.invalidate(org)
    v1 = copy.deepcopy(RATE_CARD_V0)
    v1["global"]["labor_rate"] = float(RATE_CARD_V0["global"]["labor_rate"]) + 23.0
    ulid = await run_world["make_run"](1, blobs=False)
    name = "part-000.stl"
    batch_service._batch_store().put(
        batch_service._batch_key(ulid, name), trimesh.creation.box(extents=(60, 40, 20)).export(file_type="stl")
    )
    async with eng.get_session_factory()() as s, s.begin():
        s.add(RateCardVersion(org_id=org, version=1, name="v1", status="published", payload=v1,
                              effective_from=datetime.now(timezone.utc) - timedelta(minutes=5)))
        b = (await s.execute(select(Batch).where(Batch.ulid == ulid))).scalar_one()
        b.job_type = "cost"
        item = (await s.execute(select(BatchItem).where(BatchItem.batch_id == b.id))).scalar_one()
        item.status = "processing"
        item.material_class = "aluminum"
        item.quantities = "100"

    async with eng.get_session_factory()() as s:
        b = (await s.execute(select(Batch).where(Batch.ulid == ulid))).scalar_one()
        item = (await s.execute(select(BatchItem).where(BatchItem.batch_id == b.id))).scalar_one()
        extra = await batch_tasks._run_cost_item(s, b, item)
    assert extra["cost_decision_id"]
    async with eng.get_session_factory()() as s:
        rec = (await s.execute(select(CostDecision).where(CostDecision.ulid == extra["cost_decision_id"]))).scalar_one()
    assert (rec.result_json.get("rate_card") or {}).get("version") == 1
    # The labor rate it used is the card's, not the engine's typical one.
    labor = [a for a in rec.result_json.get("assumptions") or [] if a.get("name") == "labor_rate"]
    assert labor and float(labor[0]["value"]) == v1["global"]["labor_rate"], labor
    rate_library_service.invalidate(org)
