"""Re-check a part from the organization's kept source: no upload, no check.

``POST /parts/{mesh_hash}/recheck`` runs the same should-cost decision as
``POST /validate/cost`` (``routes._run_cost_decision``) on the exact bytes the
organization kept when the part was checked, and saves the decision the same
way. It is how a saved part is priced in another material or at other
quantities, re-checked against the org's machines (``owned_processes``), its
service conditions (applied server-side, as for an upload) or a new
orientation, without anyone picking the file again. The kept bytes are never
returned.

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
from src.auth.free_tool_limits import limit_free_recheck
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
    """
    from src.api.routes import _max_upload_bytes, _run_cost_decision
    from src.services.cad_fix_service import DEFAULT_QUANTITIES, _saved_cost_inputs
    from src.services.source_artifact_service import read_source_artifact
    from src.storage import ObjectNotFoundError

    digest = str(mesh_hash or "").lower()
    if not ctx.org_id or not _SHA256.fullmatch(digest):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    try:
        data, suffix = await read_source_artifact(ctx.org_id, digest)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    limit = _max_upload_bytes()
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"The stored file is {len(data) / 1048576:.1f} MB, over the {limit / 1048576:.0f} MB limit.")

    basis = {"quantities": "request", "material_class": "request"}
    if qty is None or material_class is None:
        saved_q, saved_m, saved_basis = await _saved_cost_inputs(session, ctx.org_id, digest)
        if qty is None:
            qty = ",".join(str(q) for q in (saved_q or DEFAULT_QUANTITIES))
            basis["quantities"] = saved_basis
        if material_class is None:
            material_class = saved_m or "polymer"
            basis["material_class"] = "saved_cost_check" if saved_basis == "saved_cost_check" else "default"

    name = await _kept_name(session, ctx.org_id, digest, suffix)
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
    response.headers["Cache-Control"] = "no-store"
    return result
