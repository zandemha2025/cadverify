"""Worker task: check one part from its stored upload (``stored_check_service``).

Stages, written to the job row as they start (``result_json.stage``):

    fetching   a part imported from a share link: fetch it to local disk under the
               link rules (``link_import``), its size and SHA-256 taken as it streams
    verifying  download the stored object to local disk, checking size and SHA-256
    unpacking  a .gz or one-part ZIP, bomb-safe (``part_archive``)
    sizing     estimate the memory the check needs; refuse honestly when over budget
    measuring  the DFM analysis (``analysis_service.run_analysis``, as POST /validate)
    pricing    the cost decision (``routes._run_cost_decision``, as POST /validate/cost)
    done       or ``failed`` with ``error: {code, message}``

The check counts against the account's allowance exactly as an upload of the
same file does; nothing is charged when it fails before measuring.

A job whose ``params.source`` is ``kept`` is a big kept part's re-price or
repair (``src.services.kept_part_jobs``); it runs ``kept_part_tasks.run_kept_part``.
The incoming object is deleted at the end either way; a checked part's bytes
are kept as the organization's source for it by the analysis.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text

from src.db.engine import get_session_factory
from src.db.models import DirectUpload, Job

logger = logging.getLogger("cadverify.stored_check_tasks")

# Triangle ceiling for a big check: memory (the sizing stage) is the real bound.
_BIG_MAX_TRIANGLES = 200_000_000
HEARTBEAT_SECONDS = 30.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _Failed(Exception):
    def __init__(self, code: str, message: str, *, charged: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.charged = charged


async def _patch(job_ulid: str, **fields: Any) -> None:
    """Merge fields into the job's result_json (its own short transaction)."""
    import json

    async with get_session_factory()() as session:
        await session.execute(
            text("UPDATE jobs SET result_json = COALESCE(result_json, '{}'::jsonb) || CAST(:p AS jsonb) WHERE ulid = :u"),
            {"p": json.dumps(fields, default=str), "u": job_ulid},
        )
        await session.commit()


class _Progress:
    """Stage and fraction for the job row; byte progress from a worker thread is flushed every 2 s."""

    def __init__(self, job_ulid: str):
        self.job_ulid = job_ulid
        self.total = 0
        self.done = 0
        self._sent = -1.0
        self._task: Optional[asyncio.Task] = None
        self.timings: dict[str, float] = {}
        self._t = time.perf_counter()
        self._stage: Optional[str] = None

    async def stage(self, name: str, **extra: Any) -> None:
        now = time.perf_counter()
        if self._stage:
            self.timings[self._stage] = round((now - self._t) * 1000, 1)
        self._stage, self._t = name, now
        self.done = 0
        self._sent = -1.0
        await _patch(self.job_ulid, stage=name, progress=None, timings_ms=self.timings, **extra)

    def bytes_done(self, n: int) -> None:  # called from a thread
        self.done = n

    async def _tick(self) -> None:
        beat = 0.0
        while True:
            await asyncio.sleep(2.0)
            # A heartbeat, so a check whose worker died is seen as stopped
            # (stored_check_service.STALLED_AFTER), not "checking" forever.
            if time.monotonic() - beat >= HEARTBEAT_SECONDS:
                beat = time.monotonic()
                try:
                    await _patch(self.job_ulid, heartbeat_at=datetime.now(timezone.utc).isoformat())
                except Exception:
                    logger.debug("heartbeat write failed", exc_info=True)
            if self.total and self.done:
                frac = round(min(1.0, self.done / self.total), 3)
                if frac != self._sent:
                    self._sent = frac
                    try:
                        await _patch(self.job_ulid, progress=frac)
                    except Exception:
                        logger.debug("progress write failed", exc_info=True)

    def start(self) -> None:
        self._task = asyncio.create_task(self._tick())

    async def stop(self) -> None:
        if self._stage:
            self.timings[self._stage] = round((time.perf_counter() - self._t) * 1000, 1)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


