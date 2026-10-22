"""Re-check a part from the organization's kept source: no upload, no check.

``POST /parts/{mesh_hash}/recheck`` runs the same should-cost decision as
``POST /validate/cost`` (``routes._run_cost_decision``) on the exact bytes the
organization kept when the part was checked, and saves the decision the same
way. It is how a saved part is priced in another material or at other
quantities, re-checked against the org's machines (``owned_processes``), its
service conditions (applied server-side, as for an upload) or a new
orientation, without anyone picking the file again. The kept bytes are never
returned.

``POST /parts/{mesh_hash}/bodies`` checks every body of a multi-body file (a
weldment, a part with its fixture, parts saved together) as its own part, from
the same kept file (``body_check_service``); ``POST /parts/{mesh_hash}/bodies/
{n}/part`` makes body n a part of its own, an STL copy recorded as derived from
this part, so checking it uses no check.

Boundaries match the other stored-source routes (``part_preview``,
``part_fixes``): an org member in the caller's active org; another org's hash,
a malformed hash and a part with no kept source are the same 404. The part was
checked when its source was kept, so no check is reserved or used (no
validation-cap or org-limit dependency); free accounts get a per-user ceiling
(``limit_free_recheck``). Kill switch, admission control, the route limit and
the upload size limit all apply.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admission import admit_analysis
from src.auth.free_tool_limits import limit_free_fixes, limit_free_recheck
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, Role, require_org_role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session

router = APIRouter(tags=["parts"])

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
NOT_FOUND = "No stored source for this part in your organization."


async def _kept_name(session: AsyncSession, org_id: str, mesh_hash: str, suffix: str) -> str:
    """The name the part was checked under: its latest cost record, else its analysis."""
    from sqlalchemy import desc, select

    from src.db.models import CostDecision
    from src.services.cad_fix_service import latest_analysis

    name = None
    try:
        name = (await session.execute(
            select(CostDecision.filename)
            .where(CostDecision.org_id == org_id, CostDecision.mesh_hash == mesh_hash)
            .order_by(desc(CostDecision.created_at)).limit(1)
        )).scalar_one_or_none()
    except Exception:
        name = None
    if not isinstance(name, str) or not name:
        saved = await latest_analysis(session, org_id, mesh_hash)
        name = getattr(saved, "filename", None) if saved is not None else None
    if not isinstance(name, str) or not name:
        name = f"part{suffix}"
    if Path(name).suffix.lower() != suffix:
        name = f"{Path(name).stem or 'part'}{suffix}"
    return name


@router.post("/{mesh_hash}/recheck", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def recheck_stored_part(
    request: Request,
    response: Response,
    mesh_hash: str,
    qty: Optional[str] = Query(None, description="Comma list of quantities, e.g. 10,1000. "
                                                 "Default: the part's last cost check, else the app's ladder."),
    material_class: Optional[str] = Query(None, description="polymer|aluminum|steel|stainless|titanium. "
                                                            "Default: the part's last cost check, else polymer."),
    region: Optional[str] = Query(None, description="US|EU|MX|CN|IN|SA (unset => US, or a bound shop's region)"),
    cavities: int = Query(1, description="Formative tooling cavity count"),
    complexity: str = Query("moderate", description="simple|moderate|complex|very_complex"),
    shop: Optional[str] = Query(None, description="Per-shop calibration profile id or name (see GET /shops)."),
    overrides: Optional[str] = Query(None, description="JSON object of ad-hoc rate/driver overrides (tagged USER)."),
    owned_processes: Optional[str] = Query(None, description="Comma-separated engine process ids the org owns in-house."),
    tolerance_class: Optional[str] = Query(None, description="standard|precision|tight"),
    units: Optional[str] = Query(None, description="Declared STL source units: mm|inch (unset => mm)."),
    orientation: Optional[str] = Query(None, description="Turn the part before costing, as for POST /validate/cost."),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    _free_limit: None = Depends(limit_free_recheck),
    session: AsyncSession = Depends(get_db_session),
    _admission: None = Depends(admit_analysis),
):
    """The should-cost decision for a saved part, from the file its org kept.

    The response is ``POST /validate/cost``'s (with its ``saved`` pointer when
    decisions are persisted) plus ``recheck``: the kept file's name, size and
    format, the quantities and material it used and where they came from, and
    ``checks_used: 0``.

    A kept file beyond what a web request handles (``kept_part_jobs``: 20 MB and
    up, over the upload limit, or more memory than this process gives one
    check) isn't read here: the re-price runs on the worker, and the answer is
    202 with the job's status (``POST /api/v1/checks``'s shape); once done,
    ``GET /api/v1/checks/{id}`` holds this route's response as ``result``.
    """
    from src.api.routes import _MATERIAL_CLASSES, _REGIONS, _parse_qty_list
    from src.services import kept_part_jobs as kept
    from src.services import stored_check_service as checks

    digest = str(mesh_hash or "").lower()
    if not ctx.org_id or not _SHA256.fullmatch(digest):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    options = dict(qty=qty, material_class=material_class, region=region, cavities=cavities,
                   complexity=complexity, shop=shop, overrides=overrides, owned_processes=owned_processes,
                   tolerance_class=tolerance_class, units=units, orientation=orientation)
    info = await kept.kept_source_info(ctx.org_id, digest)
    if info is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if kept.needs_worker(info):
        # Refuse what the worker would refuse, now: a bad option is a clean 400 here.
        if material_class is not None and material_class not in _MATERIAL_CLASSES:
            raise HTTPException(status_code=400, detail=f"Unknown material_class '{material_class}'. Use one of {sorted(_MATERIAL_CLASSES)}")
        if region is not None and region not in _REGIONS:
            raise HTTPException(status_code=400, detail=f"Unknown region '{region}'. Use one of {sorted(_REGIONS)}")
        if qty is not None:
            _parse_qty_list(qty)
        job = await kept.start_and_enqueue(
            session, user_id=user.user_id, org_id=ctx.org_id, mesh_hash=digest, action=kept.RECHECK,
            filename=await _kept_name(session, ctx.org_id, digest, info.suffix), info=info, options=options,
        )
        response.status_code = 202
        response.headers["Cache-Control"] = "no-store"
        return checks.public_status(job)
    result = await recheck_kept(session, org_id=ctx.org_id, digest=digest, user=user, response=response, **options)
    response.headers["Cache-Control"] = "no-store"
    return result


async def recheck_kept(
    session: AsyncSession,
    *,
    org_id: str,
    digest: str,
    user: AuthedUser,
    response: Response,
    qty: Optional[str] = None,
    material_class: Optional[str] = None,
    region: Optional[str] = None,
    cavities: int = 1,
    complexity: str = "moderate",
    shop: Optional[str] = None,
    overrides: Optional[str] = None,
    owned_processes: Optional[str] = None,
    tolerance_class: Optional[str] = None,
    units: Optional[str] = None,
    orientation: Optional[str] = None,
) -> dict:
    """The re-price itself, from the kept bytes: this route's body, and the worker's.

    On the worker it runs under the big-check limits, so the upload-size check
    below is the worker's ceiling, not the web request's.
    """
    from src.api.routes import _max_upload_bytes, _run_cost_decision
    from src.services.cad_fix_service import DEFAULT_QUANTITIES, _saved_cost_inputs
    from src.services.source_artifact_service import read_source_artifact
    from src.storage import ObjectNotFoundError

    try:
        data, suffix = await read_source_artifact(org_id, digest)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    limit = _max_upload_bytes()
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"The stored file is {len(data) / 1048576:.1f} MB, over the {limit / 1048576:.0f} MB limit.")

    basis = {"quantities": "request", "material_class": "request"}
    if qty is None or material_class is None:
        saved_q, saved_m, saved_basis = await _saved_cost_inputs(session, org_id, digest)
        if qty is None:
            qty = ",".join(str(q) for q in (saved_q or DEFAULT_QUANTITIES))
            basis["quantities"] = saved_basis
        if material_class is None:
            material_class = saved_m or "polymer"
            basis["material_class"] = "saved_cost_check" if saved_basis == "saved_cost_check" else "default"

    name = await _kept_name(session, org_id, digest, suffix)
    upload = UploadFile(file=io.BytesIO(data), filename=name, size=len(data))
    result = await _run_cost_decision(
        file=upload, qty=qty, region=region, cavities=cavities, complexity=complexity,
        material_class=material_class, shop=shop, overrides=overrides,
        owned_processes=owned_processes, tolerance_class=tolerance_class, units=units,
        user=user, session=session, response=response, orientation=orientation,
    )
    result = dict(result)
    result["recheck"] = {
        "source": "kept", "mesh_hash": digest, "filename": name, "format": suffix.lstrip("."),
        "bytes": len(data), "qty": qty, "material_class": material_class, "basis": basis,
        "checks_used": 0,
    }
    return result


# ---------------------------------------------------------------------------
# Bodies: a file that holds several bodies, checked body by body
# ---------------------------------------------------------------------------


async def _kept_source(ctx: OrgAuthContext, mesh_hash: str) -> tuple[str, str, bytes, str]:
    """(org id, part hash, the kept bytes, their suffix), or the stored-source 404."""
    from src.api.routes import _max_upload_bytes
    from src.services.source_artifact_service import read_source_artifact
    from src.storage import ObjectNotFoundError

    digest = str(mesh_hash or "").lower()
    org_id = ctx.org_id
    if not org_id or not _SHA256.fullmatch(digest):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    try:
        data, suffix = await read_source_artifact(org_id, digest)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    limit = _max_upload_bytes()
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"The stored file is {len(data) / 1048576:.1f} MB, over the {limit / 1048576:.0f} MB limit.")
    return org_id, digest, data, suffix


async def _bodies_inputs(data: bytes, name: str, suffix: str, units: Optional[str], budget: float):
    """The kept file's analysis mesh (the same parse a check uses) and, for STEP/IGES,
    its product tree's own per-part solids when it can be read in half the budget."""
    import asyncio

    from src.api.routes import _SOURCE_UNITS, _parse_mesh_async

    if units is not None and units not in _SOURCE_UNITS:
        raise HTTPException(status_code=400, detail=f"Unknown units '{units}'. Use one of {sorted(_SOURCE_UNITS)}")
    mesh, _suffix = await _parse_mesh_async(data, name)
    if units and units != "mm":
        from src.costing.units import scale_mesh_to_mm

        mesh = scale_mesh_to_mm(mesh, units)
    model, tree_note = None, None
    if suffix in (".step", ".stp", ".iges", ".igs"):
        from src.parsers import parse_pool

        try:
            model = await asyncio.wait_for(parse_pool.submit_assembly_async(data, suffix), timeout=max(5.0, budget / 2))
        except asyncio.TimeoutError:
            parse_pool.recycle_pool(kill=True)
            tree_note = "The file's product tree wasn't read in time; bodies come from its geometry."
        except Exception:
            tree_note = "The file's product tree couldn't be read; bodies come from its geometry."
    return mesh, model, tree_note


