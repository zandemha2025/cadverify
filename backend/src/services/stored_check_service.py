"""A single part checked on the worker from its stored upload (big files).

The browser uploads the file straight to storage (``direct_upload_service``,
purpose ``part``), then ``POST /api/v1/checks`` starts the check: a ``jobs`` row
(``job_type = 'stored_check'``) and an arq task (``src.jobs.stored_check_tasks``).
The web request never reads the file. The worker verifies the upload's SHA-256,
unpacks a ``.gz`` or one-part ZIP (``part_archive``), estimates the memory the
check needs and refuses honestly when it is over what this worker can give,
then runs the same two steps as a single check (the DFM analysis and the cost
decision, the code paths of ``POST /validate`` and ``POST /validate/cost``) and
keeps the file as the organization's source for the part.

Progress lives in the job row's ``result_json`` (``stage``, ``progress``) and
is read by ``GET /api/v1/checks/{id}``.

The check takes a check from the account's allowance exactly as an upload of
the same file would (the same file identity: name and bytes), reserved on the
worker once the bytes are known; the sample and ScaleCAD-made copies are free
as they are on the web path.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.auth.org_context import caller_org_subquery
from src.db.models import DirectUpload, Job

logger = logging.getLogger("cadverify.stored_check")

JOB_TYPE = "stored_check"
MATERIAL_CLASSES = ("polymer", "aluminum", "steel", "stainless", "titanium")
STAGES = ("queued", "verifying", "unpacking", "sizing", "measuring", "pricing", "done", "failed")
_QTY = re.compile(r"^\d{1,7}(,\d{1,7}){0,11}$")


class StoredCheckError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    @property
    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


# ---------------------------------------------------------------------------
# How big a file this worker can check (memory), and what one check needs
# ---------------------------------------------------------------------------

# Peak resident memory one check adds to a warmed worker (download and
# SHA-256, parse, DFM analysis, cost decision, kept source and preview),
# measured on the real pipeline one check at a time (docs/BIG_FILES.md has the
# table and how it was taken). A binary STL is sized by its triangle count
# (exact, from its header), an ASCII STL by its triangles estimated from its
# size (~290 bytes a facet; measured to cost the same memory per triangle), and
# STEP and IGES by file size, since their triangle count is only known after
# tessellation. Between measured points the need is interpolated; past the last
# one it grows at the last measured slope. Every figure carries 10% headroom.
MEMORY_HEADROOM = 1.10
# (triangles, MB added) for STL
STL_MEMORY_POINTS: tuple[tuple[int, float], ...] = (
    (0, 150.0), (10_240, 158.0), (81_920, 461.0), (327_680, 975.0), (1_310_720, 2016.0),
)
# (file MB, MB added) for STEP (assemblies of repeated bracket bodies, ~58k faces per MB)
STEP_MEMORY_POINTS: tuple[tuple[float, float], ...] = (
    (0.0, 270.0), (0.036, 275.0), (1.16, 745.0), (4.92, 1531.0), (10.07, 2396.0),
)
# IGES is sized like STEP. The IGES files measured (1.4 MB: 414 MB added; 5.7
# MB: 660 MB) tessellated as open shells, so they skipped pricing and needed
# less than a closed solid would; STEP's curve is the safe one for a solid.
IGES_MEMORY_POINTS = STEP_MEMORY_POINTS
ASCII_STL_BYTES_PER_TRIANGLE = 290
MEMORY_MODEL = {"stl": STL_MEMORY_POINTS, "step": STEP_MEMORY_POINTS, "iges": IGES_MEMORY_POINTS}
_KIND = {".stl": "stl", ".step": "step", ".stp": "step", ".iges": "iges", ".igs": "iges"}
_FORMAT_WORD = {"stl": "STL", "stl_ascii": "STL", "step": "STEP", "iges": "IGES"}


def _interp(points, x: float) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    (x0, y0), (x1, y1) = points[-2], points[-1]
    return y1 + (y1 - y0) * (x - x1) / (x1 - x0)


def _inverse(points, y: float) -> float:
    """The largest x the (increasing) curve keeps at or under y."""
    if y <= points[0][1]:
        return 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y <= y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    (x0, y0), (x1, y1) = points[-2], points[-1]
    return x1 + (x1 - x0) * (y - y1) / (y1 - y0)


def _container_memory_bytes() -> Optional[int]:
    """This machine's (or container's) memory: cgroup limit first, then MemTotal."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = open(path).read().strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < 1 << 50:
            return int(raw)
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def check_memory_budget_bytes() -> int:
    """Memory one big check may use on this worker.

    ``CHECK_MEMORY_BUDGET_MB`` when set; else ``CHECK_MEMORY_FRACTION`` (0.6) of
    the machine's memory, which leaves room for the worker itself and the parts
    of batch and catalog runs it checks at the same time. A 2 GB production
    worker gets about 1.2 GB.
    """
    raw = os.getenv("CHECK_MEMORY_BUDGET_MB", "").strip()
    if raw:
        try:
            return max(64, int(raw)) * 1024 * 1024
        except ValueError:
            pass
    try:
        fraction = float(os.getenv("CHECK_MEMORY_FRACTION", "0.6"))
    except ValueError:
        fraction = 0.6
    total = _container_memory_bytes() or 2 * 1024**3
    return int(total * min(max(fraction, 0.1), 0.9))