@dataclass(frozen=True)
class _UploadSnapshot:
    """The fields the download reads, detached from the session."""

    ulid: str
    org_id: str
    purpose: str
    filename: str
    object_key: str
    expected_size_bytes: int
    expected_checksum_sha256: str


def _snapshot(upload: DirectUpload) -> _UploadSnapshot:
    """The fields the download reads, detached from the session."""
    return _UploadSnapshot(
        ulid=upload.ulid, org_id=upload.org_id, purpose=upload.purpose, filename=upload.filename,
        object_key=upload.object_key, expected_size_bytes=upload.expected_size_bytes,
        expected_checksum_sha256=upload.expected_checksum_sha256,
    )


async def _claim(job_ulid: str) -> Optional[tuple[dict, _UploadSnapshot]]:
    from src.services.stored_check_service import JOB_TYPE

    async with get_session_factory()() as session:
        job = (await session.execute(
            select(Job).where(Job.ulid == job_ulid, Job.job_type == JOB_TYPE).with_for_update()
        )).scalars().first()
        if job is None or job.status in ("done", "failed"):
            return None
        params = dict(job.params_json or {})
        upload = (await session.execute(
            select(DirectUpload).where(
                DirectUpload.ulid == params.get("direct_upload_id"),
                DirectUpload.org_id == job.org_id,
            ).with_for_update()
        )).scalars().first()
        if upload is None or upload.status not in ("attached", "preparing"):
            job.status = "failed"
            job.completed_at = _now()
            job.params_json = _without_sealed_link(job.params_json)
            job.result_json = {**(job.result_json or {}), "stage": "failed", "error": {
                "code": "UPLOAD_GONE", "message": "The uploaded file is no longer stored. Upload it again to check it."}}
            await session.commit()
            return None
        job.status = "running"
        job.started_at = job.started_at or _now()
        upload.status = "preparing"
        upload.preparation_started_at = _now()
        upload.prepare_attempts = (upload.prepare_attempts or 0) + 1
        await session.commit()
        return {"params": params, "user_id": job.user_id, "org_id": job.org_id}, _snapshot(upload)


async def _finish(job_ulid: str, *, ok: bool, result: dict, error: Optional[_Failed] = None) -> None:
    from src.services import direct_upload_service as uploads

    async with get_session_factory()() as session:
        job = (await session.execute(select(Job).where(Job.ulid == job_ulid).with_for_update())).scalars().first()
        if job is None:
            return
        job.status = "done" if ok else "failed"
        job.completed_at = _now()
        merged = {**(job.result_json or {}), **result, "stage": "done" if ok else "failed", "progress": 1.0 if ok else None}
        if error is not None:
            merged["error"] = {"code": error.code, "message": error.message, "charged": error.charged}
        # The analysis is named in result_json only: jobs has one row per
        # (analysis, job type), and checks of the same bytes share an analysis.
        merged.pop("analysis_row_id", None)
        job.result_json = merged
        params = job.params_json or {}
        job.params_json = _without_sealed_link(params)
        upload = (await session.execute(
            select(DirectUpload).where(
                DirectUpload.ulid == params.get("direct_upload_id"), DirectUpload.org_id == job.org_id,
            ).with_for_update()
        )).scalars().first()
        await session.commit()
        if upload is not None and upload.status in ("attached", "preparing"):
            await uploads.finish_part_upload(
                session, upload, ok=ok,
                error_code=error.code if error else None, error_message=error.message if error else None,
            )


def _without_sealed_link(params: Optional[dict]) -> Optional[dict]:
    from src.services.stored_check_service import without_sealed_link

    return without_sealed_link(params)


