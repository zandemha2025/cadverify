"""Mesh repair service -- weld, then two-tier repair (trimesh + pymeshfix fallback).

Weld: join vertices closer than WELD_TOL_MM, so faces that touch but were never
      joined (unsewn STEP/IGES faces, duplicated seam vertices) close exactly
      instead of being bridged by hole filling.
Tier 1: trimesh built-in repair (fast, handles normals/degenerates/simple holes).
Tier 2: pymeshfix.MeshFix (slower, handles complex non-manifold repair).

Every result says what was open (``describe_openings``) and ends in one
``outcome``: repaired, closed_changed (closed, but the volume moved more than
REPAIR_VOLUME_WARN_PCT or couldn't be measured), partly (some openings closed,
still not a solid), not_repaired, or not_needed (already a closed solid), with
a one-sentence ``summary``.

Exposed via repair_mesh() (``POST /validate/repair``, an upload) and
repair_stored() (``POST /parts/{mesh_hash}/repair``, the org's kept source).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger("cadverify.repair_service")


# ---------------------------------------------------------------------------
# Config (lazy-read pattern, same as routes.py)
# ---------------------------------------------------------------------------


def _repair_timeout_sec() -> float:
    """Read REPAIR_TIMEOUT_SEC env var, default 30.0, min 0.1."""
    try:
        return max(0.1, float(os.getenv("REPAIR_TIMEOUT_SEC", "30")))
    except ValueError:
        return 30.0


def _repair_max_faces() -> int:
    """Read REPAIR_MAX_FACES env var, default 500000, min 1."""
    try:
        return max(1, int(os.getenv("REPAIR_MAX_FACES", "500000")))
    except ValueError:
        return 500000


# ---------------------------------------------------------------------------
# Tier 1: trimesh built-in repair
# ---------------------------------------------------------------------------


def _tier1_repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Apply trimesh built-in repair operations (fast, in-place)."""
    # Remove degenerate (zero-area) faces using nondegenerate_faces mask
    mask = mesh.nondegenerate_faces()
    if not mask.all():
        mesh.update_faces(mask)
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_inversion(mesh)
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_winding(mesh)
    logger.info(
        "Tier 1 repair: watertight=%s faces=%d",
        mesh.is_watertight,
        len(mesh.faces),
    )
    return mesh


# ---------------------------------------------------------------------------
# Tier 2: pymeshfix fallback
# ---------------------------------------------------------------------------