def _stl_triangles(path: str, size: int) -> tuple[Optional[int], bool]:
    """(triangles, binary) for an STL: the binary header's count, else an estimate for ASCII."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(84)
    except OSError:
        return None, False
    if len(head) >= 84:
        count = int.from_bytes(head[80:84], "little")
        if 84 + 50 * count == size:
            return count, True
    if head[:5].lower() == b"solid":
        # ~260 bytes of text per facet in exporters' usual layout.
        return max(1, size // 260), False
    return None, True


def estimate_memory_bytes(path: str, filename: str) -> tuple[int, dict[str, Any]]:
    """Peak memory one check of this file needs, from its format and size (no parse)."""
    size = os.path.getsize(path)
    suffix = os.path.splitext(filename.lower())[1]
    kind = _KIND.get(suffix, "step")
    basis: dict[str, Any] = {"format": kind, "bytes": size}
    if kind == "stl":
        triangles, binary = _stl_triangles(path, size)
        if not binary or triangles is None:
            kind = "stl_ascii"
            triangles = max(1, size // ASCII_STL_BYTES_PER_TRIANGLE)
            basis["format"] = kind
        basis["triangles"] = triangles
        need_mb = _interp(STL_MEMORY_POINTS, triangles)
    else:
        need_mb = _interp(MEMORY_MODEL[kind], size / 1024**2)
    basis["headroom"] = MEMORY_HEADROOM
    return int(need_mb * MEMORY_HEADROOM * 1024**2), basis


def largest_checkable_bytes(kind: str, budget: Optional[int] = None) -> int:
    """The largest file of a format one check fits in ``budget`` (the inverse of the model)."""
    budget = check_memory_budget_bytes() if budget is None else budget
    room_mb = budget / 1024**2 / MEMORY_HEADROOM
    if kind in ("stl", "stl_ascii"):
        triangles = _inverse(STL_MEMORY_POINTS, room_mb)
        return int(84 + 50 * triangles) if kind == "stl" else int(triangles * ASCII_STL_BYTES_PER_TRIANGLE)
    return int(_inverse(MEMORY_MODEL[kind], room_mb) * 1024**2)


def _size_words(n: float) -> str:
    if n >= 1024**3:
        g = n / 1024**3
        return f"{g:.0f} GB" if g >= 10 else f"{g:.1f} GB"
    return f"{max(1, round(n / 1024**2))} MB"


def too_heavy_message(need: int, basis: dict[str, Any], budget: Optional[int] = None) -> str:
    kind = basis.get("format", "step")
    word = _FORMAT_WORD.get(kind, "CAD")
    largest = largest_checkable_bytes(kind, budget)
    return (
        f"This file needs about {_size_words(need)} of memory to check; the largest {word} file "
        f"ScaleCAD checks today is about {_size_words(largest)}. Nothing was charged."
    )


# Wall-clock budget for one big check: a base plus time per MB by format,
# about twice what the measurements took on a loaded 4-core box (STL ~1.6 s/MB,
# STEP ~40 s/MB, IGES ~45 s/MB; docs/BIG_FILES.md), capped below arq's ceiling
# for the task. ``CHECK_SECONDS_PER_MB`` overrides the per-MB figure.
STORED_CHECK_JOB_TIMEOUT_SECONDS = 3600
SECONDS_PER_MB = {"stl": 5.0, "step": 90.0, "iges": 100.0}


def time_budget_sec(part_bytes: int, filename: str = "") -> float:
    kind = _KIND.get(os.path.splitext(filename.lower())[1], "step")
    per_mb = SECONDS_PER_MB.get(kind, 90.0)
    raw = os.getenv("CHECK_SECONDS_PER_MB", "").strip()
    if raw:
        try:
            per_mb = float(raw)
        except ValueError:
            pass
    return min(STORED_CHECK_JOB_TIMEOUT_SECONDS - 300.0, 120.0 + per_mb * part_bytes / 1024**2)


# ---------------------------------------------------------------------------
# Starting and reading a check
# ---------------------------------------------------------------------------

def _validated_options(options: dict[str, Any]) -> dict[str, Any]:
    material = options.get("material_class") or "polymer"
    if material not in MATERIAL_CLASSES:
        raise StoredCheckError(422, "INVALID_MATERIAL_CLASS", f"material_class must be one of {', '.join(MATERIAL_CLASSES)}.")
    qty = options.get("qty")
    if qty is not None and (not isinstance(qty, str) or not _QTY.fullmatch(qty.replace(" ", ""))):
        raise StoredCheckError(422, "INVALID_QUANTITY", "qty must be up to 12 whole numbers separated by commas.")
    units = options.get("units")
    if units not in (None, "mm", "inch"):
        raise StoredCheckError(422, "INVALID_UNITS", "units must be mm or inch.")
    orientation = options.get("orientation")
    if orientation is not None:
        from src.analysis.orientation import parse_orientation

        try:
            parse_orientation(orientation)
        except ValueError as exc:
            raise StoredCheckError(422, "INVALID_ORIENTATION", str(exc)) from exc
    return {
        "material_class": material,
        "qty": qty.replace(" ", "") if isinstance(qty, str) else None,
        "units": units,
        "orientation": orientation,
    }


# A running check writes a heartbeat every 30 s (stored_check_tasks). One that
# has missed it for this long lost its worker (a restart, out of memory).
STALLED_AFTER = timedelta(minutes=3)
STALLED_MESSAGE = (
    "The check stopped before it finished: its worker restarted or ran out of memory. "
    "Nothing was charged; check the file again."
)


def is_stalled(job: Job, now: Optional[datetime] = None) -> bool:
    if job.status != "running":
        return False
    now = now or datetime.now(timezone.utc)
    beat = (job.result_json or {}).get("heartbeat_at")
    try:
        last = datetime.fromisoformat(beat) if beat else job.started_at
    except (TypeError, ValueError):
        last = job.started_at
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last > STALLED_AFTER


def public_status(job: Job, upload: Optional[DirectUpload] = None) -> dict[str, Any]:
    params = job.params_json or {}
    result = job.result_json or {}
    key = result.get("mesh_hash")
    if is_stalled(job):
        # Said as it is the moment it's known; the sweep makes it durable.
        result = {**result, "stage": "failed", "error": {"code": "CHECK_INTERRUPTED", "message": STALLED_MESSAGE, "charged": False}}
        return {**_status_fields(job, params, result, key), "status": "failed", "stage": "failed", "error": result["error"]}
    return _status_fields(job, params, result, key)


async def fail_stalled_checks(session: AsyncSession, *, limit: int = 50) -> int:
    """Durably end checks whose worker died, and end their uploads (the cron runs this)."""
    from src.services import direct_upload_service as uploads

    rows = list((await session.execute(
        select(Job).where(Job.job_type == JOB_TYPE, Job.status == "running")
        .order_by(Job.started_at).limit(limit).with_for_update(skip_locked=True)
    )).scalars().all())
    ended = 0
    for job in rows:
        if not is_stalled(job):
            continue
        job.status = "failed"
        job.completed_at = datetime.now(timezone.utc)
        job.result_json = {**(job.result_json or {}), "stage": "failed",
                           "error": {"code": "CHECK_INTERRUPTED", "message": STALLED_MESSAGE, "charged": False}}
        ended += 1
        upload = (await session.execute(select(DirectUpload).where(
            DirectUpload.ulid == (job.params_json or {}).get("direct_upload_id"), DirectUpload.org_id == job.org_id,
        ).with_for_update())).scalars().first()
        await session.commit()
        if upload is not None and upload.status in ("attached", "preparing"):
            await uploads.finish_part_upload(session, upload, ok=False, error_code="CHECK_INTERRUPTED", error_message=STALLED_MESSAGE)
    await session.commit()
    return ended


def _status_fields(job: Job, params: dict, result: dict, key: Optional[str]) -> dict[str, Any]:
    return {
        "check_id": job.ulid,
        "status": job.status,
        "stage": result.get("stage") or ("queued" if job.status == "queued" else job.status),
        "progress": result.get("progress"),
        "filename": params.get("filename"),
        "part_filename": result.get("part_filename"),
        "size_bytes": params.get("size_bytes"),
        "part_bytes": result.get("part_bytes"),
        "material_class": params.get("material_class"),
        "mesh_hash": key,
        "part_url": f"/app/part/{key}" if key and job.status == "done" else None,
        "analysis_id": result.get("analysis_id"),
        "cost_decision_id": result.get("cost_decision_id"),
        "memory": result.get("memory"),
        "geometry_invalid": result.get("geometry_invalid"),
        "cost_error": result.get("cost_error"),
        "timings_ms": result.get("timings_ms"),
        "error": result.get("error") if job.status == "failed" else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "status_url": f"/api/v1/checks/{job.ulid}",
        "upload_id": params.get("direct_upload_id"),
    }


async def start_check(
    session: AsyncSession,
    *,
    user_id: int,
    org_id: str,
    upload_ulid: str,
    options: dict[str, Any],
) -> tuple[Job, bool]:
    """Create the check's job and take the upload for it, in one transaction.

    Returns ``(job, created)``. Starting again on the same upload returns the
    check already started (idempotent), whatever its state.
    """
    from src.services import direct_upload_service as uploads

    opts = _validated_options(options)
    try:
        upload = await uploads.lock_completed_part_for_check(session, user_id=user_id, upload_ulid=upload_ulid)
    except uploads.DirectUploadError as exc:
        raise StoredCheckError(exc.status_code, exc.code, exc.message) from exc
    existing = (await session.execute(
        select(Job).where(
            Job.org_id == upload.org_id,
            Job.job_type == JOB_TYPE,
            Job.params_json["direct_upload_id"].astext == upload.ulid,
        ).limit(1)
    )).scalars().first()
    if existing is not None:
        return existing, False
    if upload.status != "completed":
        raise StoredCheckError(
            409,
            "DIRECT_UPLOAD_NOT_AVAILABLE",
            "This upload isn't finished yet. Finish the upload, then start the check.",
        )
    try:
        uploads.attach_to_check(upload)
    except uploads.DirectUploadError as exc:
        raise StoredCheckError(exc.status_code, exc.code, exc.message) from exc
    job = Job(
        ulid=str(ULID()),
        user_id=user_id,
        org_id=upload.org_id,
        job_type=JOB_TYPE,
        status="queued",
        params_json={
            "direct_upload_id": upload.ulid,
            "filename": upload.filename,
            "size_bytes": upload.expected_size_bytes,
            **opts,
        },
        result_json={"stage": "queued", "progress": None},
    )
    session.add(job)
    from src.services.audit_service import emit_event

    await emit_event(
        session,
        actor_id=user_id,
        action="stored_check.started",
        resource_type="job",
        resource_id=job.ulid,
        detail={"direct_upload_id": upload.ulid, "size_bytes": upload.expected_size_bytes},
        org_id=upload.org_id,
    )
    await session.commit()
    return job, True


async def enqueue(job: Job) -> None:
    """Publish the check to the worker (the committed row is the durable intent)."""
    from src.jobs.arq_backend import ArqJobQueue, get_arq_pool

    queue = ArqJobQueue(await get_arq_pool())
    await queue.enqueue(JOB_TYPE, {}, job.ulid)


async def get_check(session: AsyncSession, *, user_id: int, check_ulid: str) -> Job:
    job = (await session.execute(
        select(Job).where(
            Job.ulid == check_ulid,
            Job.job_type == JOB_TYPE,
            Job.org_id == caller_org_subquery(user_id),
        )
    )).scalars().first()
    if job is None:
        raise StoredCheckError(404, "CHECK_NOT_FOUND", "Check not found.")
    return job


async def recent_checks(session: AsyncSession, *, user_id: int, limit: int = 10) -> list[Job]:
    """The caller's own checks of the last day, newest first (for the work bar)."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    return list((await session.execute(
        select(Job).where(
            Job.user_id == user_id,
            Job.job_type == JOB_TYPE,
            Job.org_id == caller_org_subquery(user_id),
            Job.created_at >= since,
        ).order_by(desc(Job.created_at)).limit(max(1, min(limit, 50)))
    )).scalars().all())
