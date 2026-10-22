"""Worker task: check one part from its stored upload (``stored_check_service``).

Stages, written to the job row as they start (``result_json.stage``):

    verifying  download the stored object to local disk, checking size and SHA-256
    unpacking  a .gz or one-part ZIP, bomb-safe (``part_archive``)
    sizing     estimate the memory the check needs; refuse honestly when over budget
    measuring  the DFM analysis (``analysis_service.run_analysis``, as POST /validate)
    pricing    the cost decision (``routes._run_cost_decision``, as POST /validate/cost)
    done       or ``failed`` with ``error: {code, message}``

The check counts against the account's allowance exactly as an upload of the
same file does; nothing is charged when it fails before measuring.
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
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from sqlalchemy import select, text

from src.db.engine import get_session_factory
from src.db.models import DirectUpload, Job

logger = logging.getLogger("cadverify.stored_check_tasks")

# Triangle ceiling for a big check: memory (the sizing stage) is the real bound.
_BIG_MAX_TRIANGLES = 200_000_000


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
        while True:
            await asyncio.sleep(2.0)
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


def _snapshot(upload: DirectUpload) -> SimpleNamespace:
    """The fields the download reads, detached from the session."""
    return SimpleNamespace(
        ulid=upload.ulid, org_id=upload.org_id, purpose=upload.purpose, filename=upload.filename,
        object_key=upload.object_key, expected_size_bytes=upload.expected_size_bytes,
        expected_checksum_sha256=upload.expected_checksum_sha256,
    )


async def _claim(job_ulid: str) -> Optional[tuple[dict, SimpleNamespace]]:
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


async def run_stored_check(ctx: dict, job_ulid: str) -> dict:
    """Check one stored part, stage by stage (see the module docstring)."""
    from fastapi import HTTPException
    from starlette.datastructures import Headers, UploadFile

    from src.auth.require_api_key import AuthedUser
    from src.auth.validation_caps import finish_check, reserve_check
    from src.config.check_limits import larger_limits
    from src.services import analysis_service
    from src.services import direct_upload_service as uploads
    from src.services import stored_check_service as svc
    from src.services.part_archive import PartArchiveError, compression_of, unpack_part

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
        # -- verifying ---------------------------------------------------
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

        data = await asyncio.to_thread(lambda: open(path, "rb").read())
        mesh_hash = hashlib.sha256(data).hexdigest()
        result["mesh_hash"] = mesh_hash
        check_id, identity = await _admit(user, name, data)

        # -- measuring ---------------------------------------------------
        await progress.stage("measuring", mesh_hash=mesh_hash, memory=result["memory"])
        op = "analysis"
        budget_sec = svc.time_budget_sec(part_bytes, name)
        factory = get_session_factory()
        with larger_limits(budget_sec=budget_sec, max_triangles=_BIG_MAX_TRIANGLES, max_bytes=uploads.part_max_size_bytes()):
            async with factory() as session:
                try:
                    run = await analysis_service.run_analysis(
                        file_bytes=data, filename=name, processes=None, rule_pack=None, user=user, session=session,
                        org_id=meta["org_id"], source_units=params.get("units"), return_persisted_id=True,
                        orientation=params.get("orientation"),
                    )
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
    except asyncio.CancelledError:
        await progress.stop()
        if check_id and op:
            await _release(user.user_id, check_id, op)
        await _finish(job_ulid, ok=False, result=result, error=_Failed(
            "CHECK_TIMEOUT", "The check ran past its time limit. Nothing was charged."))
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
        glb, original_faces, preview_faces, decimated, face_hash = await asyncio.to_thread(
            _build_preview_glb, mesh, filename, for_analysis=True
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