def _tier2_repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Apply pymeshfix repair (handles complex non-manifold geometry)."""
    try:
        import pymeshfix
    except ImportError:
        logger.warning("pymeshfix not installed -- skipping Tier 2 repair")
        return mesh

    try:
        # Portable across pymeshfix 0.17 and 0.18: 0.18 removed repair(verbose=)
        # (it is quiet by default in both) and the .v/.f aliases, so pass no
        # kwargs and read .points/.faces, which exist in both releases.
        meshfix = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
        meshfix.repair()
        repaired = trimesh.Trimesh(vertices=meshfix.points, faces=meshfix.faces)
        logger.info(
            "Tier 2 pymeshfix repair: watertight=%s faces=%d",
            repaired.is_watertight,
            len(repaired.faces),
        )
        return repaired
    except (RuntimeError, Exception) as exc:
        logger.warning("pymeshfix repair failed: %s", exc)
        return mesh


# ---------------------------------------------------------------------------
# Volume-change check
# ---------------------------------------------------------------------------

# Warn when the repaired solid's volume differs from the pre-repair estimate by
# more than this many percent. Measured against _pre_repair_volume, correct hole
# fills land at 0.0% (planar holes are capped exactly) up to 0.9% (a hole across
# a curved wall, the noisiest correct fill observed), while filling the 6 mm bore
# of tests/assets/open-bored-block-mm.iges (repaired without welding first) lands
# at +10.4%. 2% keeps more than 2x margin over that noise and still flags a
# filled feature worth 2% of the part. It is a coarse guard: a smaller filled
# feature can stay under it, so a quiet result is never presented as proof that
# the design's features survived.
REPAIR_VOLUME_WARN_PCT = 2.0

# Vertices closer than this (mm, or the file's unit) are one point. STEP/IGES
# faces that touch but were never sewn tessellate with their own copies of the
# shared edge, micrometres apart; a cylinder's seam can do the same. Left apart,
# hole filling bridges across them: the open bored block's bore was filled
# (+10.4%) and an unsewn 6,000 mm3 box came back at 4,558 mm3. Welded first,
# both close to within 0.1% of the authored solid. 0.001 mm is far below any
# feature a process in this engine can make, so no real geometry merges.
WELD_TOL_MM = 1e-3
_WELD_DIGITS = 3  # trimesh merges vertices that agree to this many decimals
# An opening at least this share of the part's largest dimension is "a face is
# missing" (the open bored block's 20 mm top on a 20 mm part; an unsewn face),
# not a gap between faces.
FACE_SIZED_SHARE = 0.25
# When welding closes at least this share of the open edges, the file's faces
# touched but weren't joined (unsewn), rather than a face or gap being missing.
SEAM_SHARE = 0.8


def _pre_repair_volume(mesh: trimesh.Trimesh) -> float | None:
    """Origin-independent volume of ``mesh`` with each hole capped flat.

    ``mesh.volume`` of an open mesh depends on where the origin sits relative to
    the holes (a box missing one face reads 500 of 1000 mm3; the same open part
    rotated can read negative), so it cannot anchor a volume-change check.
    Instead every boundary loop is closed by a fan to its own centroid -- the cap
    a hole "obviously" needs, exact for planar holes -- after making the winding
    consistent on a copy. The input mesh is never mutated.
    """
    try:
        if not mesh.is_winding_consistent:
            mesh = mesh.copy()
            trimesh.repair.fix_winding(mesh)
        # Centred for conditioning only: a closed surface's volume is
        # translation-invariant.
        vertices = mesh.vertices - mesh.bounds.mean(axis=0)
        tris = vertices[mesh.faces]
        six_volume = np.einsum(
            "ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])
        ).sum()
        boundary = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
        if len(boundary):
            edges = mesh.edges[boundary]  # directed, in face winding order
            labels = trimesh.graph.connected_component_labels(
                edges, node_count=len(vertices)
            )
            _, loop = np.unique(labels[edges[:, 0]], return_inverse=True)
            starts, ends = vertices[edges[:, 0]], vertices[edges[:, 1]]
            centroids = np.stack(
                [np.bincount(loop, weights=starts[:, k]) for k in range(3)], axis=1
            ) / np.bincount(loop)[:, None]
            # Cap triangle (end, start, centroid) runs each boundary edge opposite
            # to its face, so the capped surface stays consistently wound.
            six_volume += np.einsum(
                "ij,ij->i", ends, np.cross(starts, centroids[loop])
            ).sum()
        volume = abs(float(six_volume)) / 6.0
    except Exception as exc:
        logger.warning("Pre-repair volume estimate failed: %s", exc)
        return None
    return volume if np.isfinite(volume) and volume > 0 else None


def _volume_check(
    original_mm3: float | None, repaired_mm3: float
) -> tuple[float | None, str | None]:
    """Return ``(volume_change_pct, volume_warning)`` for a repaired solid."""
    if not original_mm3:
        return None, (
            "The pre-repair volume could not be measured, so it is unknown whether "
            "repair added or removed material. Compare the repaired file with your "
            "design before using it."
        )
    change_pct = (repaired_mm3 - original_mm3) / original_mm3 * 100.0
    if abs(change_pct) <= REPAIR_VOLUME_WARN_PCT:
        return round(change_pct, 2), None
    return round(change_pct, 2), (
        f"Repair changed the part's volume by {change_pct:+.1f}% "
        f"({original_mm3:,.0f} → {repaired_mm3:,.0f} mm³), more than the "
        f"{REPAIR_VOLUME_WARN_PCT:g}% expected from closing gaps. It may have filled "
        "holes, bores, or pockets that belong to the design. Compare the repaired "
        "file with your design before using it."
    )


# ---------------------------------------------------------------------------
# What is open, and welding the seams
# ---------------------------------------------------------------------------


def _open_edge_count(mesh: trimesh.Trimesh) -> int:
    return int(len(trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)))


def _overshared_edge_count(mesh: trimesh.Trimesh) -> int:
    """Edges used by three or more faces (non-manifold)."""
    if not len(mesh.faces):
        return 0
    _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    return int((counts > 2).sum())


def _weld(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, int]:
    """Join vertices closer than WELD_TOL_MM on a copy; return (mesh, open edges closed).

    The input is never mutated. The welded copy is used only when it has fewer
    open edges and no new non-manifold edges; otherwise the input comes back
    with 0.
    """
    before = _open_edge_count(mesh)
    if before == 0:
        return mesh, 0
    try:
        welded = mesh.copy()
        welded.merge_vertices(digits_vertex=_WELD_DIGITS)
        mask = welded.nondegenerate_faces()
        if not mask.all():
            welded.update_faces(mask)
        welded.remove_unreferenced_vertices()
        after = _open_edge_count(welded)
        if after >= before or _overshared_edge_count(welded) > _overshared_edge_count(mesh):
            return mesh, 0
    except Exception as exc:  # a weld that fails is skipped, never fatal
        logger.warning("Weld before repair failed: %s", exc)
        return mesh, 0
    logger.info("Weld: open edges %d -> %d", before, after)
    return welded, before - after


def _loop_sizes(mesh: trimesh.Trimesh) -> list[float]:
    """Largest dimension (mm) of each boundary loop, largest first."""
    boundary = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    if not len(boundary):
        return []
    edges = mesh.edges_sorted[boundary]
    labels = trimesh.graph.connected_component_labels(edges, node_count=len(mesh.vertices))
    vids = np.unique(edges)
    lab = labels[vids]
    order = np.argsort(lab, kind="stable")
    lab, pts = lab[order], mesh.vertices[vids[order]]
    starts = np.flatnonzero(np.r_[True, lab[1:] != lab[:-1]])
    sizes = (np.maximum.reduceat(pts, starts) - np.minimum.reduceat(pts, starts)).max(axis=1)
    return sorted((float(s) for s in sizes), reverse=True)


def describe_openings(
    mesh: trimesh.Trimesh,
    *,
    capped_volume_mm3: float | None,
    welded_edges: int = 0,
    open_edges_as_read: int | None = None,
) -> dict:
    """Where ``mesh`` is open, in numbers a user can check against the file.

    ``mesh`` is the mesh repair starts from (after welding); ``welded_edges`` the
    open edges welding closed, ``open_edges_as_read`` the count before it, and
    ``capped_volume_mm3`` the volume with every opening capped flat. ``kind``:

    * ``none``     nothing is open;
    * ``seams``    most open edges were faces that touch but weren't joined;
    * ``surface``  capping every opening still encloses no volume: a sheet, not a solid;
    * ``face``     an opening at least FACE_SIZED_SHARE of the part: a face is missing;
    * ``gaps``     only smaller openings.
    """
    sizes = _loop_sizes(mesh)
    open_now = _open_edge_count(mesh)
    as_read = open_edges_as_read if open_edges_as_read is not None else open_now + welded_edges
    part_mm = float(np.max(mesh.extents)) if len(mesh.vertices) else 0.0
    if as_read == 0:
        kind = "none"
    elif welded_edges >= SEAM_SHARE * as_read:
        kind = "seams"
    elif capped_volume_mm3 is None:
        kind = "surface"
    elif sizes and part_mm > 0 and sizes[0] >= FACE_SIZED_SHARE * part_mm:
        kind = "face"
    else:
        kind = "gaps"
    return {
        "kind": kind,
        "open_edges": as_read,
        "welded_edges": welded_edges,
        "open_edges_after_weld": open_now,
        "loops": len(sizes),
        "largest_mm": round(sizes[0], 2) if sizes else None,
        "sizes_mm": [round(s, 2) for s in sizes[:5]],
        "part_mm": round(part_mm, 2),
    }


def _what_was_open(o: dict) -> str:
    n = o.get("loops") or 0
    if o["kind"] == "seams":
        return "the faces that touched but weren't joined"
    if o["kind"] == "face":
        rest = n - 1
        smaller = [f"{x:g} mm" for x in (o.get("sizes_mm") or [])[1:4]]
        sizes = f" ({', '.join(smaller)}{', …' if rest > len(smaller) else ''})" if smaller else ""
        extra = f" and {rest} other {'opening' if rest == 1 else 'openings'}{sizes}" if rest > 0 else ""
        return f"the missing face (an opening {o['largest_mm']:g} mm across){extra}"
    if o["kind"] == "surface":
        return "the surface's open edges"
    return f"{n} small {'gap' if n == 1 else 'gaps'}" if n else "the open edges"


def repair_outcome(applied: bool, details: dict) -> tuple[str, str]:
    """``(outcome, summary)`` for one repair: what happened, in one sentence."""
    o = details.get("openings") or {"kind": "gaps", "loops": 0, "largest_mm": None}
    what = _what_was_open(o)
    if details.get("not_needed"):
        return "not_needed", "Already a closed solid: nothing to repair."
    if applied:
        pct = details.get("volume_change_pct")
        if details.get("volume_warning") is None and pct is not None:
            return "repaired", f"Closed {what}. The volume changed {pct:+.1f}%."
        if pct is None:
            return "closed_changed", (
                f"Closed {what}, but the volume before repair couldn't be measured, "
                "so how much the shape changed is unknown.")
        return "closed_changed", (
            f"Closed {what}, but the volume changed {pct:+.1f}%: the repair may have filled "
            "a bore, hole or pocket that belongs to the design.")
    if details.get("timed_out"):
        return "not_repaired", details.get("reason") or "Repair timed out."
    after = details.get("openings_after") or {}
    before_edges = o.get("open_edges_after_weld") or o.get("open_edges") or 0
    after_edges = after.get("open_edges")
    if after.get("faces") and after_edges and 0 < after_edges < before_edges:
        loops = after.get("loops") or 0
        largest = after.get("largest_mm")
        where = f" (the largest {largest:g} mm across)" if largest else ""
        return "partly", (
            f"Partly closed: {before_edges - after_edges:,} of {before_edges:,} open edges closed, "
            f"{loops} {'opening is' if loops == 1 else 'openings are'} still open{where}. "
            "It isn't a solid yet, so nothing was made.")
    if details.get("error"):
        return "not_repaired", details.get("reason") or "Repair stopped with an internal error."
    if o["kind"] == "surface":
        return "not_repaired", (
            "This is a surface with no thickness: capping its edges encloses no volume, so there "
            "is no solid to close. Export the solid body, or thicken the surface, in your CAD tool.")
    if o["kind"] == "face":
        return "not_repaired", (
            f"A face is missing (an opening {o['largest_mm']:g} mm across) and mesh repair couldn't "
            "rebuild it into a solid.")
    if o["kind"] == "seams":
        return "not_repaired", "The faces touch but aren't joined, and mesh repair couldn't join them into a solid."
    return "not_repaired", f"Mesh repair couldn't close {what} into a solid."


# ---------------------------------------------------------------------------
# Combined repair pipeline
# ---------------------------------------------------------------------------


def _do_repair(mesh: trimesh.Trimesh) -> tuple:
    """Run two-tier repair. Returns (repaired_mesh, tier_used, holes_filled_approx).

    holes_filled is approximated by the face-count delta of whichever tier
    produced the returned mesh — the trimesh tier must report its own real
    delta, never a hardcoded 0 (a filled hole adds faces on tier 1 too).
    """
    original_faces = len(mesh.faces)

    _tier1_repair(mesh)

    if mesh.is_watertight:
        holes_filled = abs(len(mesh.faces) - original_faces)
        return (mesh, "trimesh", holes_filled)

    repaired = _tier2_repair(mesh)
    holes_filled = abs(len(repaired.faces) - original_faces)
    return (repaired, "pymeshfix", holes_filled)


# ---------------------------------------------------------------------------
# Main entry point (async)
# ---------------------------------------------------------------------------


async def repair_mesh(
    file_bytes: bytes,
    filename: str,
    processes: str | None,
    rule_pack: str | None,
    user,
    session,
    org_id: str | None = None,
) -> dict:
    """Parse mesh, enforce limits, run repair, re-analyze, return combined result.

    The repaired copy is saved as a part by its re-check; it is linked to the
    uploaded original by ``derived-from.json``, as the stored-part repair and
    the fixes do, so keeping it never uses another check (validation_caps).
    """
    result, repaired = await _repair(file_bytes, filename, processes, rule_pack, user, session, org_id)
    if repaired is not None:
        await _link_upload_repair(file_bytes, filename, repaired, result, user, session, org_id)
    return result


async def _link_upload_repair(original: bytes, filename: str, repaired: bytes, result: dict, user, session, org_id: str | None) -> None:
    """Record which checked part an uploaded file's repaired copy came from (best effort)."""
    from src.services import cad_fix_service as fx

    # The route resolves the organization once and passes it, so the link sits
    # in the same organization as the copy the re-check saved.
    if not org_id:
        return
    suffix = Path(filename or "").suffix.lower().lstrip(".") or "stl"
    details = result.get("repair_details") or {}
    link = {
        "parent_mesh_hash": hashlib.sha256(original).hexdigest(), "parent_format": suffix,
        "parent_filename": filename, "fix": "mesh_repair", "params": {},
        "method": f"mesh repair ({details.get('tier')})", "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by_user_id": user.user_id,
    }
    try:
        key = fx._record_key(org_id, hashlib.sha256(repaired).hexdigest(), "derived-from.json")
    except ValueError:
        return
    await _store_record(fx, key, link)


