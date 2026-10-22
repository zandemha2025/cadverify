"""Org-scoped 3D view of a part's stored source CAD.

Successful analyses and should-cost runs already keep the exact uploaded CAD in
the tenant's object store (``source_artifact_service``). These routes let the
same organization see that part again in 3D without re-uploading it:

* ``GET /parts/{mesh_hash}/preview.glb`` tessellates the stored source with the
  same parse + analysis-face-space export as ``POST /validate/preview-mesh``, so
  face highlights line up with the saved analysis (``X-Mesh-Face-Hash``).
* ``GET /parts/{mesh_hash}/source-status`` says whether a source is kept, from
  object metadata only.

Boundaries: an org membership (viewer and up) in the caller's active org is
required; another org's hash, a malformed hash and a missing artifact are all the
same 404, so existence never leaks across tenants. There is no public or share
access. Neither route returns the raw CAD bytes, and neither counts as a check
(no validation-cap or org-limit dependency). Nothing new is written: the GLB is
held only in a small in-process cache keyed by org, hash and units, and a cache
hit is served only while the stored source still exists (a deleted part is the
same 404 everywhere, whichever process deleted it).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from src.api.admission import admit_analysis
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.rbac import OrgAuthContext, OrgRole, require_org_role
from src.costing.units import mesh_source_units, scale_mesh_to_mm
from src.services.source_artifact_service import (
    find_source_artifact_suffix,
    read_source_artifact,
    read_preview_glb,
)
from src.storage import ObjectNotFoundError

logger = logging.getLogger("cadverify.part_preview")

router = APIRouter(tags=["parts"])

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NOT_FOUND = "No stored source for this part in your organization."

# (org_id, mesh_hash, units) -> (glb, headers); bounded by total bytes.
_cache: "OrderedDict[tuple[str, str, str], tuple[bytes, dict[str, str]]]" = OrderedDict()


def _cache_budget_bytes() -> int:
    try:
        return max(0, int(os.getenv("STORED_PREVIEW_CACHE_MB", "64"))) * 1024 * 1024
    except ValueError:
        return 64 * 1024 * 1024


def _cache_get(key: tuple[str, str, str]) -> tuple[bytes, dict[str, str]] | None:
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
    return hit


def _cache_put(key: tuple[str, str, str], glb: bytes, headers: dict[str, str]) -> None:
    budget = _cache_budget_bytes()
    if len(glb) > budget:
        return
    _cache[key] = (glb, headers)
    _cache.move_to_end(key)
    while sum(len(v[0]) for v in _cache.values()) > budget:
        _cache.popitem(last=False)


def _scope(ctx: OrgAuthContext, mesh_hash: str) -> tuple[str, str]:
    """The caller's org and a valid digest, or the uniform 404."""
    digest = str(mesh_hash or "").lower()
    if not ctx.org_id or not _SHA256.fullmatch(digest):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return ctx.org_id, digest


@router.get("/{mesh_hash}/source-status")
@limiter.limit("600/hour;5000/day")
async def stored_source_status(
    request: Request,
    response: Response,
    mesh_hash: str,
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
):
    """Whether this org keeps the part's source CAD. Metadata only, never bytes."""
    org_id, digest = _scope(ctx, mesh_hash)
    suffix = await find_source_artifact_suffix(org_id, digest)
    if suffix is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    response.headers["Cache-Control"] = "no-store"
    return {"mesh_hash": digest, "kept": True, "format": suffix.lstrip(".")}


@router.get("/{mesh_hash}/preview.glb", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("120/hour;1000/day")
async def stored_preview_glb(
    request: Request,
    mesh_hash: str,
    units: str = Query("mm", pattern="^(mm|inch)$"),
    ctx: OrgAuthContext = Depends(require_org_role(OrgRole.viewer)),
    _admission: None = Depends(admit_analysis),
):
    """A browser GLB of the stored source, in the analysis face space."""
    org_id, digest = _scope(ctx, mesh_hash)
    key = (org_id, digest, units)
    hit = _cache_get(key)
    # A part deleted through another API process leaves this process's copy
    # behind: a hit still needs the stored source (metadata only, no bytes).
    if hit is not None and await find_source_artifact_suffix(org_id, digest) is None:
        _cache.pop(key, None)
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if hit is None:
        # A big part's preview was built on the worker when it was checked.
        kept = await read_preview_glb(org_id, digest, source_units=units)
        if kept is not None and await find_source_artifact_suffix(org_id, digest) is not None:
            _cache_put(key, kept[0], kept[1])
            hit = kept
    if hit is None:
        try:
            data, suffix = await read_source_artifact(org_id, digest)
        except (ObjectNotFoundError, FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail=_NOT_FOUND)

        # Same parse + export as POST /validate/preview-mesh?purpose=analysis.
        from src.api.routes import _build_preview_glb, _parse_mesh_async

        filename = f"source{suffix}"
        mesh, parsed_suffix = await _parse_mesh_async(data, filename)
        mesh = scale_mesh_to_mm(mesh, mesh_source_units(filename, units))
        try:
            glb, original_faces, preview_faces, decimated, face_hash = await asyncio.to_thread(
                _build_preview_glb, mesh, filename, for_analysis=True
            )
        except HTTPException:
            raise
        except Exception:
            logger.exception("Stored preview export failed for org=%s hash=%s", org_id, digest[:12])
            raise HTTPException(status_code=500, detail="The 3D view couldn't be built from the stored file.")
        headers = {
            "X-Mesh-Original-Faces": str(original_faces),
            "X-Mesh-Preview-Faces": str(preview_faces),
            "X-Mesh-Decimated": "true" if decimated else "false",
            "X-Mesh-Source": parsed_suffix.lstrip("."),
            "X-Mesh-Face-Space": "analysis",
            "X-Mesh-Face-Hash": face_hash,
        }
        _cache_put(key, glb, headers)
        hit = (glb, headers)
    glb, headers = hit
    return Response(
        content=glb,
        media_type="model/gltf-binary",
        headers={**headers, "Cache-Control": "private, no-store"},
    )