@router.post("/{mesh_hash}/bodies", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def check_stored_bodies(
    request: Request,
    response: Response,
    mesh_hash: str,
    qty: Optional[str] = Query(None, description="Comma list of quantities per file, e.g. 1,100. "
                                                 "Default: the part's last cost check, else the app's ladder."),
    material_class: Optional[str] = Query(None, description="polymer|aluminum|steel|stainless|titanium. "
                                                            "Default: the part's last cost check; a weldment "
                                                            "left at plastic is priced in steel, labelled."),
    region: Optional[str] = Query(None, description="US|EU|MX|CN|IN|SA (unset => US)"),
    owned_processes: Optional[str] = Query(None, description="Comma-separated engine process ids the org owns."),
    units: Optional[str] = Query(None, description="Declared STL source units: mm|inch (unset => mm)."),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    _free_limit: None = Depends(limit_free_recheck),
    session: AsyncSession = Depends(get_db_session),
    _admission: None = Depends(admit_analysis),
):
    """Every body of a multi-body file checked as its own part, from the kept file.

    The response is ``body_check_service.check_bodies_sync``'s: ``part_type`` (what
    the file holds, each body with its faces in the check's 3D view, its stock
    shape, the contacts between bodies), ``designs`` (one engine check per distinct
    body shape: verdicts, the cheapest makeable route per quantity, per file),
    ``total`` (separate bodies and assemblies: the sum of the bodies) or
    ``weldment`` (members' material, joints, weld length estimate, and what isn't
    priced), plus ``source`` and ``checks_used: 0``. A one-body file answers with
    its part type and no designs.
    """
    import asyncio

    from src.api.routes import (
        _MATERIAL_CLASSES,
        _REGIONS,
        _analysis_timeout_sec,
        _parse_owned_processes,
        _parse_qty_list,
    )
    from src.services.body_check_service import check_bodies_sync
    from src.services.cad_fix_service import _saved_cost_inputs

    if material_class is not None and material_class not in _MATERIAL_CLASSES:
        raise HTTPException(status_code=400, detail=f"Unknown material_class '{material_class}'. Use one of {sorted(_MATERIAL_CLASSES)}")
    if region is not None and region not in _REGIONS:
        raise HTTPException(status_code=400, detail=f"Unknown region '{region}'. Use one of {sorted(_REGIONS)}")
    owned = _parse_owned_processes(owned_processes)
    quantities = _parse_qty_list(qty) if qty else None
    org_id, digest, data, suffix = await _kept_source(ctx, mesh_hash)
    material_is_user = material_class is not None
    basis = {"quantities": "request" if quantities else None, "material_class": "request" if material_is_user else None}
    if quantities is None or material_class is None:
        saved_q, saved_m, saved_basis = await _saved_cost_inputs(session, org_id, digest)
        if quantities is None:
            quantities, basis["quantities"] = saved_q, saved_basis
        if material_class is None:
            material_class = saved_m or "polymer"
            basis["material_class"] = "saved_cost_check" if saved_basis == "saved_cost_check" else "default"
            material_is_user = material_class != "polymer"
    name = await _kept_name(session, org_id, digest, suffix)
    budget = _analysis_timeout_sec()
    started = asyncio.get_event_loop().time()
    mesh, model, tree_note = await _bodies_inputs(data, name, suffix, units, budget)
    remaining = max(5.0, budget - (asyncio.get_event_loop().time() - started))
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, lambda: check_bodies_sync(
            mesh, filename=name, model=model, quantities=quantities, material_class=material_class,
            material_class_is_user=material_is_user, region=region or "US", owned_processes=owned,
            time_budget_sec=max(3.0, remaining - 3.0),
        )), timeout=remaining)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Checking the bodies took longer than {budget:.0f} s.")
    result["source"] = {"mesh_hash": digest, "filename": name, "format": suffix.lstrip("."), "bytes": len(data),
                        "basis": basis, "product_tree_note": tree_note}
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/{mesh_hash}/bodies/{body_id}/part", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;1000/day")
async def body_as_own_part(
    request: Request,
    response: Response,
    mesh_hash: str,
    body_id: int,
    units: Optional[str] = Query(None, description="Declared STL source units: mm|inch (unset => mm)."),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    _free_limit: None = Depends(limit_free_fixes),
    session: AsyncSession = Depends(get_db_session),
    _admission: None = Depends(admit_analysis),
):
    """One body of a multi-body file as a part of its own: an STL copy ScaleCAD made.

    Numbered as ``POST /parts/{hash}/bodies`` numbers them. The copy is recorded
    as derived from this part (``derived-from.json``, like a fix), so checking it
    uses no check. The response carries the copy's bytes (``file_b64``), its name
    and hash; the browser checks it like an upload. The original is never changed.
    """
    import asyncio
    import base64
    import hashlib
    from datetime import datetime, timezone

    from src.api.routes import _analysis_timeout_sec
    from src.services import cad_fix_service
    from src.services.body_check_service import body_stl_bytes

    org_id, digest, data, suffix = await _kept_source(ctx, mesh_hash)
    name = await _kept_name(session, org_id, digest, suffix)
    mesh, model, _note = await _bodies_inputs(data, name, suffix, units, _analysis_timeout_sec())
    try:
        stl, meta = await asyncio.to_thread(body_stl_bytes, mesh, body_id, model)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stem = Path(name).stem or "part"
    label = (meta.get("name") or f"body {meta['id']}").strip()
    filename = f"{stem} - {label}.stl" if meta.get("name") else f"{stem} - body {meta['id']}.stl"
    copy_hash = hashlib.sha256(stl).hexdigest()
    link = {
        "parent_mesh_hash": digest, "parent_format": suffix.lstrip("."), "parent_filename": name,
        "fix": "body", "params": {"body": meta["id"], "of": meta["of"], "name": meta.get("name")},
        "method": "one body of a multi-body file, as an STL in the file's own coordinates",
        "created_at": datetime.now(timezone.utc).isoformat(), "created_by_user_id": user.user_id,
    }
    await cad_fix_service._put_json(cad_fix_service._record_key(org_id, copy_hash, "derived-from.json"), link)
    response.headers["Cache-Control"] = "no-store"
    return {
        "mesh_hash": copy_hash,
        "filename": filename,
        "bytes": len(stl),
        "body": meta,
        "lineage": link,
        "checks_used": 0,
        "file_b64": base64.b64encode(stl).decode("ascii"),
    }
