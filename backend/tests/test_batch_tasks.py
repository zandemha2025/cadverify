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

    The coordinator now opens a fresh session per poll (F-ARCH-6) and re-queries
    the batch by id instead of session.refresh(), so tests dispatch on the
    statement shape rather than a fixed call ordering.
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


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_enqueues_items(mock_gsf):
    """Coordinator enqueues pending items up to the concurrency limit."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(total_items=3, completed_items=0, failed_items=0)
    pending_item = _make_item(status="pending")

    def _mark_all_done():
        # Once we've handed out the pending item, the batch reaches completion so
        # the next poll breaks the loop.
        batch.completed_items = 3

    state = {
        "batch": batch,
        "total": 3,
        "active": 0,
        "pending": [pending_item],
        "on_pending": _mark_all_done,
    }
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    ctx = {"redis": mock_pool}

    with patch("src.jobs.batch_tasks.asyncio.sleep", new_callable=AsyncMock):
        await run_batch_coordinator(ctx, "01BATCH00000000000001")

    mock_pool.enqueue_job.assert_called()
    assert pending_item.status == "queued"
    assert batch.status == "completed"


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_completes_when_all_done(mock_gsf):
    """Batch status set to completed when all items are already done."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(total_items=2, completed_items=2, failed_items=0)

    state = {"batch": batch, "total": 2, "active": 0, "pending": []}
    mock_session.execute = _coordinator_execute(state)
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}

    with patch("src.jobs.batch_tasks.asyncio.sleep", new_callable=AsyncMock):
        await run_batch_coordinator(ctx, batch.ulid)

    assert batch.status == "completed"


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_exits_on_cancel(mock_gsf):
    """Cancelled batch: coordinator exits without overwriting the status."""
    from src.jobs.batch_tasks import run_batch_coordinator

    mock_session = AsyncMock()
    mock_gsf.return_value = _mock_session_factory(mock_session)

    batch = _make_batch(total_items=3, completed_items=0, failed_items=0)

    def _cancel_after_init():
        batch.status = "cancelled"

    # Flip to cancelled right after phase-1 total count, so the first poll sees it.
    state = {
        "batch": batch,
        "total": 3,
        "active": 0,
        "pending": [],
    }

    orig = _coordinator_execute(state)

    seen_total = {"done": False}

    async def execute(stmt):
        res = await orig(stmt)
        s = str(stmt).lower()
        if "count(" in s and "status" not in s and not seen_total["done"]:
            seen_total["done"] = True
            batch.status = "cancelled"
        return res

    mock_session.execute = execute
    mock_session.commit = AsyncMock()

    ctx = {"redis": AsyncMock()}
    with patch("src.jobs.batch_tasks.asyncio.sleep", new_callable=AsyncMock):
        await run_batch_coordinator(ctx, batch.ulid)

    assert batch.status == "cancelled"


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
