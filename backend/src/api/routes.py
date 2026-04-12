"""API route handlers for CADVerify."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Query

from src.analysis.models import (
    AnalysisResult,
    FeatureSegment,
    ProcessType,
    Severity,
)
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.additive_analyzer import ADDITIVE_PROCESSES, run_additive_checks
from src.analysis.cnc_analyzer import CNC_PROCESSES, run_cnc_checks
from src.analysis.molding_analyzer import MOLDING_PROCESSES, run_molding_checks
from src.analysis.sheet_metal_analyzer import run_sheet_metal_checks
from src.analysis.casting_analyzer import CASTING_PROCESSES, run_casting_checks
from src.matcher.profile_matcher import score_process, rank_processes
from src.fixes.fix_suggester import enhance_suggestions, get_priority_fixes
from src.parsers.stl_parser import parse_stl_from_bytes
from src.parsers.step_parser import is_step_supported, parse_step_from_bytes
from src.profiles.database import get_all_processes, MATERIALS, MACHINES
from src.segmentation.fallback import segment_heuristic

router = APIRouter()


# Map process types to their analyzer functions
PROCESS_ANALYZERS = {}
for p in ADDITIVE_PROCESSES:
    PROCESS_ANALYZERS[p] = run_additive_checks
for p in CNC_PROCESSES:
    PROCESS_ANALYZERS[p] = run_cnc_checks
for p in MOLDING_PROCESSES:
    PROCESS_ANALYZERS[p] = run_molding_checks
PROCESS_ANALYZERS[ProcessType.SHEET_METAL] = run_sheet_metal_checks
for p in CASTING_PROCESSES:
    PROCESS_ANALYZERS[p] = run_casting_checks


@router.post("/validate")
async def validate_file(
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types to check. Leave empty for all.",
    ),
):
    """Upload a STEP or STL file and get manufacturing validation results."""
    start = time.time()

    # Determine file type
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".stl", ".step", ".stp"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Use .stl, .step, or .stp",
        )

    # Read file
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    # Parse mesh
    try:
        if suffix == ".stl":
            mesh = parse_stl_from_bytes(data, filename)
        else:
            if not is_step_supported():
                raise HTTPException(
                    status_code=501,
                    detail="STEP parsing requires cadquery. Install with: pip install cadquery",
                )
            mesh = parse_step_from_bytes(data, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Analyze geometry
    geometry = analyze_geometry(mesh)
    universal_issues = run_universal_checks(mesh)

    # Run heuristic segmentation
    segments = segment_heuristic(mesh)

    # Determine which processes to check
    if processes:
        try:
            target_processes = [ProcessType(p.strip()) for p in processes.split(",")]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Unknown process: {e}")
    else:
        target_processes = list(ProcessType)

    # Run process-specific checks
    process_scores = []
    for proc in target_processes:
        analyzer = PROCESS_ANALYZERS.get(proc)
        if analyzer is None:
            continue

        proc_issues = analyzer(mesh, geometry, proc, segments)
        ps = score_process(proc_issues, geometry, proc)
        process_scores.append(ps)

    # Build result
    result = AnalysisResult(
        filename=filename,
        file_type=suffix.lstrip("."),
        geometry=geometry,
        segments=segments,
        universal_issues=universal_issues,
        process_scores=process_scores,
        analysis_time_ms=round((time.time() - start) * 1000, 1),
    )

    # Determine best process
    ranked = rank_processes(result)
    if ranked and ranked[0].score > 0:
        result.best_process = ranked[0].process

    # Enhance suggestions
    result = enhance_suggestions(result)

    # Convert to response dict
    return _to_response(result)


@router.post("/validate/quick")
async def validate_quick(file: UploadFile = File(...)):
    """Quick pass/fail check — universal checks only, no process-specific analysis."""
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()

    if suffix not in (".stl", ".step", ".stp"):
        raise HTTPException(status_code=400, detail=f"Unsupported: {suffix}")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        if suffix == ".stl":
            mesh = parse_stl_from_bytes(data, filename)
        else:
            if not is_step_supported():
                raise HTTPException(status_code=501, detail="STEP parsing requires cadquery")
            mesh = parse_step_from_bytes(data, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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


@router.get("/processes")
async def list_processes():
    """List all supported manufacturing processes."""
    return {"processes": get_all_processes()}


@router.get("/materials")
async def list_materials():
    """List all materials grouped by process."""
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
    """List all machine profiles."""
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


def _to_response(result: AnalysisResult) -> dict:
    """Convert AnalysisResult to JSON-serializable response."""
    return {
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
        "universal_issues": [
            _issue_to_dict(i) for i in result.universal_issues
        ],
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


def _issue_to_dict(issue: Issue) -> dict:
    d = {
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
