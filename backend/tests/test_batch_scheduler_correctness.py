"""Focused proof for batch admission, ordering, retry, and recovery branches."""
from __future__ import annotations

import asyncio
import errno
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq import Retry
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, OperationalError

from src.db.models import Batch, BatchItem
from src.jobs import batch_tasks
from src.services import batch_service
from src.storage.base import ObjectNotFoundError


def _result(*, first=None, all_rows=None, scalar=None):
    result = MagicMock()
    result.scalar.return_value = scalar
    result.scalars.return_value.first.return_value = first
    result.scalars.return_value.all.return_value = all_rows or []
    return result


def _session_factory(session):
    context = AsyncMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=context)


def _batch(*, status="processing", concurrency_limit=3):
    return SimpleNamespace(
        id=1,
        ulid="01BATCHSCHEDULER000001",
        user_id=42,
        org_id="01ORG",
        api_key_id=1,
        status=status,
        input_mode="zip",
        job_type="dfm",
        total_items=3,
        completed_items=0,
        failed_items=0,
        concurrency_limit=concurrency_limit,
        webhook_url=None,
        webhook_secret=None,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        manifest_json=None,
    )


def _item(identifier: int, priority="normal", status="pending", attempts=0):
    return SimpleNamespace(
        id=identifier,
        ulid=f"01ITEMSCHEDULER{identifier:06d}",
        batch_id=1,
        filename=f"part-{identifier}.stl",
        status=status,
        priority=priority,
        attempt_count=attempts,
        lease_started_at=None,
        process_types=None,
        rule_pack=None,
        analysis_id=None,
        error_message=None,
        duration_ms=None,
        created_at=datetime(2026, 7, 14, 12, 0, identifier, tzinfo=timezone.utc),
        started_at=None,
        completed_at=None,
    )


@pytest.mark.parametrize("value", [1, 12])
def test_concurrency_bounds_accept_both_edges(value):
    assert batch_service.validate_batch_concurrency_limit(value) == value


@pytest.mark.parametrize("value", [0, -1, 13, True])
def test_concurrency_bounds_reject_every_out_of_contract_value(value):
    with pytest.raises(ValueError, match="concurrency_limit"):
        batch_service.validate_batch_concurrency_limit(value)


