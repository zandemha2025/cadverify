"""Unit tests for ArqJobQueue.enqueue job_type routing (F-ARCH + arq bug).

enqueue() previously hardcoded 'run_sam3d_job' regardless of job_type. It now
honors job_type via an explicit registry; unknown job_type raises.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.jobs.arq_backend import ArqJobQueue


def _factory_no_existing():
    """Session factory whose Job lookup returns None (no duplicate)."""
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = None
    session.execute.return_value = exec_result
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


@pytest.mark.asyncio
async def test_enqueue_sam3d_routes_to_run_sam3d_job():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    with patch("src.jobs.arq_backend.get_session_factory", return_value=_factory_no_existing()):
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
    with patch("src.jobs.arq_backend.get_session_factory", return_value=_factory_no_existing()):
        await q.enqueue("reconstruction", {}, "KEY2")
    args, _ = pool.enqueue_job.call_args
    assert args[0] == "run_reconstruction_job"


@pytest.mark.asyncio
async def test_enqueue_design_routes_to_sandboxed_generation_job():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    with patch("src.jobs.arq_backend.get_session_factory", return_value=_factory_no_existing()):
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
async def test_enqueue_duplicate_returns_existing_without_reenqueue():
    pool = AsyncMock()
    q = ArqJobQueue(pool)
    existing = MagicMock()
    existing.ulid = "KEY1"
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.first.return_value = existing
    session.execute.return_value = exec_result
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    with patch("src.jobs.arq_backend.get_session_factory", return_value=factory):
        jid = await q.enqueue("sam3d", {}, "KEY1")
    assert jid == "KEY1"
    pool.enqueue_job.assert_not_called()


@pytest.mark.asyncio
async def test_close_arq_pool_closes_and_clears_singleton():
    import src.jobs.arq_backend as backend

    pool = AsyncMock()
    backend._pool = pool
    await backend.close_arq_pool()
    pool.aclose.assert_awaited_once()
    assert backend._pool is None
