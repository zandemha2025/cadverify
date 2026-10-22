"""Big kept parts: re-price and mesh repair on the worker, from the kept file.

A saved part is re-priced (``POST /parts/{hash}/recheck``: another material,
quantities, machines, orientation) and repaired (``POST /parts/{hash}/repair``)
from the file its organization kept. When that file is beyond what a web request
handles, the route doesn't read it. Beyond means any of:

* 20 MB or more (``KEPT_PART_WORKER_FROM_MB``), the size from which an upload
  also goes to the big-file check instead of the one-request check;
* over the web request's own upload limit (``MAX_UPLOAD_MB``);
* more memory than this process gives one check (the worker's measured model,
  ``stored_check_service.estimate_memory_bytes``, as the web memory gate sizes
  an upload).

The route then starts the same kind of job as a big file's check (``jobs``
row, ``job_type = 'stored_check'``, ``params.source = 'kept'``) and answers 202
with the job's status, the shape ``POST /api/v1/checks`` answers. The worker
(``src.jobs.kept_part_tasks``) sizes the file against its own memory, runs the
route's own code path under the big-check limits, and keeps the response the
route would have given on the job: ``GET /api/v1/checks/{id}`` returns it as
``result`` once done. The work bar shows it on every page like a big check.

Nothing is charged, on the web or on the worker: neither uses a check (the free
accounts' per-user ceiling on re-checks and repairs is counted at the request,
as for the one-request path).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db.models import Job

JOB_TYPE = "stored_check"
SOURCE = "kept"
RECHECK = "recheck"
REPAIR = "repair"
ACTIONS = (RECHECK, REPAIR)
DEFAULT_WORKER_FROM_MB = 20.0
_HEAD_BYTES = 84  # enough for a binary STL's triangle count


@dataclass(frozen=True)
class KeptSource:
    """The kept file's key, suffix, size and first bytes: what sizing needs, not the file."""

    key: str
    suffix: str
    size: int
    head: bytes


def _size(store, key: str) -> int:
    stat = getattr(store, "stat", None)
    if callable(stat):
        return int(stat(key).size_bytes)
    local_path = getattr(store, "local_path", None)
    if callable(local_path):
        return int(os.path.getsize(local_path(key)))
    total = 0
    with store.open(key) as fh:  # a store that can only stream: count, never hold
        while chunk := fh.read(8 * 1024 * 1024):
            total += len(chunk)
    return total


def _head(store, key: str) -> bytes:
    with store.open(key) as fh:
        return fh.read(_HEAD_BYTES)


async def kept_source_info(org_id: str, mesh_hash: str) -> Optional[KeptSource]:
    """The organization's kept file for this part, without reading it. None when none is kept."""
    from src.services import source_artifact_service as sources
    from src.storage import ObjectNotFoundError

    try:
        suffix = await sources.find_source_artifact_suffix(org_id, mesh_hash)
        if suffix is None:
            return None
        key = sources.artifact_key(org_id, mesh_hash, suffix)
        store = sources._store()
        size = await asyncio.to_thread(_size, store, key)
        head = await asyncio.to_thread(_head, store, key)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        return None
    return KeptSource(key=key, suffix=suffix, size=size, head=head)


def worker_from_bytes() -> int:
    try:
        mb = float(os.getenv("KEPT_PART_WORKER_FROM_MB", str(DEFAULT_WORKER_FROM_MB)))
    except ValueError:
        mb = DEFAULT_WORKER_FROM_MB
    return int(max(0.0, mb) * 1024 * 1024)


def memory_need(info: KeptSource) -> tuple[int, dict[str, Any]]:
    """The memory one check of the kept file needs, from its size and first bytes."""
    from src.services import stored_check_service as sizing

    return sizing._estimate(info.size, f"source{info.suffix}",
                            lambda: sizing._stl_triangles_from_head(info.head, info.size))


def needs_worker(info: KeptSource) -> bool:
    """Whether this kept file is beyond what a web request handles (see the module docstring)."""
    from src.api.routes import _max_upload_bytes
    from src.config import check_limits
    from src.services import stored_check_service as sizing

    if check_limits.current() is not None:
        return False  # already on the worker, under the big-check limits
    if info.size >= worker_from_bytes() or info.size > _max_upload_bytes():
        return True
    need, _basis = memory_need(info)
    return need > sizing.check_memory_budget_bytes()


def _plain(options: dict[str, Any]) -> dict[str, Any]:
    """The job's options: plain JSON values only (ids, strings, numbers, lists of numbers)."""
    out: dict[str, Any] = {}
    for key, value in options.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            out[key] = value
        elif isinstance(value, (list, tuple)) and all(isinstance(v, (int, float, str)) for v in value):
            out[key] = list(value)
        else:
            raise TypeError(f"option {key!r} is not a plain JSON value")
    return out


async def start_job(
    session: AsyncSession,
    *,
    user_id: int,
    org_id: str,
    mesh_hash: str,
    action: str,
    filename: str,
    info: KeptSource,
    options: dict[str, Any],
) -> tuple[Job, bool]:
    """Create the job (committed) or return the same one already waiting or running.

    Asking again for the same part, action and options while one runs returns it
    (a second click doesn't start a second big job).
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown kept-part action {action!r}")
    opts = _plain(options)
    running = (await session.execute(
        select(Job).where(
            Job.org_id == org_id,
            Job.job_type == JOB_TYPE,
            Job.status.in_(("queued", "running")),
            Job.params_json["source"].astext == SOURCE,
            Job.params_json["mesh_hash"].astext == mesh_hash,
            Job.params_json["action"].astext == action,
        ).order_by(Job.id.desc()).limit(20)
    )).scalars().all()
    for job in running:
        if (job.params_json or {}).get("options") == opts:
            return job, False
    job = Job(
        ulid=str(ULID()),
        user_id=user_id,
        org_id=org_id,
        job_type=JOB_TYPE,
        status="queued",
        params_json={
            "source": SOURCE,
            "action": action,
            "mesh_hash": mesh_hash,
            "filename": filename,
            "size_bytes": info.size,
            "material_class": opts.get("material_class"),
            "options": opts,
        },
        result_json={"stage": "queued", "progress": None},
    )
    session.add(job)
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action=f"part.{action}_queued",
        resource_type="part",
        resource_id=mesh_hash,
        file_hash=mesh_hash,
        detail={"job_id": job.ulid, "bytes": info.size, "on": "worker"},
        org_id=org_id,
    )
    await session.commit()
    return job, True


async def start_and_enqueue(session: AsyncSession, **kwargs: Any) -> Job:
    """``start_job`` and publish it to the worker (the committed row is the durable intent)."""
    from src.services import stored_check_service as checks

    job, _created = await start_job(session, **kwargs)
    if job.status == "queued":
        try:
            await checks.enqueue(job)
        except Exception:
            # The worker's reconcile cron offers queued rows again
            # (src.jobs.arq_backend.reconcile_queued_jobs).
            pass
    return job


async def is_kept_job(job_ulid: str) -> bool:
    from src.db.engine import get_session_factory

    async with get_session_factory()() as session:
        source = (await session.execute(
            select(Job.params_json["source"].astext).where(Job.ulid == job_ulid, Job.job_type == JOB_TYPE)
        )).scalar_one_or_none()
    return source == SOURCE
