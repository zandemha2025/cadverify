"""Ways to lay a stored part down, compared by the check's own rules.

``GET /parts/{mesh_hash}/orientations`` reads the organization's kept source
(the exact uploaded file, as ``part_preview`` does), lays it on each of the six
sides of its box and on its largest flat faces that aren't on a file axis, and
for each says what the check's own rules mark: the faces and area needing
support per printing process (``check_overhangs``), the wall area without
draft per molding process (``check_draft_angles``, the tool opening along the
placed +Z), the height and the footprint. ``best`` names the choice per
process (least support, then lowest; least wall without draft). ``down=x,y,z``
adds a face picked in the 3D view.

It compares; it doesn't re-check. A full re-check in a chosen orientation is
``POST /validate`` and ``POST /validate/cost`` with ``orientation``, which
re-measure everything (undercuts too) and price it; the same file uses no
extra check. This route never counts as a check either: no validation-cap or
org-limit dependency, no bytes returned, nothing written. Boundaries match
``part_preview``: the caller's active org only; another org's hash, a
malformed hash and a missing source are the same 404.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from src.api.admission import admit_analysis
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role
from src.costing.units import mesh_source_units, scale_mesh_to_mm
from src.services.source_artifact_service import find_source_artifact_suffix, read_source_artifact
from src.storage import ObjectNotFoundError

logger = logging.getLogger("cadverify.part_orientation")

router = APIRouter(tags=["parts"])

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NOT_FOUND = "No stored source for this part in your organization."
_CACHE_ENTRIES = 32
_cache: "OrderedDict[tuple, dict]" = OrderedDict()


def _scope(ctx: OrgAuthContext, mesh_hash: str) -> tuple[str, str]:
    digest = str(mesh_hash or "").lower()
    if not ctx.org_id or not _SHA256.fullmatch(digest):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ctx.org_id, digest


def _down(raw: Optional[str]) -> Optional[list[float]]:
    if raw is None or not raw.strip():
        return None
    try:
        nums = [float(p) for p in raw.split(",")]
    except ValueError:
        nums = []
    if len(nums) != 3 or not all(abs(n) < 1e6 for n in nums) or not any(nums):
        raise HTTPException(status_code=400, detail="down is a direction in the file's coordinates: x,y,z.")
    return nums


@router.get("/{mesh_hash}/orientations", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("240/hour;2000/day")
async def part_orientations(
    request: Request,
    response: Response,
    mesh_hash: str,
    units: str = Query("mm", pattern="^(mm|inch)$"),
    down: Optional[str] = Query(None, description="Also lay this file direction on the plate: x,y,z."),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    _admission: None = Depends(admit_analysis),
):
    """Compare ways to lay this part down. Never a check; nothing is saved."""
    from src.analysis.orientation import OrientationError, orientation_options

    org_id, digest = _scope(ctx, mesh_hash)
    picked = _down(down)
    key = (org_id, digest, units, tuple(picked) if picked else None)
    hit = _cache.get(key)
    # Served from cache only while the stored source exists (a deleted part is a 404).
    if hit is not None and await find_source_artifact_suffix(org_id, digest) is None:
        _cache.pop(key, None)
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if hit is None:
        try:
            data, suffix = await read_source_artifact(org_id, digest)
        except (ObjectNotFoundError, FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        from src.api.routes import _analysis_timeout_sec, _parse_mesh_async

        filename = f"source{suffix}"
        mesh, _ = await _parse_mesh_async(data, filename)
        mesh = scale_mesh_to_mm(mesh, mesh_source_units(filename, units))
        try:
            options = await asyncio.wait_for(
                asyncio.to_thread(orientation_options, mesh, down=picked),
                timeout=_analysis_timeout_sec(),
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Comparing orientations took too long for this part.")
        except OrientationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        hit = {"mesh_hash": digest, "units": units, **options}
        _cache[key] = hit
        while len(_cache) > _CACHE_ENTRIES:
            _cache.popitem(last=False)
    else:
        _cache.move_to_end(key)
    response.headers["Cache-Control"] = "no-store"
    return hit