async def _forget_sealed_link(job_ulid: str) -> None:
    """Drop the sealed link from the job row: read once, never kept."""
    from src.services.stored_check_service import LINK_SEALED_PARAM

    async with get_session_factory()() as session:
        await session.execute(
            text("UPDATE jobs SET params_json = params_json - CAST(:k AS text) WHERE ulid = :u"),
            {"k": LINK_SEALED_PARAM, "u": job_ulid},
        )
        await session.commit()


async def _fetch_link(job_ulid: str, params: dict, upload: _UploadSnapshot, progress: "_Progress", result: dict) -> tuple[str, str]:
    """The ``fetching`` stage: the linked file to local disk, then its upload row and job updated."""
    from src.services import direct_upload_service as uploads
    from src.services import link_import
    from src.services.stored_check_service import LINK_SEALED_PARAM

    sealed = params.get(LINK_SEALED_PARAM)
    await _forget_sealed_link(job_ulid)
    label = (params.get("link") or {}).get("label") or "the link"
    await progress.stage("fetching", fetching_from=label)
    if not link_import.link_import_enabled():
        raise _Failed("LINK_IMPORT_OFF", "Import from a link is off on this server. Nothing was charged.")
    try:
        plan = link_import.plan_link(link_import.open_sealed_url(sealed))
    except (link_import.LinkRefused, link_import.LinkFetchError) as exc:
        raise _Failed(exc.code, f"{exc.message} Nothing was charged.") from None

    def on_bytes(done: int, total: Optional[int]) -> None:
        progress.total = total or 0
        progress.bytes_done(done)

    try:
        fetched = await link_import.fetch_to_file(plan, max_bytes=uploads.part_max_size_bytes(), on_bytes=on_bytes)
    except link_import.LinkFetchError as exc:
        raise _Failed(exc.code, f"{exc.message} Nothing was charged.") from None
    try:
        name = link_import.choose_filename(params.get("given_filename"), fetched.filename, plan.filename_hint)
        async with get_session_factory()() as session:
            row = (await session.execute(
                select(DirectUpload).where(DirectUpload.ulid == upload.ulid, DirectUpload.org_id == upload.org_id).with_for_update()
            )).scalars().first()
            if row is None:
                raise _Failed("UPLOAD_GONE", "The link's upload record is gone. Paste the link again. Nothing was charged.")
            await uploads.record_link_fetched(session, row, size_bytes=fetched.size, sha256=fetched.sha256, filename=name)
            import json

            await session.execute(
                text("UPDATE jobs SET params_json = params_json || CAST(:p AS jsonb) WHERE ulid = :u"),
                {"p": json.dumps({"filename": name, "size_bytes": fetched.size}), "u": job_ulid},
            )
            await session.commit()
    except link_import.LinkFetchError as exc:
        _unlink(fetched.path)
        raise _Failed(exc.code, f"{exc.message} Nothing was charged.") from None
    except BaseException:
        _unlink(fetched.path)
        raise
    result["fetched_bytes"] = fetched.size
    await _patch(job_ulid, fetched_bytes=fetched.size)
    logger.info("link fetched for %s: %d bytes from %s", job_ulid, fetched.size, fetched.final_host)
    return fetched.path, name


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


async def _owned_processes(session, org_id: str) -> Optional[str]:
    from src.db.models import MachineInstance
    from src.jobs.batch_tasks import _catalog_owned_processes

    owned = _catalog_owned_processes((await session.execute(
        select(MachineInstance.process).where(MachineInstance.org_id == org_id)
    )).scalars().all())
    return owned or None


async def _admit(user, name: str, data: bytes) -> tuple[Optional[str], str]:
    """Reserve the check as an upload of the same file would; returns (check_id, identity)."""
    from fastapi import HTTPException

    from src.auth.catalog_allowance import file_identity
    from src.auth.validation_caps import SAMPLE_PART_SHA256, _needs_new_slot, derived_copy_parent, reserve_check

    identity = file_identity(name, data)
    content = hashlib.sha256(data).hexdigest()
    if content in SAMPLE_PART_SHA256:
        return None, identity
    try:
        if await _needs_new_slot(user.user_id, identity) and await derived_copy_parent(user, content):
            return None, identity
        return await reserve_check(user.user_id, None, identity, "analysis"), identity
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        raise _Failed(str(detail.get("code") or "check_refused"), str(detail.get("message") or "This check wasn't started.")) from exc