def test_concurrency_none_uses_validated_default():
    assert batch_service.validate_batch_concurrency_limit(None) == 10


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_coordinator_uses_explicit_priority_rank_and_stable_tiebreakers(mock_gsf):
    batch = _batch()
    items = [_item(1, "high"), _item(2, "normal"), _item(3, "low")]
    session = AsyncMock()
    statements = []

    async def execute(stmt):
        statements.append(stmt)
        sql = str(stmt).lower()
        if "from batches" in sql:
            return _result(first=batch)
        if "count(" in sql:
            return _result(scalar=0)
        if "from batch_items" in sql and "coalesce" in sql:
            return _result(all_rows=[])
        if "from batch_items" in sql:
            return _result(all_rows=items)
        return _result()

    session.execute.side_effect = execute
    mock_gsf.return_value = _session_factory(session)
    pool = AsyncMock()

    await batch_tasks.run_batch_coordinator({"redis": pool}, batch.ulid)

    pending_stmt = next(
        stmt
        for stmt in statements
        if "from batch_items" in str(stmt).lower()
        and "coalesce" not in str(stmt).lower()
        and "count(" not in str(stmt).lower()
    )
    sql = str(
        pending_stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "priority = 'high'" in sql and "then 0" in sql
    assert "priority = 'normal'" in sql and "then 1" in sql
    assert "priority = 'low'" in sql and "then 2" in sql
    assert "batch_items.created_at asc, batch_items.id asc" in sql

    calls = [
        call
        for call in pool.enqueue_job.call_args_list
        if call.args[0] == "run_batch_item"
    ]
    assert [call.args[1] for call in calls] == [item.ulid for item in items]
    assert [call.kwargs["_defer_by"] for call in calls] == [0, 1, 2]
    assert [item.attempt_count for item in items] == [1, 1, 1]


@pytest.mark.asyncio
async def test_stale_lease_recovery_requeues_under_budget_and_fails_exhausted():
    batch = _batch()
    retryable = _item(1, status="processing", attempts=2)
    exhausted = _item(2, status="processing", attempts=3)
    session = AsyncMock()
    session.execute.return_value = _result(all_rows=[retryable, exhausted])
    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

    recovered = await batch_service.recover_stale_batch_item_leases(
        session,
        batch,
        processing_cutoff=now - timedelta(minutes=11),
        queued_cutoff=now - timedelta(hours=6),
        now=now,
    )

    assert recovered.requeued_ulids == (retryable.ulid,)
    assert recovered.exhausted_ulids == (exhausted.ulid,)
    assert retryable.status == "pending"
    assert exhausted.status == "failed"
    assert exhausted.completed_at == now
    assert "3 attempts" in exhausted.error_message
    assert batch.failed_items == 1


class _ProviderError(Exception):
    def __init__(self, status: int, code: str):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


@pytest.mark.parametrize(
    "cause",
    [
        TimeoutError("socket timed out"),
        ConnectionResetError(errno.ECONNRESET, "reset"),
        _ProviderError(503, "SlowDown"),
    ],
)
def test_storage_transient_allowlist(cause):
    error = batch_tasks.BatchStorageReadError("storage read")
    error.__cause__ = cause
    assert batch_tasks.is_transient_batch_item_error(error) is True


def test_database_transient_allowlist_and_integrity_denylist():
    operational = OperationalError("select", {}, ConnectionError("db down"))
    integrity = IntegrityError("insert", {}, ValueError("duplicate"))
    assert batch_tasks.is_transient_batch_item_error(operational) is True
    assert batch_tasks.is_transient_batch_item_error(integrity) is False


@pytest.mark.parametrize(
    "error",
    [
        ValueError("invalid CAD"),
        asyncio.TimeoutError("CAD compute budget exceeded"),
        ObjectNotFoundError("missing-part.stl"),
        _ProviderError(403, "AccessDenied"),
    ],
)
def test_user_cad_and_permanent_storage_errors_are_never_retried(error):
    if isinstance(error, _ProviderError):
        wrapped = batch_tasks.BatchStorageReadError("storage read")
        wrapped.__cause__ = error
        error = wrapped
    assert batch_tasks.is_transient_batch_item_error(error) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attempts", "parent_status", "expected_action", "expected_status"),
    [
        (1, "processing", "retry", "queued"),
        (3, "processing", "failed", "failed"),
        (1, "cancelled", "terminal", "skipped"),
    ],
)
async def test_transient_resolution_retry_exhaustion_and_terminal_parent(
    attempts, parent_status, expected_action, expected_status
):
    item = _item(1, status="processing", attempts=attempts)
    batch = _batch(status=parent_status)
    session = AsyncMock()
    session.execute.side_effect = [_result(first=item), _result(first=batch)]

    with patch(
        "src.jobs.batch_tasks.get_session_factory",
        return_value=_session_factory(session),
    ), patch.object(
        batch_service,
        "update_batch_counters",
        new_callable=AsyncMock,
    ) as counters:
        action, resulting_attempts = (
            await batch_tasks._resolve_transient_batch_item_failure(item.ulid)
        )

    assert action == expected_action
    assert item.status == expected_status
    if expected_action == "retry":
        assert resulting_attempts == 2
        assert item.attempt_count == 2
    if expected_action == "failed":
        counters.assert_awaited_once_with(session, batch.id, "failed_items")
        assert "3 attempts" in item.error_message
    else:
        counters.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_real_item_task_retries_storage_timeout_without_terminalizing(mock_gsf):
    item = _item(1, status="queued", attempts=1)
    batch = _batch()
    session = AsyncMock()
    session.execute.side_effect = [_result(first=item), _result(first=batch)]
    mock_gsf.return_value = _session_factory(session)

    with patch.object(
        batch_service,
        "read_batch_blob",
        side_effect=TimeoutError("S3 read timed out"),
    ), patch.object(
        batch_tasks,
        "_resolve_transient_batch_item_failure",
        new_callable=AsyncMock,
        return_value=("retry", 2),
    ) as resolve, patch.object(
        batch_service,
        "update_batch_counters",
        new_callable=AsyncMock,
    ) as counters:
        with pytest.raises(Retry):
            await batch_tasks.run_batch_item({"job_try": 1}, item.ulid)

    resolve.assert_awaited_once_with(item.ulid)
    counters.assert_not_awaited()
    assert item.status == "processing"


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_real_item_task_retries_operational_db_failure(mock_gsf):
    item = _item(1, status="queued", attempts=1)
    batch = _batch()
    session = AsyncMock()
    session.execute.side_effect = [_result(first=item), _result(first=batch)]
    mock_gsf.return_value = _session_factory(session)

    from src.services import analysis_service

    db_error = OperationalError("update", {}, ConnectionError("db restarted"))
    with patch.object(
        batch_service,
        "read_batch_blob",
        return_value=b"solid part\nendsolid part",
    ), patch.object(
        analysis_service,
        "run_analysis",
        new_callable=AsyncMock,
        side_effect=db_error,
    ), patch.object(
        batch_tasks,
        "_resolve_transient_batch_item_failure",
        new_callable=AsyncMock,
        return_value=("retry", 2),
    ) as resolve, patch.object(
        batch_service,
        "update_batch_counters",
        new_callable=AsyncMock,
    ) as counters:
        with pytest.raises(Retry):
            await batch_tasks.run_batch_item({"job_try": 1}, item.ulid)

    resolve.assert_awaited_once_with(item.ulid)
    counters.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_reconciliation_covers_pending_queued_and_processing():
    session = AsyncMock()
    session.execute.return_value = _result(all_rows=[1, 2, 3])

    changed = await batch_service.reconcile_terminal_batch_items(session)

    assert changed == 3
    stmt = session.execute.await_args.args[0]
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "update batch_items" in sql
    assert "'completed', 'failed', 'cancelled'" in sql
    assert "'pending', 'queued', 'processing'" in sql
    assert "lease_started_at=null" in sql.replace(" ", "") or "lease_started_at = null" in sql


