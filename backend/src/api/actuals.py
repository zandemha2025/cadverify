"""Your actuals: import them the way you have them, see how close ScaleCAD came,
calibrate with them, and the pilot report.

Mounted at ``/api/v1/actuals``. Every route is org-scoped through
``resolve_org``: one organization's actuals, comparisons, calibrations and
reports never include another's.

* ``POST /preview``  (analyst): the file (CSV or .xlsx) + optional ``mapping``
  and ``choices`` (JSON form fields) -> the columns, the prefilled mapping, the
  process values, and every row's match (matched / ambiguous with candidates /
  unmatched with the reason / error). Nothing is saved.
* ``POST /import``   (analyst): the same inputs; imports every matched row
  without errors through the ground-truth create path and reports the rest.
* ``GET /accuracy``  (viewer, every plan): ``?part=<file hash>`` or
  ``?run=<run id>`` or all parts -> per-actual comparison + summary, and the
  calibration in effect.
* ``GET /calibration`` (viewer, every plan): what a calibration would change
  (fitted on all the org's actuals, held out part by part) and the history.
* ``POST /calibration/apply`` (analyst, pilot plan): apply it to future estimates.
* ``POST /calibration/undo``  (analyst): undo the one in effect.
* ``GET /report`` and ``GET /report.pdf`` (viewer): the pilot report for
  ``?run=<run id>`` or every part.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.kill_switch import require_kill_switch_open
from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.auth.validation_caps import require_paid_access
from src.db.engine import get_db_session
from src.services import accuracy_service as acc
from src.services import actuals_service as svc
from src.services import calibration_service as cal
from src.services import pilot_report_service as report_svc

logger = logging.getLogger("cadverify.actuals")

router = APIRouter(tags=["actuals"])

_CHUNK = 1024 * 1024


async def _org(session: AsyncSession, user: AuthedUser) -> str:
    org_id = await resolve_org(session, user.user_id)
    if not org_id:
        raise HTTPException(status_code=403, detail="No organization for caller.")
    return org_id


async def _read(file: UploadFile) -> bytes:
    from src.api.groundtruth import _import_cap_bytes

    limit = _import_cap_bytes()
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(status_code=413, detail=f"The file is over the {limit // (1024 * 1024)} MB import limit.")
    if not buf:
        raise HTTPException(status_code=400, detail="The file is empty.")
    return bytes(buf)


def _json_form(raw: Optional[str], name: str) -> Optional[dict]:
    if raw is None or not raw.strip():
        return None
    if len(raw) > 200_000:
        raise HTTPException(status_code=400, detail=f"{name} is too long.")
    try:
        value = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{name} must be JSON.")
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{name} must be a JSON object.")
    return value


@router.post("/preview")
@limiter.limit("120/hour;1000/day")
async def preview_actuals(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    mapping: Optional[str] = Form(None),
    choices: Optional[str] = Form(None),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    data = await _read(file)
    try:
        return await svc.preview(session, org_id, file.filename or "actuals.csv", data,
                                 _json_form(mapping, "mapping"), _json_form(choices, "choices"))
    except svc.TableError as exc:
        raise HTTPException(status_code=422, detail={"code": "unreadable", "message": str(exc)})


@router.post("/import", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;100/day")
async def import_actuals(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    mapping: Optional[str] = Form(None),
    choices: Optional[str] = Form(None),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    data = await _read(file)
    try:
        out = await svc.import_rows(session, org_id, user.user_id, file.filename or "actuals.csv", data,
                                    _json_form(mapping, "mapping"), _json_form(choices, "choices"))
    except svc.TableError as exc:
        raise HTTPException(status_code=422, detail={"code": "unreadable", "message": str(exc)})
    from src.services.audit_service import emit_event

    await emit_event(session, user.user_id, "actuals.imported", "ground_truth", None,
                     {"org_id": org_id, "imported": out["imported"], "parts": out["parts"],
                      "test": out["test"], "rows": out["rows"]}, org_id=org_id)
    await session.commit()
    return out


async def _calibration_public(session: AsyncSession, org_id: str) -> Optional[dict]:
    hist = await cal.public_history(session, org_id)
    return next((h for h in hist if h["in_effect"]), None)


@router.get("/accuracy")
@limiter.limit("240/hour;3000/day")
async def get_accuracy(
    request: Request,
    response: Response,
    part: Optional[str] = Query(None, max_length=128, pattern=r"^[0-9a-fA-F]{8,128}$"),
    run: Optional[str] = Query(None, max_length=64, pattern=r"^[0-9A-Za-z]{10,64}$"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    scope = acc.Scope(part_key=part.lower() if part else None)
    if run and not part:
        keys = await acc.run_part_keys(session, org_id, run)
        if keys is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        scope = acc.Scope(keys=keys)
    out = await acc.accuracy(session, org_id, scope)
    out["calibration"] = await _calibration_public(session, org_id)
    out["scope"] = {"part": scope.part_key, "run": run if run and not part else None}
    return out


async def _plan(session: AsyncSession, user_id: int) -> Optional[str]:
    from src.db.models import User

    return (await session.execute(select(User.plan).where(User.id == user_id))).scalar_one_or_none()


@router.get("/calibration")
@limiter.limit("240/hour;3000/day")
async def get_calibration(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    rows = await acc.comparisons(session, org_id, acc.Scope())
    return {
        "proposal": acc.proposal(rows),
        "history": await cal.public_history(session, org_id),
        "can_apply": (await _plan(session, user.user_id)) == "pilot",
    }


class ApplyIn(BaseModel):
    processes: Optional[list[str]] = Field(None, max_length=40)


@router.post("/calibration/apply", dependencies=[Depends(require_kill_switch_open), Depends(require_paid_access)])
@limiter.limit("20/hour;100/day")
async def apply_calibration(
    request: Request,
    response: Response,
    body: ApplyIn,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    try:
        row = await cal.apply(session, org_id, user.user_id, body.processes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "nothing_to_apply", "message": str(exc)})
    from src.services.audit_service import emit_event

    await emit_event(session, user.user_id, "calibration.applied", "org_calibration", row.ulid,
                     {"org_id": org_id, "factors": row.factors}, org_id=org_id)
    # Saved decisions (and their sign-offs) were priced before this calibration.
    from src.services import cost_decision_service

    await cost_decision_service.mark_org_decisions_stale(
        session, org_id, reason=cost_decision_service.CALIBRATION_STALE_REASON)
    await session.commit()
    return {"applied": await _calibration_public(session, org_id),
            "history": await cal.public_history(session, org_id)}


@router.post("/calibration/undo", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("20/hour;100/day")
async def undo_calibration(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    row = await cal.undo(session, org_id, user.user_id)
    if row is None:
        raise HTTPException(status_code=409, detail={"code": "nothing_applied", "message": "No calibration is in effect."})
    from src.services.audit_service import emit_event

    await emit_event(session, user.user_id, "calibration.undone", "org_calibration", row.ulid,
                     {"org_id": org_id}, org_id=org_id)
    from src.services import cost_decision_service

    await cost_decision_service.mark_org_decisions_stale(
        session, org_id, reason=cost_decision_service.CALIBRATION_STALE_REASON)
    await session.commit()
    return {"undone": row.ulid, "in_effect": await _calibration_public(session, org_id),
            "history": await cal.public_history(session, org_id)}


@router.get("/report")
@limiter.limit("120/hour;1000/day")
async def get_report(
    request: Request,
    response: Response,
    run: Optional[str] = Query(None, max_length=64, pattern=r"^[0-9A-Za-z]{10,64}$"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    org_id = await _org(session, user)
    try:
        return await report_svc.build_report(session, org_id, run)
    except report_svc.ReportNotFound:
        raise HTTPException(status_code=404, detail="Run not found.")


@router.get("/report.pdf")
@limiter.limit("60/hour;500/day")
async def get_report_pdf(
    request: Request,
    run: Optional[str] = Query(None, max_length=64, pattern=r"^[0-9A-Za-z]{10,64}$"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    org_id = await _org(session, user)
    try:
        rep = await report_svc.build_report(session, org_id, run)
    except report_svc.ReportNotFound:
        raise HTTPException(status_code=404, detail="Run not found.")
    pdf = await report_svc.render_pdf(rep)
    name = f"scalecad-pilot-report-{(rep['generated_at'] or '')[:10]}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