# A check that found no room in the worker's compute budget within its wait
# goes back to the queue and starts again this many seconds later.
ROOM_REQUEUE_DEFER_SECONDS = 15


async def requeue_for_room(ctx: dict, job_ulid: str) -> dict:
    """No room in the compute budget within the wait: back in the queue, nothing charged or lost.

    The job row returns to ``queued`` and a fresh arq job (its own id: the
    first one's id stays taken while arq keeps its result) runs it again after
    ``ROOM_REQUEUE_DEFER_SECONDS``. The upload stays stored; the next run
    downloads and sizes it again.
    """
    async with get_session_factory()() as session:
        job = (await session.execute(select(Job).where(Job.ulid == job_ulid).with_for_update())).scalars().first()
        if job is None or job.status in ("done", "failed"):
            return {"skipped": True}
        times = int((job.result_json or {}).get("requeued_for_room") or 0) + 1
        job.status = "queued"
        job.result_json = {**(job.result_json or {}), "stage": "queued", "progress": None,
                           "waiting_for_room": True, "requeued_for_room": times}
        await session.commit()
    pool = ctx.get("redis") or ctx.get("pool")
    try:
        if pool is None:
            raise RuntimeError("no Redis pool in the worker context")
        await pool.enqueue_job("run_stored_check", job_ulid, _job_id=f"{job_ulid}:room:{times}",
                               _defer_by=ROOM_REQUEUE_DEFER_SECONDS)
    except Exception:
        # The queued row is the durable intent: the reconcile cron offers it again.
        logger.exception("stored check %s could not be queued again; the reconcile cron will", job_ulid)
    logger.info("stored check %s waited for compute room; queued again (%d)", job_ulid, times)
    return {"requeued": True, "times": times}


async def run_stored_check(ctx: dict, job_ulid: str) -> dict:
    """Check one stored part, stage by stage (see the module docstring).

    From its sizing to its end the check holds room in the worker's compute
    budget (``src.services.compute_budget``), sized by its memory need.
    """
    from src.services import compute_budget

    # A big kept part's re-price or repair runs as this task too (same ceiling, one try).
    from src.services.kept_part_jobs import is_kept_job

    if await is_kept_job(job_ulid):
        from src.jobs.kept_part_tasks import run_kept_part

        return await run_kept_part(ctx, job_ulid)

    async with compute_budget.deferred_hold(label="big check") as room:
        return await _check_stored_part(ctx, job_ulid, room)