@pytest.mark.asyncio
@patch("src.jobs.batch_tasks.get_session_factory")
async def test_terminal_reconciliation_task_commits_repaired_items(mock_gsf):
    session = AsyncMock()
    mock_gsf.return_value = _session_factory(session)
    with patch.object(
        batch_service,
        "reconcile_terminal_batch_items",
        new_callable=AsyncMock,
        return_value=2,
    ) as reconcile:
        changed = await batch_tasks.reconcile_terminal_batch_items({})

    assert changed == 2
    reconcile.assert_awaited_once_with(session)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_reconciliation_task_has_explicit_off_switch(monkeypatch):
    monkeypatch.setenv("BATCH_TERMINAL_RECONCILE_ENABLED", "0")
    assert await batch_tasks.reconcile_terminal_batch_items({}) == 0


def test_worker_registers_exact_bounded_item_attempts():
    from src.jobs.worker import WorkerSettings

    registration = next(
        fn for fn in WorkerSettings.functions if getattr(fn, "name", None) == "run_batch_item"
    )
    assert registration.max_tries == batch_service.BATCH_ITEM_MAX_ATTEMPTS == 3
    cron_names = {job.coroutine.__name__ for job in WorkerSettings.cron_jobs}
    assert "reconcile_terminal_batch_items" in cron_names
