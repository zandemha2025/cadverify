"""Org-scoped fixes ScaleCAD applies itself to a stored part's source CAD.

* ``GET  /parts/{mesh_hash}/fixes`` lists, per finding of the part's latest
  saved check, whether ScaleCAD can fix it itself, with which fix and which
  parameters. Metadata only: no CAD work, no bytes, never a check.
* ``POST /parts/{mesh_hash}/fixes/{fix_id}`` makes that fix on a copy of the
  stored source in an isolated CAD worker, re-checks the copy in the same
  request, and returns before/after evidence plus the fixed file. The original
  is never changed; the copy is a new part linked to its parent.
* ``POST /parts/{mesh_hash}/repair`` is mesh repair (``POST /validate/repair``)
  on a copy of the stored source, so a saved part never asks for its file again;
  the repaired copy is a new part linked to its parent, like a fix.
* ``GET  /parts/{mesh_hash}/fixed-file`` downloads a fixed copy. Only copies
  ScaleCAD made are downloadable here; original sources stay non-downloadable,
  as in ``part_preview``.

Boundaries match ``part_preview``: the caller's active org only; another org's
hash, a malformed hash and a missing artifact are the same 404. Making a fix
needs an org member (it adds a part) and is on every plan, the free trial
included, like mesh repair (``POST /validate/repair``); like repair it never
reserves or consumes a part check (no validation-cap or org-limit dependency).
Free accounts get a per-user ceiling on fixes (``src.auth.free_tool_limits``).
"""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admission import admit_analysis
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, Role, require_org_role, require_role
from src.auth.require_api_key import AuthedUser
from src.auth.free_tool_limits import limit_free_fixes, limit_free_repair
from src.db.engine import get_db_session
from src.services import cad_fix_service as svc

router = APIRouter(tags=["parts"])

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NOT_FOUND = "No stored source for this part in your organization."


def _scope(ctx: OrgAuthContext, mesh_hash: str) -> tuple[str, str]:
    digest = str(mesh_hash or "").lower()
    if not ctx.org_id or not _SHA256.fullmatch(digest):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ctx.org_id, digest


def _quantities(raw: Optional[str]) -> Optional[list[int]]:
    if raw is None or not raw.strip():
        return None
    from src.api.routes import _parse_qty_list

    return _parse_qty_list(raw)