async def _check_stored_part(ctx: dict, job_ulid: str, room) -> dict:
    from fastapi import HTTPException
    from starlette.datastructures import Headers, UploadFile

    from src.auth.require_api_key import AuthedUser
    from src.auth.validation_caps import finish_check, reserve_check
    from src.config.check_limits import larger_limits
    from src.services import analysis_service, compute_budget
    from src.services import direct_upload_service as uploads
    from src.services import stored_check_service as svc
    from src.services.part_archive import PartArchiveError, compression_of, unpack_part

    started = time.monotonic()
    claimed = await _claim(job_ulid)
    if claimed is None:
        return {"skipped": True}
    meta, upload = claimed
    params = meta["params"]
    progress = _Progress(job_ulid)
    progress.start()
    paths: list[str] = []
    result: dict[str, Any] = {}
    check_id: Optional[str] = None
    identity = None
    op: Optional[str] = None
    user = AuthedUser(user_id=meta["user_id"], api_key_id=0, key_prefix="worker", role="analyst", org_id=meta["org_id"])
    try:
        if params.get("source") == svc.SOURCE_LINK:
            # -- fetching (a share link) ---------------------------------
            path, name = await _fetch_link(job_ulid, params, upload, progress, result)
            paths.append(path)
        else:
            # -- verifying -----------------------------------------------
            await progress.stage("verifying")
            progress.total = int(upload.expected_size_bytes)
            try:
                path = await asyncio.to_thread(uploads.download_to_bounded_tempfile, upload, progress.bytes_done)
            except uploads.DirectUploadError as exc:
                raise _Failed(exc.code, exc.message) from exc
            paths.append(path)
            name = upload.filename

        # -- unpacking ---------------------------------------------------
        if compression_of(name) != "none":
            await progress.stage("unpacking")
            try:
                part = await asyncio.to_thread(unpack_part, path, name, max_bytes=uploads.part_max_size_bytes())
            except PartArchiveError as exc:
                raise _Failed(exc.code, exc.message) from exc
            if part.path != path:
                paths.append(part.path)
            path, name = part.path, part.filename
        part_bytes = os.path.getsize(path)
        result.update(part_filename=name, part_bytes=part_bytes)

        # -- sizing ------------------------------------------------------
        await progress.stage("sizing", part_filename=name, part_bytes=part_bytes)
        need, basis = svc.estimate_memory_bytes(path, name)
        budget = svc.check_memory_budget_bytes()
        result["memory"] = {"need_bytes": need, "budget_bytes": budget, "basis": basis}
        if need > budget:
            raise _Failed("CHECK_TOO_LARGE", svc.too_heavy_message(need, basis, budget))

        # Room in the compute budget for the whole check, waiting for the parts
        # already being checked; its time limits start once it has room. The wait
        # leaves the job time for its own work, then the check goes back to the
        # queue. A link's file was fetched once and isn't kept, so a link check
        # waits for as long as its job allows instead.
        budget_sec = svc.time_budget_sec(part_bytes, name)
        if params.get("source") == svc.SOURCE_LINK:
            room.wait = compute_budget.job_wait_seconds(
                started, 0.0, svc.STORED_CHECK_JOB_TIMEOUT_SECONDS, margin=60.0)
        else:
            room.wait = compute_budget.job_wait_seconds(
                started, 2 * budget_sec, svc.STORED_CHECK_JOB_TIMEOUT_SECONDS)
        await _patch(job_ulid, waiting_for_room=True)
        await room.take(need)
        await _patch(job_ulid, waiting_for_room=False)

        data = await asyncio.to_thread(lambda: open(path, "rb").read())
        mesh_hash = hashlib.sha256(data).hexdigest()
        result["mesh_hash"] = mesh_hash
        check_id, identity = await _admit(user, name, data)

        # -- measuring ---------------------------------------------------
        await progress.stage("measuring", mesh_hash=mesh_hash, memory=result["memory"])
        op = "analysis"
        factory = get_session_factory()
        with larger_limits(budget_sec=budget_sec, max_triangles=_BIG_MAX_TRIANGLES, max_bytes=uploads.part_max_size_bytes()):
            async with factory() as session:
                try:
                    run = await analysis_service.run_analysis(
                        file_bytes=data, filename=name, processes=None, rule_pack=None, user=user, session=session,
                        org_id=meta["org_id"], source_units=params.get("units"), return_persisted_id=True,
                        orientation=params.get("orientation"),
                    )
                except compute_budget.MeshBusy as exc:
                    raise _Failed("CHECK_BUSY", "The worker was too busy to mesh this part in time. "
                                  "Nothing was charged; check the file again.") from exc
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                    raise _Failed("CHECK_UNREADABLE" if exc.status_code < 500 else "CHECK_TIMEOUT",
                                  str(detail.get("message") or exc.detail), charged=False) from exc
                if not isinstance(run, analysis_service.AnalysisRun) or run.analysis_id is None:
                    raise _Failed("CHECK_FAILED", "The analysis finished without a saved record.")
                await session.commit()  # the analysis and the kept source, durable before pricing
                result["analysis_row_id"] = run.analysis_id
                result["analysis_timings_ms"] = run.stage_timings_ms
                from src.db.models import Analysis

                result["analysis_id"] = (await session.execute(
                    select(Analysis.ulid).where(Analysis.id == run.analysis_id)
                )).scalar_one_or_none()
                if check_id:
                    await finish_check(user.user_id, check_id, "analysis", True)
                op = None

                # -- pricing ---------------------------------------------
                await progress.stage("pricing", analysis_id=result["analysis_id"])
                if check_id:
                    await reserve_check(user.user_id, check_id, identity, "cost")
                op = "cost"
                from src.api.routes import _run_cost_decision
                from src.services.cad_fix_service import DEFAULT_QUANTITIES

                upload_file = UploadFile(file=io.BytesIO(data), filename=name,
                                         headers=Headers({"content-type": "application/octet-stream"}))
                try:
                    report = await _run_cost_decision(
                        file=upload_file,
                        qty=params.get("qty") or ",".join(str(q) for q in DEFAULT_QUANTITIES),
                        region=None, cavities=1, complexity="moderate",
                        material_class=params.get("material_class") or "polymer",
                        owned_processes=await _owned_processes(session, meta["org_id"]),
                        units=params.get("units"), user=user, session=session,
                        orientation=params.get("orientation"),
                        # The job's organization, never the person's active one: they
                        # may have switched while the check waited.
                        org_id=meta["org_id"],
                    )
                    saved = (report or {}).get("saved") or {}
                    result["cost_decision_id"] = saved.get("id")
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, dict) else {}
                    if exc.status_code == 400 and detail.get("code") == "GEOMETRY_INVALID":
                        result["geometry_invalid"] = str(detail.get("message") or "not a closed solid")
                    else:
                        message = detail.get("message") if detail else exc.detail
                        result["cost_error"] = str(message or "Pricing didn't finish.")
                await session.commit()  # the cost decision
                if check_id:
                    await finish_check(user.user_id, check_id, "cost", "cost_error" not in result)
                op = None
                await _keep_preview(meta["org_id"], mesh_hash, name, data, params.get("units"), result)
        await progress.stop()
        result["timings_ms"] = progress.timings
        await _finish(job_ulid, ok=True, result=result)
        logger.info("stored check %s done: %s bytes in %s", job_ulid, part_bytes, progress.timings)
        return {"ok": True}
    except _Failed as exc:
        await progress.stop()
        if check_id and op:
            await _release(user.user_id, check_id, op)
        result["timings_ms"] = progress.timings
        await _finish(job_ulid, ok=False, result=result, error=exc)
        logger.info("stored check %s refused: %s", job_ulid, exc.code)
        return {"ok": False, "code": exc.code}
    except compute_budget.ComputeBusy as exc:
        # Before anything was reserved or measured (the room comes first).
        await progress.stop()
        if params.get("source") != svc.SOURCE_LINK:
            return await requeue_for_room(ctx, job_ulid)
        minutes = max(1, round(exc.waited_s / 60))
        await _finish(job_ulid, ok=False, result=result, error=_Failed(
            "CHECK_BUSY", f"The worker stayed busy with other checks for {minutes} minutes, so this one "
            "didn't start. Nothing was charged; import the link again."))
        return {"ok": False, "code": "CHECK_BUSY"}
    except asyncio.CancelledError:
        # arq cancels a task at its time limit, and every running task when the
        # worker stops (a release, a restart). Say which.
        await progress.stop()
        if check_id and op:
            await _release(user.user_id, check_id, op)
        timed_out = time.monotonic() - started >= svc.STORED_CHECK_JOB_TIMEOUT_SECONDS - 5
        await _finish(job_ulid, ok=False, result=result, error=_Failed(
            "CHECK_TIMEOUT", "The check ran past its time limit. Nothing was charged.") if timed_out else _Failed(
            "CHECK_INTERRUPTED", "The check was interrupted before it finished: the worker restarted. "
            "Nothing was charged; check the file again."))
        raise
    except Exception as exc:  # noqa: BLE001 - the job must end with an honest state
        await progress.stop()
        logger.exception("stored check %s failed", job_ulid)
        if check_id and op:
            await _release(user.user_id, check_id, op)
        await _finish(job_ulid, ok=False, result=result, error=_Failed(
            "CHECK_FAILED", "The check didn't finish because of an error on our side. Nothing was charged."))
        return {"ok": False}
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        _give_memory_back(result.get("mesh_hash"))


