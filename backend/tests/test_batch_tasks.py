"""Unit tests for batch_tasks arq task functions.

Uses mocked DB sessions, analysis_service, and webhook_service.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.models import Batch, BatchItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_batch(
    ulid: str = "01BATCH00000000000001",
    user_id: int = 42,
    status: str = "processing",
    total_items: int = 3,
    completed_items: int = 0,
    failed_items: int = 0,
    concurrency_limit: int = 10,
    webhook_url: str | None = None,
) -> MagicMock:
    batch = MagicMock(spec=Batch)
    batch.id = 1
    batch.ulid = ulid
    batch.user_id = user_id
    batch.status = status
    batch.input_mode = "zip"
    batch.total_items = total_items
    batch.completed_items = completed_items
    batch.failed_items = failed_items
    batch.concurrency_limit = concurrency_limit
    batch.webhook_url = webhook_url
    batch.webhook_secret = "secret" if webhook_url else None
    batch.api_key_id = 1
    batch.started_at = None
    batch.completed_at = None
    batch.manifest_json = None
    return batch


def _make_item(
    ulid: str = "01ITEM000000000000001",
    filename: str = "part1.stl",
    status: str = "pending",
    priority: str = "normal",
) -> MagicMock:
    item = MagicMock(spec=BatchItem)
    item.id = 1
    item.ulid = ulid
    item.batch_id = 1
    item.filename = filename
    item.status = status
    item.priority = priority
    item.process_types = None
    item.rule_pack = None
    item.analysis_id = None
    item.error_message = None
    item.duration_ms = None
    item.started_at = None
    item.completed_at = None
    return item


def _mock_session_factory(session):
    """Create a mock session factory that returns an async context manager."""
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


# ---------------------------------------------------------------------------
# run_batch_coordinator
# ---------------------------------------------------------------------------


def _coordinator_execute(state):
    """Build a session.execute that routes by the compiled SQL.

    The coordinator now runs ONE poll "tick" per invocation (F-ARCH-6/#1): load
    the batch by ulid, count active items, select pending items. Tests dispatch on
    the statement shape rather than a fixed call ordering.
    """

    async def execute(stmt):
        s = str(stmt).lower()
        result = MagicMock()
        scalars = MagicMock()
        if "count(" in s:
            # active count has a `status IN (...)` clause; total count does not.
            result.scalar.return_value = state["active"] if "status" in s else state["total"]
            return result
        if "from batch_items" in s:
            scalars.all.return_value = state["pending"]
            result.scalars.return_value = scalars
            cb = state.get("on_pending")
            if cb is not None:
                cb()
            return result
        # default: batch load (SELECT ... FROM batches ...)
        scalars.first.return_value = state["batch"]
        result.scalars.return_value = scalars
        return result

    return execute


def _enqueued(mock_pool, fn_name):
    """Return the list of enqueue_job calls whose first positional arg == fn_name."""
    return [
        c for c in mock_pool.enqueue_job.call_args_list
        if c.args and c.args[0] == fn_name
    ]


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_tick_enqueues_items_and_re_enqueues_self(mock_gsf):
    """A steady-state tick drip-feeds pending items, writes a heartbeat, and
    re-enqueues *itself* (the self-re-enqueueing shape that replaces the
    while-True loop, F-ARCH-6/#1)."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(status="processing", total_items=3, completed_items=0, failed_items=0)
    pending_item = _make_item(status="pending")

    state = {"batch": batch, "total": 3, "active": 0, "pending": [pending_item]}
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    ctx = {"redis": mock_pool}

    await run_batch_coordinator(ctx, batch.ulid)

    # Item enqueued and marked queued.
    assert pending_item.status == "queued"
    assert len(_enqueued(mock_pool, "run_batch_item")) == 1
    # Heartbeat written to manifest_json (reassign-the-dict pattern).
    assert batch.manifest_json is not None and "heartbeat_at" in batch.manifest_json
    # Coordinator re-enqueued itself, deferred, for the next tick.
    self_calls = _enqueued(mock_pool, "run_batch_coordinator")
    assert len(self_calls) == 1
    assert self_calls[0].args[1] == batch.ulid
    assert self_calls[0].kwargs.get("_defer_by") == 2  # BATCH_POLL_INTERVAL_SECONDS
    # Not finalized -- work still remains.
    assert batch.status == "processing"


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_first_tick_initializes(mock_gsf):
    """First tick transitions pending -> processing, sets started_at, computes
    total_items, and re-enqueues itself."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(status="pending", total_items=0, completed_items=0, failed_items=0)
    pending_item = _make_item(status="pending")

    state = {"batch": batch, "total": 3, "active": 0, "pending": [pending_item]}
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    ctx = {"redis": mock_pool}

    await run_batch_coordinator(ctx, batch.ulid)

    assert batch.status == "processing"
    assert batch.started_at is not None
    assert batch.total_items == 3  # recomputed from the count query
    assert len(_enqueued(mock_pool, "run_batch_coordinator")) == 1


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_finalizes_and_does_not_re_enqueue(mock_gsf):
    """When every item is terminal the tick marks the batch completed and does
    NOT re-enqueue itself -- the chain stops."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(status="processing", total_items=2, completed_items=2, failed_items=0)

    state = {"batch": batch, "total": 2, "active": 0, "pending": []}
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    ctx = {"redis": mock_pool}

    await run_batch_coordinator(ctx, batch.ulid)

    assert batch.status == "completed"
    assert batch.completed_at is not None
    # No self re-enqueue: the chain terminates.
    assert _enqueued(mock_pool, "run_batch_coordinator") == []


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_empty_batch_completes(mock_gsf):
    """A pending batch with zero items finalizes to completed on the first tick."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(status="pending", total_items=0, completed_items=0, failed_items=0)

    state = {"batch": batch, "total": 0, "active": 0, "pending": []}
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    ctx = {"redis": mock_pool}

    await run_batch_coordinator(ctx, batch.ulid)

    assert batch.status == "completed"
    assert _enqueued(mock_pool, "run_batch_coordinator") == []


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_stops_on_cancel_without_overwriting(mock_gsf):
    """A cancelled batch is terminal: the tick returns immediately, does not
    overwrite the status, and does not re-enqueue."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(status="cancelled", total_items=3, completed_items=0, failed_items=0)

    state = {"batch": batch, "total": 3, "active": 0, "pending": []}
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    ctx = {"redis": mock_pool}

    await run_batch_coordinator(ctx, batch.ulid)

    assert batch.status == "cancelled"
    mock_pool.enqueue_job.assert_not_called()


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_tick_cancelled_at_arq_timeout_is_not_swallowed(mock_gsf):
    """Faithful reproduction of arq's ``asyncio.wait_for(task, job_timeout)``.

    arq/worker.py wraps every job in ``task = create_task(coro)`` +
    ``await asyncio.wait_for(task, timeout_s)`` and CANCELS the task at the
    deadline. On py3.9 ``asyncio.CancelledError`` is a ``BaseException`` -- the
    old while-True coordinator's ``except Exception`` cleanup could never catch it,
    orphaning the batch in 'processing'. The tick model designs the long-lived job
    away; this test asserts a tick that overruns the timeout is cancelled cleanly,
    does NOT fabricate a terminal status, and leaves the batch for the heartbeat
    sweeper to recover.
    """
    import asyncio

    from src.jobs.batch_tasks import run_batch_coordinator

    batch = _make_batch(status="processing", total_items=3, completed_items=0)

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    async def slow_execute(stmt):
        # Overrun the (tiny) job_timeout so wait_for cancels us mid-tick.
        await asyncio.sleep(1.0)
        result = MagicMock()
        scalars = MagicMock()
        scalars.first.return_value = batch
        result.scalars.return_value = scalars
        return result

    mock_session.execute = slow_execute
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}

    # Mirror arq/worker.py:597-599 exactly.
    task = asyncio.ensure_future(run_batch_coordinator(ctx, batch.ulid))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=0.05)

    # No except-Exception cleanup fired to fabricate a terminal status; the batch
    # is left non-terminal, and recovery is the heartbeat sweeper's job (proved in
    # test_batch_service.test_sweep_reaps_stale_heartbeat_not_fresh).
    assert batch.status == "processing"