@router.get("/{mesh_hash}/fixes")
@limiter.limit("600/hour;5000/day")
async def part_fix_options(
    request: Request,
    response: Response,
    mesh_hash: str,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Per finding: whether ScaleCAD can fix it itself, and with which fix."""
    from src.services.source_artifact_service import find_source_artifact_suffix

    org_id, digest = _scope(ctx, mesh_hash)
    suffix = await find_source_artifact_suffix(org_id, digest)
    if suffix is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    saved = await svc.latest_analysis(session, org_id, digest)
    options = svc.fix_options(
        saved.result_json if saved is not None else None,
        suffix,
        await svc.read_attempts(org_id, digest),
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "mesh_hash": digest,
        "format": suffix.lstrip("."),
        "analysis": None if saved is None else {
            "id": saved.ulid,
            "analysis_version": saved.analysis_version,
            "created_at": saved.created_at.isoformat() if saved.created_at else None,
        },
        "derived_from": await svc.read_lineage(org_id, digest),
        **options,
    }


@router.post("/{mesh_hash}/fixes/{fix_id}", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("30/hour;200/day")
async def apply_part_fix(
    request: Request,
    response: Response,
    mesh_hash: str,
    fix_id: str,
    value: Optional[float] = Query(
        None,
        description="The fix's parameter: radius_mm, diameter_mm or angle_deg. "
                    "Leave empty for what the part's findings ask for.",
    ),
    processes: Optional[str] = Query(None, description="Comma-separated processes for the re-check."),
    rule_pack: Optional[str] = Query(None, description="Industry rule pack for the re-check."),
    qty: Optional[str] = Query(None, description="Quantities to price, e.g. 10,1000. "
                                                 "Default: the part's last cost check, else the app's ladder."),
    material_class: Optional[str] = Query(None, description="polymer|aluminum|steel|stainless|titanium"),
    with_cost: bool = Query(True, description="Price both files (adds one engine pass each)."),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    _free_limit: None = Depends(limit_free_fixes),
    session: AsyncSession = Depends(get_db_session),
    _admission: None = Depends(admit_analysis),
):
    """Make one fix on a copy of the stored source and re-check the copy."""
    from src.api.routes import _MATERIAL_CLASSES
    from src.analysis.rules import available_rule_packs, get_rule_pack

    org_id, digest = _scope(ctx, mesh_hash)
    if rule_pack and get_rule_pack(rule_pack) is None:
        raise HTTPException(status_code=400, detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}")
    if material_class is not None and material_class not in _MATERIAL_CLASSES:
        raise HTTPException(status_code=400, detail=f"Unknown material_class '{material_class}'. Use one of {sorted(_MATERIAL_CLASSES)}")
    try:
        result = await svc.apply_fix(
            org_id=org_id, mesh_hash=digest, fix_id=fix_id, value=value,
            processes=processes, rule_pack=rule_pack, quantities=_quantities(qty),
            material_class=material_class, with_cost=with_cost, user=user, session=session,
        )
    except svc.FixRequestError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/{mesh_hash}/repair", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def repair_stored_part(
    request: Request,
    response: Response,
    mesh_hash: str,
    processes: Optional[str] = Query(None, description="Comma-separated processes for the re-check."),
    rule_pack: Optional[str] = Query(None, description="Industry rule pack for the re-check."),
    qty: Optional[str] = Query(None, description="Quantities to price the repaired copy at, e.g. 10,1000. "
                                                 "Default: the part's last cost check, else the app's ladder."),
    material_class: Optional[str] = Query(None, description="polymer|aluminum|steel|stainless|titanium"),
    with_cost: bool = Query(True, description="Price the repaired copy (adds one engine pass)."),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.member)),
    user: AuthedUser = Depends(require_role(Role.analyst)),
    _free_limit: None = Depends(limit_free_repair),
    session: AsyncSession = Depends(get_db_session),
    _admission: None = Depends(admit_analysis),
):
    """Mesh repair on a copy of the stored source: no upload, no check used.

    The same repair, limits and re-check as ``POST /validate/repair``. A
    repaired copy becomes a new part linked to this one and is downloadable from
    ``GET /parts/{repaired}/fixed-file``. The response is the upload repair's
    plus ``outcome`` (repaired | closed_changed | partly | not_repaired | not_needed),
    ``summary``, ``source``, ``repaired``, ``download``, ``lineage`` and
    ``prices`` (the repaired copy only: the open original isn't priced).

    A kept file beyond what a web request handles (``kept_part_jobs``: 20 MB and
    up, over the upload limit, or more memory than this process gives one
    check) isn't read here: the repair runs on the worker, and the answer is
    202 with the job's status (``POST /api/v1/checks``'s shape); once done,
    ``GET /api/v1/checks/{id}`` holds this route's response as ``result``.
    """
    from src.api.routes import _MATERIAL_CLASSES
    from src.analysis.rules import available_rule_packs, get_rule_pack
    from src.services import kept_part_jobs as kept
    from src.services import repair_service
    from src.services import stored_check_service as checks

    org_id, digest = _scope(ctx, mesh_hash)
    if rule_pack and get_rule_pack(rule_pack) is None:
        raise HTTPException(status_code=400, detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}")
    if material_class is not None and material_class not in _MATERIAL_CLASSES:
        raise HTTPException(status_code=400, detail=f"Unknown material_class '{material_class}'. Use one of {sorted(_MATERIAL_CLASSES)}")
    info = await kept.kept_source_info(org_id, digest)
    if info is not None and kept.needs_worker(info):
        saved = await svc.latest_analysis(session, org_id, digest)
        name = (saved.filename if saved is not None else None) or f"part{info.suffix}"
        job = await kept.start_and_enqueue(
            session, user_id=user.user_id, org_id=org_id, mesh_hash=digest, action=kept.REPAIR, filename=name,
            info=info, options={"processes": processes, "rule_pack": rule_pack, "quantities": _quantities(qty),
                                "material_class": material_class, "with_cost": with_cost},
        )
        response.status_code = 202
        response.headers["Cache-Control"] = "no-store"
        return checks.public_status(job)
    result = await repair_service.repair_stored(
        org_id=org_id, mesh_hash=digest, processes=processes, rule_pack=rule_pack,
        quantities=_quantities(qty), material_class=material_class, with_cost=with_cost,
        user=user, session=session,
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/{mesh_hash}/fixed-file")
@limiter.limit("120/hour;1000/day")
async def download_fixed_file(
    request: Request,
    mesh_hash: str,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
):
    """The bytes of a copy ScaleCAD fixed. Original sources are not served here."""
    org_id, digest = _scope(ctx, mesh_hash)
    found = await svc.read_fixed_file(org_id, digest)
    if found is None:
        raise HTTPException(status_code=404, detail="No fixed copy with this hash in your organization.")
    data, suffix, link = found
    name = svc._fixed_filename(link.get("parent_filename") or f"part{suffix}", link.get("fix") or "", suffix)
    return Response(
        content=data,
        media_type=svc.MEDIA_TYPES.get(suffix, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "X-Content-SHA256": digest,
        },
    )