async def _repair(
    file_bytes: bytes,
    filename: str,
    processes: str | None,
    rule_pack: str | None,
    user,
    session,
    org_id: str | None,
) -> tuple[dict, bytes | None]:
    """The repair itself: ``(response dict, repaired STL bytes or None)``."""
    from fastapi import HTTPException

    from src.api.routes import _parse_mesh_async
    from src.services import analysis_service

    # Parse mesh (off the event loop; shares the parse cache with /validate)
    mesh, suffix = await _parse_mesh_async(file_bytes, filename)

    # Face-count guard (T-05A-01, T-05A-02)
    max_faces = _repair_max_faces()
    if len(mesh.faces) > max_faces:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Mesh has {len(mesh.faces):,} faces, exceeds REPAIR_MAX_FACES "
                f"limit of {max_faces:,}. Simplify the mesh before attempting repair."
            ),
        )

    # Run original analysis
    original_result = await analysis_service.run_analysis(
        file_bytes, filename, processes, rule_pack, user, session, org_id=org_id
    )
    # return_persisted_id is False here, so the result is the analysis dict;
    # assert the contract instead of silently misreading an AnalysisRun.
    assert isinstance(original_result, dict)

    loop = asyncio.get_event_loop()
    original_faces = len(mesh.faces)

    def _prepare(m: trimesh.Trimesh):
        as_read = _open_edge_count(m)
        welded, welded_edges = _weld(m)
        # Volume before repair, every hole capped flat (see _pre_repair_volume),
        # measured on the welded mesh so unsewn seams don't skew it: the baseline
        # that discloses a repair which filled design features instead of
        # silently substituting a different solid.
        capped = _pre_repair_volume(welded)
        openings = describe_openings(
            welded, capped_volume_mm3=capped, welded_edges=welded_edges, open_edges_as_read=as_read)
        return welded, capped, openings

    # CPU-bound, so off the event loop.
    work_mesh, original_volume_mm3, openings = await loop.run_in_executor(None, _prepare, mesh)

    def refused(details: dict) -> tuple[dict, None]:
        details = {"openings": openings, **details}
        outcome, summary = repair_outcome(False, details)
        details["reason"] = summary
        return {
            "original_analysis": original_result,
            "repair_applied": False,
            "repair_details": details,
            "repaired_analysis": None,
            "repaired_file_b64": None,
            "repair_verification": None,
            "outcome": outcome,
            "summary": summary,
        }, None

    # A closed, consistently wound, positive-volume mesh has nothing to repair:
    # say so instead of making an identical copy.
    if openings["kind"] == "none" and mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0:
        return refused({"not_needed": True})

    # Run repair with timeout (T-05A-01)
    repair_start = time.time()
    try:
        repaired_mesh, tier, holes_filled = await asyncio.wait_for(
            loop.run_in_executor(None, _do_repair, work_mesh),
            timeout=_repair_timeout_sec(),
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Repair failed: %s", exc)
        # ``reason`` is the user-facing explanation on every refusal path; a
        # timeout's str(exc) is empty, so ``error`` alone explained nothing.
        timed_out = isinstance(exc, asyncio.TimeoutError)
        reason = (
            f"Repair timed out after {_repair_timeout_sec():g} s."
            if timed_out
            else "Repair stopped with an internal error before producing a solid."
        )
        return refused({"error": str(exc) or type(exc).__name__, "reason": reason, "timed_out": timed_out})

    repair_duration_ms = round((time.time() - repair_start) * 1000, 1)

    # Refuse a file unless the repair actually produced a finite, positive-volume
    # watertight solid. The engine label alone is never proof that repair worked.
    # (pymeshfix can hand back no faces at all, e.g. for a flat surface.)
    closed = len(repaired_mesh.faces) > 0 and repaired_mesh.is_watertight
    repaired_volume = float(repaired_mesh.volume) if closed and np.isfinite(repaired_mesh.volume) else 0.0
    if not closed or repaired_volume <= 0:
        after = None
        if len(repaired_mesh.faces):
            sizes = _loop_sizes(repaired_mesh)
            after = {
                "faces": len(repaired_mesh.faces),
                "open_edges": _open_edge_count(repaired_mesh),
                "loops": len(sizes),
                "largest_mm": round(sizes[0], 2) if sizes else None,
            }
        return refused({
            "tier": tier,
            "welded_edges": openings["welded_edges"],
            "duration_ms": repair_duration_ms,
            "openings_after": after,
        })

    # Export repaired mesh to binary STL
    repaired_stl_bytes = repaired_mesh.export(file_type="stl")
    repaired_b64 = base64.b64encode(repaired_stl_bytes).decode("ascii")
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip(".-") or "part"
    repaired_name = f"{safe_stem}-repaired.stl"

    # Re-analyze repaired mesh
    repaired_result = await analysis_service.run_analysis(
        repaired_stl_bytes,
        repaired_name,
        processes,
        rule_pack,
        user,
        session,
        org_id=org_id,
    )
    assert isinstance(repaired_result, dict)

    volume_change_pct, volume_warning = _volume_check(original_volume_mm3, repaired_volume)

    repair_details = {
        "tier": tier,
        "original_faces": original_faces,
        "repaired_faces": len(repaired_mesh.faces),
        "holes_filled": holes_filled,
        "welded_edges": openings["welded_edges"],
        "duration_ms": repair_duration_ms,
        # Honest disclosure: repair changes geometry. The pre-repair volume is
        # an estimate (holes capped flat); the delta is reported, and warned on
        # past REPAIR_VOLUME_WARN_PCT, so a materially different solid is never
        # silently substituted.
        "original_volume_mm3": original_volume_mm3,
        "repaired_volume_mm3": repaired_volume,
        "volume_change_pct": volume_change_pct,
        "volume_warning": volume_warning,
        "warn_pct": REPAIR_VOLUME_WARN_PCT,
        "openings": openings,
    }
    outcome, summary = repair_outcome(True, repair_details)
    repair_details["summary"] = summary

    # Verification receipt: both verdicts came from run_analysis, the identical
    # validation pipeline used by POST /validate. Hashes bind the shown verdicts
    # and download to the exact before/after bytes; this is evidence, not a
    # cryptographic signature or approval.
    repair_verification = {
        "validation_path": "/api/v1/validate",
        "reverified": True,
        "original_verdict": original_result.get("overall_verdict", "unknown"),
        "repaired_verdict": repaired_result.get("overall_verdict", "unknown"),
        "original_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "repaired_sha256": hashlib.sha256(repaired_stl_bytes).hexdigest(),
        "download_media_type": "model/stl",
        "download_filename": repaired_name,
        "checks_used": 0,
    }
    return {
        "original_analysis": original_result,
        "repair_applied": True,
        "repair_details": repair_details,
        "repaired_analysis": repaired_result,
        "repaired_file_b64": repaired_b64,
        "repair_verification": repair_verification,
        "outcome": outcome,
        "summary": summary,
    }, repaired_stl_bytes


# ---------------------------------------------------------------------------
# Repair of the organization's kept source (no upload)
# ---------------------------------------------------------------------------

STORED_NOT_FOUND = "No stored source for this part in your organization."


async def repair_stored(
    *,
    org_id: str,
    mesh_hash: str,
    processes: str | None,
    rule_pack: str | None,
    quantities: list[int] | None,
    material_class: str | None,
    with_cost: bool,
    user,
    session,
) -> dict:
    """Mesh repair on a copy of the part's kept source CAD, re-checked in the same request.

    The same repair, limits and re-check as ``POST /validate/repair``, read from
    the org's stored source instead of an upload, so a saved part never asks for
    its file again. A repaired copy is saved as a new part (its analysis and
    source, as the upload repair's re-check already does) and linked to its
    parent by ``derived-from.json``, so ``GET /parts/{hash}/fixed-file`` serves
    it. The original is never written. No part check is reserved or used.
    """
    from fastapi import HTTPException

    from src.api.routes import _max_upload_bytes
    from src.services import cad_fix_service as fx
    from src.services.source_artifact_service import read_source_artifact
    from src.storage import ObjectNotFoundError

    try:
        data, suffix = await read_source_artifact(org_id, mesh_hash)
    except (ObjectNotFoundError, FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail=STORED_NOT_FOUND)
    limit = _max_upload_bytes()
    if len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"The stored file is {len(data) / 1048576:.1f} MB, over the {limit / 1048576:.0f} MB limit.")

    saved = await fx.latest_analysis(session, org_id, mesh_hash)
    original_name = (saved.filename if saved is not None else None) or f"part{suffix}"
    if Path(original_name).suffix.lower() != suffix:
        original_name = f"{Path(original_name).stem or 'part'}{suffix}"

    result, repaired = await _repair(data, original_name, processes, rule_pack, user, session, org_id)
    result["source"] = {"mesh_hash": mesh_hash, "filename": original_name, "format": suffix.lstrip("."), "bytes": len(data)}
    result.update({"repaired": None, "download": None, "lineage": None, "prices": None})
    now = datetime.now(timezone.utc).isoformat()
    attempt = {"fix": "mesh_repair", "at": now, "applied": repaired is not None,
               "outcome": result["outcome"], "summary": result["summary"]}

    if repaired is None:
        await _store_record(fx, fx._record_key(org_id, mesh_hash, "fixes/mesh_repair.json"), attempt)
        return result

    fixed_hash = hashlib.sha256(repaired).hexdigest()
    fixed_name = fx._fixed_filename(original_name, "mesh_repair", ".stl")
    details = result["repair_details"]
    link = {
        "parent_mesh_hash": mesh_hash, "parent_format": suffix.lstrip("."),
        "parent_filename": original_name, "fix": "mesh_repair", "params": {},
        "method": f"mesh repair ({details.get('tier')})", "created_at": now,
        "created_by_user_id": user.user_id,
    }
    await _store_record(fx, fx._record_key(org_id, fixed_hash, "derived-from.json"), link)
    await _store_record(fx, fx._record_key(org_id, mesh_hash, "fixes/mesh_repair.json"),
                        {**attempt, "fixed_mesh_hash": fixed_hash})

    from src.services.audit_service import emit_event

    try:
        await emit_event(
            session, actor_id=user.user_id, action="part.repair_applied", resource_type="part",
            resource_id=fixed_hash, file_hash=fixed_hash, result_summary=result["outcome"],
            detail={"parent_mesh_hash": mesh_hash, "fix": "mesh_repair", "volume_change_pct": details.get("volume_change_pct")},
            org_id=org_id,
        )
    except Exception:
        logger.warning("audit event for stored repair failed", exc_info=True)

    if with_cost:
        basis = "request"
        if quantities is None or material_class is None:
            saved_q, saved_m, saved_basis = await fx._saved_cost_inputs(session, org_id, mesh_hash)
            if quantities is None:
                quantities, basis = saved_q, saved_basis
            material_class = material_class or saved_m
        report = await fx._price(repaired, fixed_name, quantities, material_class)
        result["prices"] = {
            "quantities": quantities, "material_class": material_class, "basis": basis,
            # The open original isn't priced: nothing is priced from a shape that isn't closed.
            "before": None, "after": fx._cheapest(report),
            "note": "Model prices for the repaired copy, not quotes. Cheapest method the check doesn't block, per quantity.",
        }

    result["repaired"] = {**fx._side(result["repaired_analysis"], repaired, ".stl", fixed_hash), "filename": fixed_name}
    result["lineage"] = link
    result["download"] = {
        "url": f"/api/v1/parts/{fixed_hash}/fixed-file", "filename": fixed_name,
        "media_type": "model/stl", "bytes": len(repaired),
    }
    result["repair_verification"]["download_filename"] = fixed_name
    if len(repaired) > fx.inline_max_bytes():
        result["repaired_file_b64"] = None  # served by the download URL instead
    return result


async def _store_record(fx, key: str, payload: dict) -> None:
    try:
        await fx._put_json(key, payload)
    except Exception:
        logger.warning("could not store repair record %s", key, exc_info=True)
