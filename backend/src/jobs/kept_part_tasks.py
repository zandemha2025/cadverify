"""Worker task: re-price or repair a big kept part (``src.services.kept_part_jobs``).

Runs as ``run_stored_check`` (the same arq function, ceiling and single try as a
big file's check), which hands a job whose ``params.source`` is ``kept`` here.
Stages, written to the job row as they start (``result_json.stage``):

    sizing     the kept file's memory need against this worker's budget; refused
               honestly over it ("needs about ... of memory ... Nothing was charged.")
    pricing    a re-price: ``part_recheck.recheck_kept``, the route's own code
    repairing  a mesh repair: ``repair_service.repair_stored``, the route's own code
    done       ``result`` holds the response the route would have given
    failed     ``error: {code, message, charged: false}``

Both run under the big-check limits (``src.config.check_limits``): the worker's
file-size ceiling and a time budget from the file's size, instead of a web
request's. Nothing is charged: neither uses a check.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from sqlalchemy import select

from src.db.engine import get_session_factory
from src.db.models import Job
from src.jobs.stored_check_tasks import _BIG_MAX_TRIANGLES, _Failed, _give_memory_back, _now, _Progress

logger = logging.getLogger("cadverify.kept_part_tasks")


async def _claim(job_ulid: str) -> Optional[dict[str, Any]]:
    async with get_session_factory()() as session:
        job = (await session.execute(select(Job).where(Job.ulid == job_ulid).with_for_update())).scalars().first()
        if job is None or job.status in ("done", "failed"):
            return None
        job.status = "running"
        job.started_at = job.started_at or _now()
        await session.commit()
        return {"params": dict(job.params_json or {}), "user_id": job.user_id, "org_id": job.org_id}


async def _finish(job_ulid: str, *, ok: bool, result: dict, error: Optional[_Failed] = None) -> None:
    async with get_session_factory()() as session:
        job = (await session.execute(select(Job).where(Job.ulid == job_ulid).with_for_update())).scalars().first()
        if job is None:
            return
        job.status = "done" if ok else "failed"
        job.completed_at = _now()
        merged = {**(job.result_json or {}), **result, "stage": "done" if ok else "failed",
                  "progress": 1.0 if ok else None}
        if error is not None:
            merged["error"] = {"code": error.code, "message": error.message, "charged": False}
        job.result_json = merged
        await session.commit()


def _http_failure(exc, action: str) -> _Failed:
    """The route's own refusal (an HTTPException), as the job's error."""
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    message = str(detail.get("message") or detail.get("detail") or exc.detail)
    if exc.status_code == 504:
        code = "CHECK_TIMEOUT"
    elif exc.status_code == 404:
        code = "PART_SOURCE_GONE"
    else:
        code = str(detail.get("code") or ("REPRICE_REFUSED" if action == "recheck" else "REPAIR_REFUSED"))
    if "Nothing was charged" not in message:
        message = f"{message.rstrip('.')}. Nothing was charged."
    return _Failed(code, message)


def _summary(action: str, report: dict) -> tuple[str, Optional[str]]:
    """(one line for the work bar, the part to open): the re-priced part, or the repaired copy."""
    if action == "recheck":
        return "Re-priced", None
    outcome = report.get("outcome")
    repaired = (report.get("repaired") or {}).get("mesh_hash")
    words = {"repaired": "Repaired", "closed_changed": "Repaired; the volume changed",
             "partly": "Partly repaired", "not_repaired": "Not repaired", "not_needed": "Already a closed solid"}
    return words.get(str(outcome), "Repair finished"), repaired


async def run_kept_part(ctx: dict, job_ulid: str) -> dict:
    """Re-price or repair one big kept part (see the module docstring)."""
    from fastapi import HTTPException, Response
    from fastapi.encoders import jsonable_encoder

    from src.auth.require_api_key import AuthedUser
    from src.config.check_limits import larger_limits
    from src.jobs.stored_check_tasks import requeue_for_room
    from src.services import compute_budget
    from src.services import direct_upload_service as uploads
    from src.services import kept_part_jobs as kept
    from src.services import stored_check_service as svc

    started = time.monotonic()
    claimed = await _claim(job_ulid)
    if claimed is None:
        return {"skipped": True}
    params, org_id = claimed["params"], claimed["org_id"]
    action, digest = params.get("action"), str(params.get("mesh_hash") or "")
    options = dict(params.get("options") or {})
    user = AuthedUser(user_id=claimed["user_id"], api_key_id=0, key_prefix="worker", role="analyst", org_id=org_id)
    progress = _Progress(job_ulid)
    progress.start()
    result: dict[str, Any] = {"action": action, "mesh_hash": digest}
    try:
        # -- sizing ------------------------------------------------------
        await progress.stage("sizing")
        info = await kept.kept_source_info(org_id, digest)
        if info is None:
            raise _Failed("PART_SOURCE_GONE", "This part's file is no longer kept, so it can't be "
                          f"{'re-priced' if action == kept.RECHECK else 'repaired'} from here. Nothing was charged.")
        name = str(params.get("filename") or f"part{info.suffix}")
        need, basis = kept.memory_need(info)
        budget = svc.check_memory_budget_bytes()
        result.update(part_filename=name, part_bytes=info.size,
                      memory={"need_bytes": need, "budget_bytes": budget, "basis": basis})
        if need > budget:
            raise _Failed("CHECK_TOO_LARGE", svc.too_heavy_message(need, basis, budget))

        budget_sec = svc.time_budget_sec(info.size, name)
        stage = "pricing" if action == kept.RECHECK else "repairing"
        # Room in the worker's compute budget for the whole job, waiting for the
        # parts already being checked (its time limit starts once it has room);
        # past the wait its job allows, it goes back to the queue.
        wait = compute_budget.job_wait_seconds(started, 2 * budget_sec, svc.STORED_CHECK_JOB_TIMEOUT_SECONDS)
        async with compute_budget.hold(need, wait=wait, label=f"kept part {action}"):
            await progress.stage(stage, part_filename=name, part_bytes=info.size, memory=result["memory"])
            with larger_limits(budget_sec=budget_sec, max_triangles=_BIG_MAX_TRIANGLES, max_bytes=uploads.part_max_size_bytes()):
                async with get_session_factory()() as session:
                    try:
                        if action == kept.RECHECK:
                            from src.api.part_recheck import recheck_kept

                            report = await recheck_kept(session, org_id=org_id, digest=digest, user=user,
                                                        response=Response(), **options)
                        elif action == kept.REPAIR:
                            from src.services import repair_service

                            report = await repair_service.repair_stored(
                                org_id=org_id, mesh_hash=digest, processes=options.get("processes"),
                                rule_pack=options.get("rule_pack"), quantities=options.get("quantities"),
                                material_class=options.get("material_class"),
                                with_cost=bool(options.get("with_cost", True)), user=user, session=session,
                            )
                            # The copy is served by its download URL, not inline on the job.
                            report["repaired_file_b64"] = None
                        else:
                            raise _Failed("JOB_UNKNOWN", "This job asked for something the worker doesn't do. Nothing was charged.")
                    except HTTPException as exc:
                        raise _http_failure(exc, str(action)) from exc
                    await session.commit()
        summary, open_hash = _summary(str(action), report)
        result.update(result=jsonable_encoder(report), summary=summary, open_hash=open_hash or digest)
        await progress.stop()
        result["timings_ms"] = progress.timings
        await _finish(job_ulid, ok=True, result=result)
        logger.info("kept part %s %s done: %s bytes in %s", digest[:12], action, info.size, progress.timings)
        return {"ok": True}
    except _Failed as exc:
        await progress.stop()
        result["timings_ms"] = progress.timings
        await _finish(job_ulid, ok=False, result=result, error=exc)
        logger.info("kept part %s %s refused: %s", digest[:12], action, exc.code)
        return {"ok": False, "code": exc.code}
    except compute_budget.ComputeBusy:
        await progress.stop()
        return await requeue_for_room(ctx, job_ulid)
    except asyncio.CancelledError:
        await progress.stop()
        timed_out = time.monotonic() - started >= svc.STORED_CHECK_JOB_TIMEOUT_SECONDS - 5
        await _finish(job_ulid, ok=False, result=result, error=_Failed(
            "CHECK_TIMEOUT", "This ran past its time limit. Nothing was charged.") if timed_out else _Failed(
            "CHECK_INTERRUPTED", "This was interrupted before it finished: the worker restarted. "
            "Nothing was charged; try again."))
        raise
    except Exception:  # noqa: BLE001 - the job must end with an honest state
        await progress.stop()
        logger.exception("kept part %s %s failed", digest[:12], action)
        await _finish(job_ulid, ok=False, result=result, error=_Failed(
            "CHECK_FAILED", "This didn't finish because of an error on our side. Nothing was charged."))
        return {"ok": False}
    finally:
        _give_memory_back(digest)
