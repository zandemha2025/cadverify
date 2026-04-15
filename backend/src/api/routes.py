"""API route handlers for CADVerify."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.additive_analyzer import ADDITIVE_PROCESSES, run_additive_checks
from src.analysis.casting_analyzer import CASTING_PROCESSES, run_casting_checks
from src.analysis.cnc_analyzer import CNC_PROCESSES, run_cnc_checks
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.models import AnalysisResult, Issue, ProcessType, Severity
from src.analysis.processes import get_analyzer
from src.analysis.rules import available_rule_packs, get_rule_pack
from src.analysis.molding_analyzer import MOLDING_PROCESSES, run_molding_checks
from src.analysis.sheet_metal_analyzer import run_sheet_metal_checks
from src.api.upload_validation import enforce_triangle_cap, validate_magic
from src.fixes.fix_suggester import enhance_suggestions, get_priority_fixes
from src.matcher.profile_matcher import rank_processes, score_process
from src.parsers.step_parser import is_step_supported, parse_step_from_bytes
from src.parsers.stl_parser import parse_stl_from_bytes
from src.profiles.database import MACHINES, MATERIALS, get_all_processes

logger = logging.getLogger("cadverify.routes")

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# Process → analyzer function map (legacy, pre-registry adapter)
# ──────────────────────────────────────────────────────────────
PROCESS_ANALYZERS: dict[ProcessType, callable] = {}
for _p in ADDITIVE_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_additive_checks
for _p in CNC_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_cnc_checks
for _p in MOLDING_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_molding_checks
PROCESS_ANALYZERS[ProcessType.SHEET_METAL] = run_sheet_metal_checks
for _p in CASTING_PROCESSES:
    PROCESS_ANALYZERS[_p] = run_casting_checks


# ──────────────────────────────────────────────────────────────
# Upload handling
# ──────────────────────────────────────────────────────────────
_CHUNK = 1024 * 1024  # 1 MiB


def _max_upload_bytes() -> int:
    """Read limit lazily so tests can override via monkeypatch."""
    try:
        mb = int(os.getenv("MAX_UPLOAD_MB", "100"))
    except ValueError:
        mb = 100
    return max(1, mb) * 1024 * 1024


async def _read_capped(file: UploadFile) -> bytes:
    """Stream-read the upload, rejecting anything over MAX_UPLOAD_MB."""
    limit = _max_upload_bytes()
    buf = bytearray()
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {limit // (1024 * 1024)}MB limit",
            )
    if not buf:
        raise HTTPException(status_code=400, detail="Empty file uploaded")
    return bytes(buf)


def _parse_mesh(data: bytes, filename: str):
    suffix = Path(filename).suffix.lower()
    if suffix not in (".stl", ".step", ".stp"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Use .stl, .step, or .stp",
        )
    # CORE-07: defense-in-depth — verify magic bytes before dispatching
    # to parser libs (cadquery/trimesh can crash on adversarial input).
    validate_magic(data, suffix)
    try:
        if suffix == ".stl":
            mesh = parse_stl_from_bytes(data, filename)
            enforce_triangle_cap(mesh)
            return mesh, suffix
        if not is_step_supported():
            raise HTTPException(
                status_code=501,
                detail="STEP parsing requires cadquery. Install with: pip install cadquery",
            )
        mesh = parse_step_from_bytes(data, filename)
        enforce_triangle_cap(mesh)
        return mesh, suffix
    except HTTPException:
        raise
    except ValueError as e:
        # Parser-provided message is safe to expose.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Mesh parsing failed for %s", filename)
        raise HTTPException(status_code=400, detail="Failed to parse mesh file")


def _resolve_target_processes(processes: Optional[str]) -> list[ProcessType]:
    if not processes:
        return list(ProcessType)
    out: list[ProcessType] = []
    for token in processes.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(ProcessType(token))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown process: {token}")
    return out


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────
@router.post("/validate")
async def validate_file(
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types to check. Leave empty for all.",
    ),
    rule_pack: Optional[str] = Query(
        None,
        description="Industry rule pack: aerospace, automotive, oil_gas, medical.",
    ),
):
    """Upload a STEP or STL file and get manufacturing validation results."""
    start = time.time()
    filename = file.filename or "unknown"

    # Resolve rule pack (if specified)
    pack = None
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        if pack is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    data = await _read_capped(file)
    mesh, suffix = _parse_mesh(data, filename)

    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    features = detect_features(mesh)
    ctx.features = features
    universal_issues = run_universal_checks(mesh)

    target_processes = _resolve_target_processes(processes)

    process_scores = []
    for proc in target_processes:
        # Prefer new registry-based analyzers (Phase 2); fall back to legacy.
        new_analyzer = get_analyzer(proc)
        if new_analyzer is not None:
            try:
                proc_issues = new_analyzer.analyze(ctx)
            except Exception:
                logger.exception("New analyzer failed for %s", proc.value)
                continue
        else:
            legacy = PROCESS_ANALYZERS.get(proc)
            if legacy is None:
                continue
            try:
                proc_issues = legacy(mesh, geometry, proc, ctx.segments)
            except Exception:
                logger.exception("Legacy analyzer failed for %s", proc.value)
                continue
        # Apply rule pack overlay (tighten thresholds, escalate severity)
        if pack:
            proc_issues = pack.apply(proc_issues, proc)
        ps = score_process(proc_issues, geometry, proc)
        process_scores.append(ps)

    result = AnalysisResult(
        filename=filename,
        file_type=suffix.lstrip("."),
        geometry=geometry,
        segments=ctx.segments,
        universal_issues=universal_issues,
        process_scores=process_scores,
        analysis_time_ms=round((time.time() - start) * 1000, 1),
    )

    ranked = rank_processes(result)
    if ranked and ranked[0].score > 0:
        result.best_process = ranked[0].process

    result = enhance_suggestions(result)

    return _to_response(result, features, pack)


@router.post("/validate/quick")
async def validate_quick(file: UploadFile = File(...)):
    """Quick pass/fail check — universal checks only, no process-specific analysis."""
    filename = file.filename or "unknown"
    data = await _read_capped(file)
    mesh, _ = _parse_mesh(data, filename)

    geometry = analyze_geometry(mesh)
    issues = run_universal_checks(mesh)
    has_errors = any(i.severity == Severity.ERROR for i in issues)

    return {
        "filename": filename,
        "verdict": "fail" if has_errors else "pass",
        "geometry": {
            "vertices": geometry.vertex_count,
            "faces": geometry.face_count,
            "volume_mm3": round(geometry.volume, 1),
            "bounding_box_mm": [round(d, 1) for d in geometry.bounding_box.dimensions],
            "is_watertight": geometry.is_watertight,
        },
        "issues": [
            {
                "code": i.code,
                "severity": i.severity.value,
                "message": i.message,
                "fix": i.fix_suggestion,
            }
            for i in issues
        ],
    }


@router.get("/rule-packs")
async def list_rule_packs():
    """List available industry rule packs."""
    packs = []
    for name in available_rule_packs():
        p = get_rule_pack(name)
        if p:
            packs.append({
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "override_count": len(p.overrides),
                "mandatory_issue_count": len(p.mandatory_issues),
            })
    return {"rule_packs": packs}


@router.get("/processes")
async def list_processes():
    return {"processes": get_all_processes()}


@router.get("/materials")
async def list_materials():
    return {
        "materials": [
            {
                "name": m.name,
                "processes": [p.value for p in m.process_types],
                "min_wall_mm": m.min_wall_thickness,
                "tensile_mpa": m.tensile_strength,
                "cost_per_kg_usd": m.cost_per_kg,
                "notes": m.notes,
            }
            for m in MATERIALS
        ]
    }


@router.get("/machines")
async def list_machines():
    return {
        "machines": [
            {
                "name": m.name,
                "manufacturer": m.manufacturer,
                "process": m.process_type.value,
                "build_volume_mm": list(m.build_volume),
                "min_layer_mm": m.min_layer_height,
                "materials": m.materials,
                "notes": m.notes,
            }
            for m in MACHINES
        ]
    }


# ──────────────────────────────────────────────────────────────
# Serialization
# ──────────────────────────────────────────────────────────────
def _to_response(result: AnalysisResult, features: list | None = None, pack=None) -> dict:
    resp = {
        "filename": result.filename,
        "file_type": result.file_type,
        "overall_verdict": result.overall_verdict,
        "best_process": result.best_process.value if result.best_process else None,
        "analysis_time_ms": result.analysis_time_ms,
        "geometry": {
            "vertices": result.geometry.vertex_count,
            "faces": result.geometry.face_count,
            "volume_mm3": round(result.geometry.volume, 1),
            "surface_area_mm2": round(result.geometry.surface_area, 1),
            "bounding_box_mm": [round(d, 1) for d in result.geometry.bounding_box.dimensions],
            "is_watertight": result.geometry.is_watertight,
            "is_manifold": result.geometry.is_manifold,
            "center_of_mass": [round(c, 2) for c in result.geometry.center_of_mass],
            "units": result.geometry.units,
        },
        "segments": [
            {
                "id": s.segment_id,
                "type": s.feature_type.value,
                "face_count": len(s.face_indices),
                "centroid": [round(c, 2) for c in s.centroid],
                "confidence": round(s.confidence, 2),
            }
            for s in result.segments
        ],
        "features": [
            {
                "kind": f.kind.value,
                "face_count": len(f.face_indices),
                "centroid": [round(c, 3) for c in f.centroid],
                "radius": round(f.radius, 3) if f.radius is not None else None,
                "depth": round(f.depth, 3) if f.depth is not None else None,
                "area": round(f.area, 3) if f.area is not None else None,
                "confidence": round(f.confidence, 3),
            }
            for f in (features or [])
        ],
        "universal_issues": [_issue_to_dict(i) for i in result.universal_issues],
        "process_scores": [
            {
                "process": ps.process.value,
                "score": ps.score,
                "verdict": ps.verdict,
                "recommended_material": ps.recommended_material,
                "recommended_machine": ps.recommended_machine,
                "estimated_cost_factor": ps.estimated_cost_factor,
                "issues": [_issue_to_dict(i) for i in ps.issues],
            }
            for ps in sorted(result.process_scores, key=lambda s: s.score, reverse=True)
        ],
        "priority_fixes": get_priority_fixes(result),
    }
    if pack:
        resp["rule_pack"] = {
            "name": pack.name,
            "version": pack.version,
        }
    return resp


def _issue_to_dict(issue: Issue) -> dict:
    d: dict = {
        "code": issue.code,
        "severity": issue.severity.value,
        "message": issue.message,
        "fix_suggestion": issue.fix_suggestion,
    }
    if issue.process:
        d["process"] = issue.process.value
    if issue.affected_faces:
        d["affected_face_count"] = len(issue.affected_faces)
        d["affected_faces_sample"] = issue.affected_faces[:20]
    if issue.region_center:
        d["region_center"] = [round(c, 2) for c in issue.region_center]
    if issue.measured_value is not None:
        d["measured_value"] = round(issue.measured_value, 3)
    if issue.required_value is not None:
        d["required_value"] = issue.required_value
    return d
