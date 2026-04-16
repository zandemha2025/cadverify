"""API route handlers for CADVerify."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.models import AnalysisResult, Issue, ProcessType
from src.analysis.rules import available_rule_packs, get_rule_pack
from src.api.upload_validation import enforce_triangle_cap, validate_magic
from src.auth.kill_switch import require_kill_switch_open
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.fixes.fix_suggester import get_priority_fixes
from src.parsers.step_parser import is_step_supported, parse_step_from_bytes
from src.parsers.stl_parser import parse_stl_from_bytes
from src.profiles.database import MACHINES, MATERIALS, get_all_processes
from src.services import analysis_service, repair_service

logger = logging.getLogger("cadverify.routes")

router = APIRouter()


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


def _analysis_timeout_sec() -> float:
    """Read ANALYSIS_TIMEOUT_SEC lazily so tests can override via monkeypatch."""
    try:
        return max(0.1, float(os.getenv("ANALYSIS_TIMEOUT_SEC", "60")))
    except ValueError:
        return 60.0


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
@router.post("/validate", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_file(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types to check. Leave empty for all.",
    ),
    rule_pack: Optional[str] = Query(
        None,
        description="Industry rule pack: aerospace, automotive, oil_gas, medical.",
    ),
    segmentation: Optional[str] = Query(
        None,
        description="Segmentation method: 'sam3d' for async SAM-3D (returns 202).",
    ),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload a STEP or STL file and get manufacturing validation results."""
    # Validate rule pack early (before reading file bytes)
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        if pack is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    data = await _read_capped(file)
    result = await analysis_service.run_analysis(
        file_bytes=data,
        filename=file.filename or "unknown",
        processes=processes,
        rule_pack=rule_pack,
        user=user,
        session=session,
    )

    if segmentation == "sam3d":
        from fastapi.responses import JSONResponse

        from src.jobs.arq_backend import get_job_queue
        from src.services import job_service

        # Compute mesh hash (same algorithm as analysis_service)
        mesh_hash = analysis_service.compute_mesh_hash(data)

        # Look up the just-persisted analysis row
        analysis_id = await analysis_service.get_latest_analysis_id(
            session, user.user_id, mesh_hash,
        )
        if analysis_id is None:
            # Defensive: analysis should have been persisted by run_analysis
            raise HTTPException(
                status_code=500,
                detail="Analysis row not found after persist -- cannot enqueue SAM-3D job.",
            )

        # Save mesh blob for worker retrieval
        await job_service.save_mesh_blob(mesh_hash, data)

        # Create job (idempotent by analysis_id + sam3d)
        job = await job_service.create_sam3d_job(
            session, analysis_id, user.user_id, mesh_hash,
        )
        await session.commit()

        # Enqueue arq job
        queue = await get_job_queue()
        await queue.enqueue("sam3d", {"mesh_hash": mesh_hash}, job.ulid)

        return JSONResponse(
            status_code=202,
            content={
                "analysis_id": analysis_id,
                "job_id": job.ulid,
                "poll_url": f"/api/v1/jobs/{job.ulid}",
                "result": result,
            },
        )

    return result


@router.post("/validate/quick", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_quick(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Quick pass/fail check — universal checks only, no process-specific analysis."""
    data = await _read_capped(file)
    return await analysis_service.run_quick_analysis(
        file_bytes=data,
        filename=file.filename or "unknown",
        user=user,
        session=session,
    )


@router.post("/validate/demo", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("10/hour")
async def validate_demo(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types. Leave empty for all.",
    ),
):
    """Public demo — full analysis, no auth, no persistence, tight rate limit."""
    import asyncio
    import time

    from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
    from src.analysis.context import GeometryContext
    from src.analysis.features.detector import detect_features
    from src.analysis.scoring import rank_processes, score_process
    from src.analysis.suggestion_engine import enhance_suggestions
    from src.profiles.database import get_analyzer

    data = await _read_capped(file)
    mesh, suffix = _parse_mesh(data, file.filename or "unknown")
    target_processes = _resolve_target_processes(processes)

    start = time.time()

    def _run():
        geometry = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, geometry)
        features = detect_features(mesh)
        ctx.features = features
        universal_issues = run_universal_checks(mesh)
        process_scores = []
        for proc in target_processes:
            analyzer = get_analyzer(proc)
            if analyzer is None:
                continue
            try:
                proc_issues = analyzer.analyze(ctx)
            except Exception:
                logger.exception("Demo analyzer failed for %s", proc.value)
                continue
            ps = score_process(proc_issues, geometry, proc)
            process_scores.append(ps)
        return geometry, ctx, features, universal_issues, process_scores

    timeout = _analysis_timeout_sec()
    loop = asyncio.get_event_loop()
    try:
        geometry, ctx, features, universal_issues, process_scores = (
            await asyncio.wait_for(
                loop.run_in_executor(None, _run),
                timeout=timeout,
            )
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Analysis exceeded {timeout:.0f}s timeout.",
        )

    duration_ms = round((time.time() - start) * 1000, 1)

    result = AnalysisResult(
        filename=file.filename or "unknown",
        file_type=suffix.lstrip("."),
        geometry=geometry,
        segments=ctx.segments,
        universal_issues=universal_issues,
        process_scores=process_scores,
        analysis_time_ms=duration_ms,
    )
    ranked = rank_processes(result)
    if ranked and ranked[0].score > 0:
        result.best_process = ranked[0].process
    result = enhance_suggestions(result)

    resp = _to_response(result, features)
    resp["demo"] = True
    return resp


@router.post("/validate/repair", dependencies=[Depends(require_kill_switch_open)])
@limiter.limit("60/hour;500/day")
async def validate_repair(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    processes: Optional[str] = Query(
        None,
        description="Comma-separated process types for re-analysis. Leave empty for all.",
    ),
    rule_pack: Optional[str] = Query(
        None,
        description="Industry rule pack: aerospace, automotive, oil_gas, medical.",
    ),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Upload a STEP or STL file, attempt mesh repair, and get before/after analysis."""
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        if pack is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    data = await _read_capped(file)
    return await repair_service.repair_mesh(
        file_bytes=data,
        filename=file.filename or "unknown",
        processes=processes,
        rule_pack=rule_pack,
        user=user,
        session=session,
    )


@router.get("/rule-packs")
@limiter.limit("60/hour;500/day")
async def list_rule_packs(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
):
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
@limiter.limit("60/hour;500/day")
async def list_processes(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
):
    return {"processes": get_all_processes()}


@router.get("/materials")
@limiter.limit("60/hour;500/day")
async def list_materials(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
):
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
@limiter.limit("60/hour;500/day")
async def list_machines(
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
):
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
