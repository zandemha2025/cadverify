"""The worker slows down under load instead of falling over (round 12, item 5).

Batch 23's coordinator and the minute crons died at 60 s with asyncpg's
connect TimeoutError. The traceback ended in ``loop.getaddrinfo`` ->
``run_in_executor``: resolving the database host waits for a thread of the
event loop's default executor, and every one of those threads was busy with a
part's parse or price (and, after a job timed out, with work that can't be
cancelled and runs on). These tests hold the default executor's threads the
same way and time the database connect.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")


def _default_executor_threads() -> int:
    # concurrent.futures.ThreadPoolExecutor's default size.
    return min(32, (os.cpu_count() or 1) + 4)


async def _hold_executor(n: int, release: threading.Event) -> list[asyncio.Future]:
    """Occupy n default-executor threads, as n long parses would."""
    loop = asyncio.get_running_loop()
    return [loop.run_in_executor(None, release.wait, 30) for _ in range(n)]


def test_host_resolution_waits_behind_busy_parses_without_the_worker_executor():
    """The incident in miniature: every default thread busy, a DB host lookup has to wait."""

    async def scenario() -> float:
        release = threading.Event()
        held = await _hold_executor(_default_executor_threads() + 4, release)
        loop = asyncio.get_running_loop()
        loop.call_later(1.5, release.set)
        t0 = time.monotonic()
        await loop.getaddrinfo("localhost", 5432)
        took = time.monotonic() - t0
        await asyncio.gather(*held)
        return took

    assert asyncio.run(scenario()) >= 1.2


def test_the_worker_executor_keeps_host_resolution_free_while_parses_hold_threads():
    from src.jobs.executor import install_worker_executor, worker_executor_threads

    async def scenario() -> float:
        loop = asyncio.get_running_loop()
        install_worker_executor(loop)
        release = threading.Event()
        # As many blocking calls as the worker can have running at once (12 jobs, a
        # parse and a price each, plus a timed-out job's work still finishing).
        held = await _hold_executor(_default_executor_threads() + 4, release)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(loop.getaddrinfo("localhost", 5432), timeout=5)
            return time.monotonic() - t0
        finally:
            release.set()
            await asyncio.gather(*held)

    assert worker_executor_threads() > _default_executor_threads() + 4
    assert asyncio.run(scenario()) < 1.0


@pytest.mark.skipif(not _PG, reason="requires PostgreSQL (DATABASE_URL=postgresql://...)")
def test_a_db_connect_under_parse_load_is_prompt_with_the_worker_executor():
    """The coordinator's own first step (open a session, run a query) while parses hold threads."""
    from sqlalchemy import text

    from src.jobs.executor import install_worker_executor

    async def scenario(install: bool) -> float:
        import src.db.engine as eng

        loop = asyncio.get_running_loop()
        if install:
            install_worker_executor(loop)
        await eng.dispose_engine()
        release = threading.Event()
        held = await _hold_executor(_default_executor_threads() + 4, release)
        loop.call_later(2.0, release.set)
        t0 = time.monotonic()
        try:
            async with eng.get_session_factory()() as s:
                await s.execute(text("SELECT 1"))
            return time.monotonic() - t0
        finally:
            release.set()
            await asyncio.gather(*held)
            await eng.dispose_engine()

    assert asyncio.run(scenario(False)) >= 1.5  # waits for a parse to give a thread back
    assert asyncio.run(scenario(True)) < 1.5