def _give_memory_back(mesh_hash: Optional[str]) -> None:
    """After a big check: drop its parse from the mesh cache and hand freed memory to the OS.

    One big mesh would otherwise sit in the parsed-mesh cache, and glibc keeps
    the arenas a 2 GB check freed, so the worker's resident size stays at its
    peak for the batch items and checks that follow.
    """
    import gc

    try:
        if mesh_hash:
            from src.parsers import mesh_cache

            mesh_cache.forget_hashes([mesh_hash])
    except Exception:
        logger.debug("mesh cache forget failed", exc_info=True)
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


async def _keep_preview(org_id: str, mesh_hash: str, name: str, data: bytes, units: Optional[str], result: dict) -> None:
    """Build and keep the part's 3D preview now, while its parse is cached in this process.

    The part's page then serves it as is (GET /parts/{hash}/preview.glb) instead
    of parsing a big file in a web request. Best effort: without it the page
    builds the preview the usual way.
    """
    from src.api.routes import _build_preview_glb, _parse_mesh_async
    from src.costing.units import mesh_source_units, scale_mesh_to_mm
    from src.services.source_artifact_service import save_preview_glb

    try:
        t = time.perf_counter()
        suffix = os.path.splitext(name.lower())[1]
        filename = f"source{suffix}"
        mesh, parsed_suffix = await _parse_mesh_async(data, filename)
        # The part's page asks for the mm interpretation (preview.glb?units=mm).
        mesh = scale_mesh_to_mm(mesh, mesh_source_units(filename, "mm"))
        from src.services import compute_budget

        glb, original_faces, preview_faces, decimated, face_hash = await compute_budget.run_within_budget(
            _build_preview_glb, mesh, filename, for_analysis=True, label="big check preview"
        )
        await save_preview_glb(org_id, mesh_hash, glb, {
            "X-Mesh-Original-Faces": str(original_faces),
            "X-Mesh-Preview-Faces": str(preview_faces),
            "X-Mesh-Decimated": "true" if decimated else "false",
            "X-Mesh-Source": parsed_suffix.lstrip("."),
            "X-Mesh-Face-Space": "analysis",
            "X-Mesh-Face-Hash": face_hash,
        }, source_units="mm")
        result["preview_ms"] = round((time.perf_counter() - t) * 1000, 1)
    except Exception:
        logger.warning("stored check preview not kept for %s", mesh_hash[:12], exc_info=True)


async def _release(user_id: int, check_id: str, op: str) -> None:
    from src.auth.validation_caps import finish_check

    try:
        await finish_check(user_id, check_id, op, False)
    except Exception:
        logger.warning("could not release check %s/%s", check_id, op, exc_info=True)


async def sweep_stalled_stored_checks(ctx: dict) -> int:
    """Cron: end checks whose worker died mid-check (no heartbeat for STALLED_AFTER)."""
    from src.services.stored_check_service import fail_stalled_checks

    async with get_session_factory()() as session:
        ended = await fail_stalled_checks(session)
    if ended:
        logger.info("ended %d stalled stored checks", ended)
    return ended