# ---------------------------------------------------------------------------
# sweep_orphaned_batches (arq cron task)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_sweep_task_commits_when_reaped(mock_gsf):
    from src.jobs.batch_tasks import sweep_orphaned_batches

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)
    mock_session.commit = AsyncMock()

    import src.services.batch_service as bs

    with patch.object(bs, "sweep_orphaned_batches", new_callable=AsyncMock, return_value=2) as mock_sweep:
        n = await sweep_orphaned_batches({})

    assert n == 2
    mock_sweep.assert_awaited_once()
    mock_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_sweep_task_off_switch(monkeypatch):
    from src.jobs.batch_tasks import sweep_orphaned_batches

    monkeypatch.setenv("BATCH_ORPHAN_SWEEP_ENABLED", "0")
    assert await sweep_orphaned_batches({}) == 0


# ---------------------------------------------------------------------------
# run_batch_item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_item_task_calls_run_analysis(mock_gsf):
    """Item task calls analysis_service.run_analysis."""
    from src.jobs.batch_tasks import run_batch_item

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    item = _make_item(status="queued")
    batch = _make_batch()

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars = MagicMock()
        if call_count == 1:
            scalars.first.return_value = item
        elif call_count == 2:
            scalars.first.return_value = batch
        else:
            scalars.first.return_value = None
        result.scalars.return_value = scalars
        return result

    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}

    import src.services.analysis_service as _as_mod
    import src.services.batch_service as _bs_mod
    import src.services.webhook_service as _ws_mod

    with patch.object(_as_mod, "run_analysis", new_callable=AsyncMock, return_value={"verdict": "pass"}) as mock_run, \
         patch.object(_as_mod, "get_latest_analysis_id", new_callable=AsyncMock, return_value=42), \
         patch.object(_as_mod, "compute_mesh_hash", return_value="abc123"), \
         patch.object(_bs_mod, "update_batch_counters", new_callable=AsyncMock) as mock_counters, \
         patch.object(_ws_mod, "create_webhook_delivery", new_callable=AsyncMock), \
         patch("builtins.open", MagicMock(return_value=MagicMock(
             __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"stl data"))),
             __exit__=MagicMock(return_value=False),
         ))):

        await run_batch_item(ctx, "01ITEM000000000000001")

        mock_run.assert_called_once()


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_item_task_updates_counters(mock_gsf):
    """Item task calls update_batch_counters on completion."""
    from src.jobs.batch_tasks import run_batch_item

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    item = _make_item(status="queued")
    batch = _make_batch()

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars = MagicMock()
        if call_count == 1:
            scalars.first.return_value = item
        elif call_count == 2:
            scalars.first.return_value = batch
        else:
            scalars.first.return_value = None
        result.scalars.return_value = scalars
        return result

    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}

    import src.services.analysis_service as _as_mod
    import src.services.batch_service as _bs_mod
    import src.services.webhook_service as _ws_mod

    with patch.object(_as_mod, "run_analysis", new_callable=AsyncMock, return_value={"verdict": "pass"}), \
         patch.object(_as_mod, "get_latest_analysis_id", new_callable=AsyncMock, return_value=42), \
         patch.object(_as_mod, "compute_mesh_hash", return_value="abc123"), \
         patch.object(_bs_mod, "update_batch_counters", new_callable=AsyncMock) as mock_counters, \
         patch.object(_ws_mod, "create_webhook_delivery", new_callable=AsyncMock), \
         patch("builtins.open", MagicMock(return_value=MagicMock(
             __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"data"))),
             __exit__=MagicMock(return_value=False),
         ))):

        await run_batch_item(ctx, "01ITEM000000000000001")

        mock_counters.assert_called_once_with(
            mock_session, batch.id, "completed_items"
        )


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_item_completion_refreshes_batch_heartbeat(mock_gsf):
    """B1: liveness from work, not just the coordinator.

    An item that completes successfully must refresh the SAME
    manifest_json['heartbeat_at'] field the coordinator writes (via the
    real, unmocked touch_batch_heartbeat -- reassign-the-dict pattern, so
    SQLAlchemy's JSONB change detection fires). This is what keeps a batch
    alive in the sweeper's eyes even when the coordinator's own tick is
    delayed by arq pool saturation or a deploy pause.
    """
    from src.jobs.batch_tasks import run_batch_item

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    item = _make_item(status="queued")
    batch = _make_batch()
    # Simulate a coordinator heartbeat written long ago -- stale by any
    # reasonable window.
    batch.manifest_json = {"heartbeat_at": "2020-01-01T00:00:00+00:00"}

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars = MagicMock()
        if call_count == 1:
            scalars.first.return_value = item
        elif call_count == 2:
            scalars.first.return_value = batch
        else:
            scalars.first.return_value = None
        result.scalars.return_value = scalars
        return result

    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}

    import src.services.analysis_service as _as_mod
    import src.services.batch_service as _bs_mod
    import src.services.webhook_service as _ws_mod

    with patch.object(_as_mod, "run_analysis", new_callable=AsyncMock, return_value={"verdict": "pass"}), \
         patch.object(_as_mod, "get_latest_analysis_id", new_callable=AsyncMock, return_value=42), \
         patch.object(_as_mod, "compute_mesh_hash", return_value="abc123"), \
         patch.object(_bs_mod, "update_batch_counters", new_callable=AsyncMock), \
         patch.object(_ws_mod, "create_webhook_delivery", new_callable=AsyncMock), \
         patch("builtins.open", MagicMock(return_value=MagicMock(
             __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"data"))),
             __exit__=MagicMock(return_value=False),
         ))):

        await run_batch_item(ctx, "01ITEM000000000000001")

    assert batch.manifest_json["heartbeat_at"] != "2020-01-01T00:00:00+00:00"
    refreshed = datetime.fromisoformat(batch.manifest_json["heartbeat_at"])
    assert (datetime.now(timezone.utc) - refreshed).total_seconds() < 5


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_item_failure_also_refreshes_batch_heartbeat(mock_gsf):
    """B1: a FAILED item is still proof of life for the batch -- the
    heartbeat must refresh on the failure path too, not just success."""
    from src.jobs.batch_tasks import run_batch_item

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    item = _make_item(status="queued")
    batch = _make_batch()
    batch.manifest_json = {"heartbeat_at": "2020-01-01T00:00:00+00:00"}

    call_count = 0

    async def mock_execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        scalars = MagicMock()
        if call_count == 1:
            scalars.first.return_value = item
        elif call_count == 2:
            scalars.first.return_value = batch
        else:
            scalars.first.return_value = None
        result.scalars.return_value = scalars
        return result

    mock_session.execute = mock_execute
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}

    import src.services.analysis_service as _as_mod
    import src.services.batch_service as _bs_mod

    with patch.object(
        _as_mod, "run_analysis", new_callable=AsyncMock, side_effect=RuntimeError("boom")
    ), patch.object(_bs_mod, "update_batch_counters", new_callable=AsyncMock):
        await run_batch_item(ctx, "01ITEM000000000000001")

    assert item.status == "failed"
    assert batch.manifest_json["heartbeat_at"] != "2020-01-01T00:00:00+00:00"
    refreshed = datetime.fromisoformat(batch.manifest_json["heartbeat_at"])
    assert (datetime.now(timezone.utc) - refreshed).total_seconds() < 5


# ---------------------------------------------------------------------------
# dispatch_webhook
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_dispatch_webhook_retries_on_failure(mock_gsf):
    """dispatch_webhook calls schedule_webhook_retry on failure."""
    from src.jobs.batch_tasks import dispatch_webhook

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    mock_pool = AsyncMock()
    ctx = {"redis": mock_pool}

    import src.services.webhook_service as _ws_mod

    with patch.object(_ws_mod, "deliver_webhook", new_callable=AsyncMock, return_value=False) as mock_deliver, \
         patch.object(_ws_mod, "schedule_webhook_retry", new_callable=AsyncMock) as mock_retry:

        await dispatch_webhook(ctx, 42)

        mock_deliver.assert_called_once_with(mock_session, 42)
        mock_retry.assert_called_once_with(
            mock_session, 42, mock_pool
        )
