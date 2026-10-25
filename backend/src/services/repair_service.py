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
        meshfix = pymeshfix.MeshFix(mesh.vertices, mesh.faces)
        meshfix.repair(verbose=False)
        repaired = trimesh.Trimesh(vertices=meshfix.v, faces=meshfix.f)
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

    # Run repair with timeout (T-05A-01)
    repair_start = time.time()
    original_faces = len(mesh.faces)
    # Volume before repair: unreliable for a non-watertight mesh (that is why
    # repair is needed) but recorded so the post-repair delta is disclosed,
    # not silent — hole filling can materially change enclosed volume.
    try:
        original_volume_mm3 = float(mesh.volume)
    except Exception:
        original_volume_mm3 = None
    loop = asyncio.get_event_loop()
    try:
        repaired_mesh, tier, holes_filled = await asyncio.wait_for(
            loop.run_in_executor(None, _do_repair, mesh),
            timeout=_repair_timeout_sec(),
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("Repair failed: %s", exc)
        return {
            "original_analysis": original_result,
            "repair_applied": False,
            "repair_details": {"error": str(exc)},
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

    try:
        repaired_volume_mm3 = float(repaired_mesh.volume)
    except Exception:
        repaired_volume_mm3 = None
    volume_change_pct = None
    if original_volume_mm3 and repaired_volume_mm3:
        volume_change_pct = round(
            (repaired_volume_mm3 - original_volume_mm3)
            / abs(original_volume_mm3) * 100.0,
            2,
        )

    repair_details = {
        "tier": tier,
        "original_faces": original_faces,
        "repaired_faces": len(repaired_mesh.faces),
        "holes_filled": holes_filled,
        "duration_ms": repair_duration_ms,
        # Honest disclosure: repair changes geometry. The pre-repair volume of
        # a non-watertight mesh is itself an estimate; the delta is reported
        # so a materially different solid is never silently substituted.
        "original_volume_mm3": original_volume_mm3,
        "repaired_volume_mm3": repaired_volume_mm3,
        "volume_change_pct": volume_change_pct,
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
