"""Mesh repair service -- two-tier repair (trimesh + pymeshfix fallback).

Tier 1: trimesh built-in repair (fast, handles normals/degenerates/simple holes).
Tier 2: pymeshfix.MeshFix (slower, handles complex non-manifold repair).

Exposed via repair_mesh() which is called by the /validate/repair endpoint.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import time
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
# of tests/assets/open-bored-block-mm.iges lands at +10.4%. 2% keeps more than 2x
# margin over that noise and still flags a filled feature worth 2% of the part.
# It is a coarse guard: a smaller filled feature can stay under it, so a quiet
# result is never presented as proof that the design's features survived.
REPAIR_VOLUME_WARN_PCT = 2.0


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
) -> dict:
    """Parse mesh, enforce limits, run repair, re-analyze, return combined result."""
    from fastapi import HTTPException

    from src.api.routes import _parse_mesh
    from src.services import analysis_service

    # Parse mesh
    mesh, suffix = _parse_mesh(file_bytes, filename)

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
        file_bytes, filename, processes, rule_pack, user, session
    )
    # return_persisted_id is False here, so the result is the analysis dict;
    # assert the contract instead of silently misreading an AnalysisRun.
    assert isinstance(original_result, dict)

    loop = asyncio.get_event_loop()
    original_faces = len(mesh.faces)
    # Volume before repair, every hole capped flat (see _pre_repair_volume): the
    # baseline that discloses a repair which filled design features instead of
    # silently substituting a different solid. CPU-bound, so off the event loop.
    original_volume_mm3 = await loop.run_in_executor(None, _pre_repair_volume, mesh)

    # Run repair with timeout (T-05A-01)
    repair_start = time.time()
    try:
        repaired_mesh, tier, holes_filled = await asyncio.wait_for(
            loop.run_in_executor(None, _do_repair, mesh),
            timeout=_repair_timeout_sec(),
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Repair failed: %s", exc)
        # ``reason`` is the user-facing explanation on every refusal path; a
        # timeout's str(exc) is empty, so ``error`` alone explained nothing.
        reason = (
            f"Repair timed out after {_repair_timeout_sec():g} s."
            if isinstance(exc, asyncio.TimeoutError)
            else "Repair stopped with an internal error before producing a solid."
        )
        return {
            "original_analysis": original_result,
            "repair_applied": False,
            "repair_details": {"error": str(exc), "reason": reason},
            "repaired_analysis": None,
            "repaired_file_b64": None,
            "repair_verification": None,
        }

    repair_duration_ms = round((time.time() - repair_start) * 1000, 1)

    # Refuse a file unless the repair actually produced a finite, positive-volume
    # watertight solid. The engine label alone is never proof that repair worked.
    repaired_volume = float(repaired_mesh.volume) if np.isfinite(repaired_mesh.volume) else 0.0
    if not repaired_mesh.is_watertight or repaired_volume <= 0:
        return {
            "original_analysis": original_result,
            "repair_applied": False,
            "repair_details": {
                "tier": tier,
                "reason": "Repair did not produce a watertight positive-volume solid.",
                "duration_ms": repair_duration_ms,
            },
            "repaired_analysis": None,
            "repaired_file_b64": None,
            "repair_verification": None,
        }

    # Export repaired mesh to binary STL
    repaired_stl_bytes = repaired_mesh.export(file_type="stl")
    repaired_b64 = base64.b64encode(repaired_stl_bytes).decode("ascii")

    # Re-analyze repaired mesh
    repaired_result = await analysis_service.run_analysis(
        repaired_stl_bytes,
        f"{filename}-repaired.stl",
        processes,
        rule_pack,
        user,
        session,
    )
    assert isinstance(repaired_result, dict)

    volume_change_pct, volume_warning = _volume_check(original_volume_mm3, repaired_volume)

    repair_details = {
        "tier": tier,
        "original_faces": original_faces,
        "repaired_faces": len(repaired_mesh.faces),
        "holes_filled": holes_filled,
        "duration_ms": repair_duration_ms,
        # Honest disclosure: repair changes geometry. The pre-repair volume is
        # an estimate (holes capped flat); the delta is reported, and warned on
        # past REPAIR_VOLUME_WARN_PCT, so a materially different solid is never
        # silently substituted.
        "original_volume_mm3": original_volume_mm3,
        "repaired_volume_mm3": repaired_volume,
        "volume_change_pct": volume_change_pct,
        "volume_warning": volume_warning,
    }

    # Verification receipt: both verdicts came from run_analysis, the identical
    # validation pipeline used by POST /validate. Hashes bind the shown verdicts
    # and download to the exact before/after bytes; this is evidence, not a
    # cryptographic signature or approval.
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).stem).strip(".-") or "part"
    repair_verification = {
        "validation_path": "/api/v1/validate",
        "reverified": True,
        "original_verdict": original_result.get("overall_verdict", "unknown"),
        "repaired_verdict": repaired_result.get("overall_verdict", "unknown"),
        "original_sha256": hashlib.sha256(file_bytes).hexdigest(),
        "repaired_sha256": hashlib.sha256(repaired_stl_bytes).hexdigest(),
        "download_media_type": "model/stl",
        "download_filename": f"{safe_stem}-repaired.stl",
    }
    return {
        "original_analysis": original_result,
        "repair_applied": True,
        "repair_details": repair_details,
        "repaired_analysis": repaired_result,
        "repaired_file_b64": repaired_b64,
        "repair_verification": repair_verification,
    }
