"""The worker's thread pool: enough threads that a busy box slows down, never times out.

Every blocking call the worker makes off the event loop shares the loop's
default executor: a part's parse and price (``run_in_executor(None, ...)``),
storage reads (``asyncio.to_thread``), and the event loop's own host lookup
before every new database or Redis connection (``loop.getaddrinfo``). The
default pool has ``min(32, cpus + 4)`` threads, 8 on a 4-CPU box. Twelve
jobs each holding a thread for a minutes-long parse, plus the work of a job
that timed out (a thread can't be cancelled, so it runs on), take every one of
them; a database connect then waits in the queue until asyncpg gives up at
60 s. That is how batch 23's coordinator and the minute crons died under load.

The worker sizes its default pool for everything it can have running at once,
with room to spare, so a lookup or a storage read always finds a thread and
merely runs slower when the CPUs are busy. The CPU work itself is bounded by
the jobs (``max_jobs``) and the catalog's parse slots, not by this pool.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("cadverify.worker")

_FLOOR = 64


def worker_executor_threads() -> int:
    """The worker's default-pool size: WORKER_THREAD_POOL_SIZE, at least 64."""
    try:
        configured = int(os.getenv("WORKER_THREAD_POOL_SIZE", str(_FLOOR)))
    except (TypeError, ValueError):
        configured = _FLOOR
    return max(_FLOOR, configured)


def install_worker_executor(loop: asyncio.AbstractEventLoop | None = None) -> ThreadPoolExecutor:
    """Give the worker's event loop its own, larger default thread pool (idempotent per loop)."""
    loop = loop or asyncio.get_event_loop()
    current = getattr(loop, "_cadverify_worker_executor", None)
    if current is not None:
        return current
    pool = ThreadPoolExecutor(max_workers=worker_executor_threads(), thread_name_prefix="worker")
    loop.set_default_executor(pool)
    setattr(loop, "_cadverify_worker_executor", pool)
    logger.info("worker default thread pool: %d threads", pool._max_workers)
    return pool
