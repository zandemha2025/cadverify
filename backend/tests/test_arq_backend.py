"""Publication idempotency and routing tests for the ARQ job adapter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from src.jobs.arq_backend import ArqJobQueue


def _job(key: str, job_type: str, status: str = "queued") -> MagicMock:
    job = MagicMock()
    job.ulid = key
    job.job_type = job_type
    job.status = status
    return job


def _factory_for(job: MagicMock | None):
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = job
    session.execute.return_value = exec_result
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_enqueue_sam3d_routes_to_run_sam3d_job():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(_job("KEY1", "sam3d")),
    ):
        jid = await q.enqueue("sam3d", {"mesh_hash": "x"}, "KEY1")
    assert jid == "KEY1"
    args, kwargs = pool.enqueue_job.call_args
    assert args[0] == "run_sam3d_job"
    assert args[1] == "KEY1"
    assert kwargs.get("_job_id") == "KEY1"


@pytest.mark.asyncio
async def test_enqueue_reconstruction_routes_to_run_reconstruction_job():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(_job("KEY2", "reconstruction")),
    ):
        await q.enqueue("reconstruction", {}, "KEY2")
    args, kwargs = pool.enqueue_job.call_args
    assert args[0] == "run_reconstruction_job"
    assert kwargs["_job_id"] == "recon_KEY2"


@pytest.mark.asyncio
async def test_enqueue_design_routes_to_sandboxed_generation_job():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(_job("KEY-DESIGN", "design_generation")),
    ):
        await q.enqueue("design_generation", {}, "KEY-DESIGN")
    args, _ = pool.enqueue_job.call_args
    assert args[0] == "run_design_generation_job"


@pytest.mark.asyncio
async def test_enqueue_unknown_job_type_raises_and_does_not_enqueue():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    with pytest.raises(ValueError, match="Unknown job_type"):
        await q.enqueue("bogus_type", {}, "KEY3")
    pool.enqueue_job.assert_not_called()


@pytest.mark.asyncio
async def test_committed_queued_row_is_offered_even_when_publication_already_exists():
    pool = AsyncMock()
    pool.enqueue_job.return_value = None
    q = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(_job("KEY1", "sam3d")),
    ):
        jid = await q.enqueue("sam3d", {}, "KEY1")
    assert jid == "KEY1"
    pool.enqueue_job.assert_awaited_once_with(
        "run_sam3d_job",
        "KEY1",
        _job_id="KEY1",
    )


@pytest.mark.asyncio
async def test_repeated_publication_uses_one_deterministic_arq_job_id():
    class IdempotentPool:
        def __init__(self) -> None:
            self.ids: set[str] = set()
            self.scheduled = 0

        async def enqueue_job(self, _task, _job_ulid, *, _job_id):
            if _job_id in self.ids:
                return None
            self.ids.add(_job_id)
            self.scheduled += 1
            return object()

    pool = IdempotentPool()
    queue = ArqJobQueue(pool)  # type: ignore[arg-type]
    factory = _factory_for(_job("KEY1", "sam3d"))
    with patch("src.jobs.arq_backend.get_session_factory", return_value=factory):
        await queue.enqueue("sam3d", {}, "KEY1")
        await queue.enqueue("sam3d", {}, "KEY1")
    assert pool.ids == {"KEY1"}
    assert pool.scheduled == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "done", "partial", "failed"])
async def test_terminal_or_running_row_is_not_republished(status: str):
    pool = AsyncMock()
    queue = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(_job("KEY1", "sam3d", status)),
    ):
        assert await queue.enqueue("sam3d", {}, "KEY1") == "KEY1"
    pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_uncommitted_job_is_rejected_before_redis_publication():
    pool = AsyncMock()
    queue = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(None),
    ):
        with pytest.raises(ValueError, match="must be committed"):
            await queue.enqueue("sam3d", {}, "MISSING")
    pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_persisted_job_type_must_match_publication_task():
    pool = AsyncMock()
    queue = ArqJobQueue(pool)
    with patch(
        "src.jobs.arq_backend.get_session_factory",
        return_value=_factory_for(_job("KEY1", "reconstruction")),
    ):
        with pytest.raises(ValueError, match="not 'sam3d'"):
            await queue.enqueue("sam3d", {}, "KEY1")
    pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciler_reoffers_each_durable_queued_job():
    from src.jobs import arq_backend

    session = AsyncMock()
    query_result = MagicMock()
    query_result.all.return_value = [
        ("SAM-1", "sam3d"),
        ("RECON-1", "reconstruction"),
    ]
    session.execute.return_value = query_result
    ctx = AsyncMock()
    ctx.__aenter__.return_value = session
    ctx.__aexit__.return_value = False
    factory = MagicMock(return_value=ctx)

    with (
        patch.object(arq_backend, "get_session_factory", return_value=factory),
        patch.object(
            arq_backend.ArqJobQueue,
            "enqueue",
            new_callable=AsyncMock,
        ) as enqueue,
    ):
        result = await arq_backend.reconcile_queued_jobs({"redis": AsyncMock()})

    assert result == {"scanned": 2, "offered": 2, "failed": 0}
    assert enqueue.await_args_list == [
        call("sam3d", {}, "SAM-1"),
        call("reconstruction", {}, "RECON-1"),
    ]


@pytest.mark.asyncio
async def test_close_arq_pool_closes_and_clears_singleton():
    import src.jobs.arq_backend as backend

    pool = AsyncMock()
    backend._pool = pool
    await backend.close_arq_pool()
    pool.aclose.assert_awaited_once()
    assert backend._pool is None
