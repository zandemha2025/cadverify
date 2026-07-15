"""Analysis service — pipeline orchestration with hash, dedup, persist.

Wraps the existing analysis pipeline (analyzers, features, scoring) with
SHA-256 hashing, per-user dedup cache lookup, ORM persistence, and usage
event tracking.
"""
from __future__ import annotations

import asyncio
import gc
import hashlib
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src import __version__ as _app_version
from src.analysis.base_analyzer import (
    analyze_geometry,
    decimation_issue,
    run_universal_checks,
)
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.models import AnalysisResult, ProcessType, Severity
from src.analysis.processes import get_analyzer
from src.analysis.rules import get_rule_pack
from src.auth.require_api_key import AuthedUser
from src.db.models import Analysis, UsageEvent
from src.fixes.fix_suggester import enhance_suggestions, get_priority_fixes
from src.matcher.profile_matcher import rank_processes, score_process

logger = logging.getLogger("cadverify.analysis_service")


@dataclass(frozen=True)
class AnalysisRun:
    """Internal result plus the exact Analysis row written or reused.

    Request handlers keep receiving the historical response dictionary. Delayed
    workers opt into this wrapper so they can link the exact cache variant that
    ``run_analysis`` selected, rather than racing a later "latest by mesh" query.
    """

    result: dict
    analysis_id: int | None


def _analysis_return(
    result: dict,
    analysis_id: int | None,
    return_persisted_id: bool,
) -> dict | AnalysisRun:
    if return_persisted_id:
        return AnalysisRun(result=result, analysis_id=analysis_id)
    return result


def _force_gc_after_analysis() -> bool:
    """Return True if FORCE_GC_AFTER_ANALYSIS=true (default false)."""
    return os.getenv("FORCE_GC_AFTER_ANALYSIS", "false").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Hashing utilities
# ---------------------------------------------------------------------------


def compute_mesh_hash(file_bytes: bytes) -> str:
    """SHA-256 hex digest of raw uploaded file bytes (D-09)."""
    return hashlib.sha256(file_bytes).hexdigest()


def compute_process_set_hash(process_values: list[str]) -> str:
    """SHA-256 of sorted, comma-joined process type values (D-11)."""
    canonical = ",".join(sorted(process_values))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _persist_source_evidence(
    org_id: str,
    mesh_hash: str,
    filename: str,
    file_bytes: bytes,
    *,
    parsed_mesh=None,
    parse_mesh_async_fn=None,
    source_units: str = "mm",
) -> None:
    """Persist exact source plus a canonical STL derivative.

    The derivative lets the ground-truth engine consume STEP/IGES sources
    without a second CAD kernel dependency. Cache hits lazily backfill it by
    parsing only when the object is absent.
    """
    from src.services.source_artifact_service import (
        costable_mesh_exists,
        save_costable_mesh_artifact,
        save_source_artifact,
    )

    await save_source_artifact(org_id, mesh_hash, filename, file_bytes)
    if await costable_mesh_exists(org_id, mesh_hash):
        return
    mesh = parsed_mesh
    if mesh is None:
        if parse_mesh_async_fn is None:
            raise RuntimeError("source evidence requires a parsed mesh")
        mesh, _suffix = await parse_mesh_async_fn(file_bytes, filename)
        if source_units != "mm":
            from src.costing.units import scale_mesh_to_mm

            mesh = scale_mesh_to_mm(mesh, source_units)
    payload = await asyncio.to_thread(mesh.export, file_type="stl")
    if not isinstance(payload, (bytes, bytearray, memoryview)) or not payload:
        raise RuntimeError("CAD parser did not produce a costable STL derivative")
    await save_costable_mesh_artifact(org_id, mesh_hash, bytes(payload))


# ---------------------------------------------------------------------------
# Cache lookup
# ---------------------------------------------------------------------------


async def _check_cache(
    session: AsyncSession,
    user_id: int,
    mesh_hash: str,
    process_set_hash: str,
    analysis_version: str,
    *,
    org_id: str | None = None,
) -> Analysis | None:
    """Return an existing Analysis row from the caller's organization.

    Request paths may omit ``org_id`` and use the caller's validated active-org
    subquery. Delayed workers pass the immutable organization persisted on their
    parent batch/job so a later user organization switch cannot change ownership.
    """
    from src.auth.org_context import caller_org_subquery

    org_scope = org_id if org_id is not None else caller_org_subquery(user_id)
    stmt = select(Analysis).where(
        Analysis.org_id == org_scope,
        Analysis.user_id == user_id,
        Analysis.mesh_hash == mesh_hash,
        Analysis.process_set_hash == process_set_hash,
        Analysis.analysis_version == analysis_version,
    )
    return (await session.execute(stmt)).scalars().first()


# ---------------------------------------------------------------------------
# Persist analysis
# ---------------------------------------------------------------------------


def _nullable_api_key_id(user: AuthedUser) -> int | None:
    """Return a real API-key FK, or NULL for dashboard-session auth."""
    return user.api_key_id or None


def _sanitize_nonfinite(value):
    """Recursively replace non-finite floats (NaN / ±Inf) with ``None``.

    A degenerate / zero-volume mesh makes trimesh emit NaN for stats like
    center_of_mass; NaN and Inf are *not* valid JSON, so an unsanitized
    result_json makes the asyncpg JSONB INSERT raise
    ``InvalidTextRepresentationError`` and the endpoint returns HTTP 500.

    This is the persist-boundary guard: non-finite → ``null`` (honest
    "uncomputable", never a fabricated ``0``). The verdict itself is untouched
    — the user still gets the honest "geometry invalid" answer, just without a
    crash. Applied to the whole result dict as defense-in-depth on top of the
    per-stat guard in ``analyze_geometry``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _sanitize_nonfinite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_nonfinite(v) for v in value]
    return value


async def _persist_analysis(
    session: AsyncSession,
    user: AuthedUser,
    mesh_hash: str,
    process_set_hash: str,
    analysis_version: str,
    filename: str,
    file_type: str,
    file_size_bytes: int,
    result_json: dict,
    verdict: str,
    face_count: int,
    duration_ms: float,
    signature_vec: Optional[list] = None,
    org_id: str | None = None,
) -> Analysis:
    """Insert a new Analysis row and flush to get the assigned id."""
    from src.auth.org_context import resolve_org

    # Persist-boundary guard: strip non-finite floats (NaN/±Inf) so the JSONB
    # INSERT cannot throw InvalidTextRepresentationError (degenerate meshes).
    result_json = _sanitize_nonfinite(result_json)

    analysis = Analysis(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=(org_id if org_id is not None else await resolve_org(session, user.user_id)),
        api_key_id=_nullable_api_key_id(user),
        mesh_hash=mesh_hash,
        process_set_hash=process_set_hash,
        analysis_version=analysis_version,
        filename=filename,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        result_json=result_json,
        verdict=verdict,
        face_count=face_count,
        duration_ms=duration_ms,
    )
    session.add(analysis)
    await session.flush()  # get id assigned

    # Maintain the materialized per-part catalog projection (Aramco GAP 2 — scale
    # to millions). Same-transaction + graceful-degrade: a projection failure is
    # isolated in a SAVEPOINT and swallowed, never breaking this persist.
    from src.services import part_summary_service

    await part_summary_service.refresh_part_summary_safe(
        session, analysis.org_id, analysis.mesh_hash
    )

    # Customer-context Slice 1: enter this part into the org's identity-retrieval
    # corpus (org-scoped shape signature). The name-hint is the uploaded filename
    # (the name from the file); declared_part_id/program stay NULL until the
    # customer declares them. Best-effort + graceful-degrade in a SAVEPOINT — a
    # corpus write can NEVER break this live analysis persist.
    from src.services import part_signature_service

    await part_signature_service.upsert_signature_safe(
        session,
        analysis.org_id,
        analysis.mesh_hash,
        signature_vec,
        declared_name=filename,
        source="upload",
    )
    return analysis


# ---------------------------------------------------------------------------
# Usage event
# ---------------------------------------------------------------------------


async def _write_usage_event(
    session: AsyncSession,
    user: AuthedUser,
    event_type: str,
    analysis_id: int | None,
    mesh_hash: str | None,
    duration_ms: float | None,
    face_count: int | None,
    org_id: str | None = None,
) -> None:
    """Append a usage_events row (same transaction as analysis persist)."""
    from src.auth.org_context import resolve_org

    event = UsageEvent(
        user_id=user.user_id,
        org_id=(org_id if org_id is not None else await resolve_org(session, user.user_id)),
        api_key_id=_nullable_api_key_id(user),
        event_type=event_type,
        analysis_id=analysis_id,
        mesh_hash=mesh_hash,
        duration_ms=duration_ms,
        face_count=face_count,
    )
    session.add(event)


# ---------------------------------------------------------------------------
# Lazy imports from routes to avoid circular dependency
# (routes.py imports analysis_service; analysis_service needs route helpers)
# ---------------------------------------------------------------------------


def _get_route_helpers():
    """Import route-level helpers lazily to break circular import."""
    from src.api.routes import (
        _analysis_timeout_sec,
        _issue_to_dict,
        _parse_mesh,
        _parse_mesh_async,
        _resolve_target_processes,
        _to_response,
    )
    return (
        _analysis_timeout_sec,
        _issue_to_dict,
        _parse_mesh,
        _resolve_target_processes,
        _to_response,
        _parse_mesh_async,
    )


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


async def run_analysis(
    file_bytes: bytes,
    filename: str,
    processes: str | None,
    rule_pack: str | None,
    user: AuthedUser,
    session: AsyncSession,
    include_thickness: bool = False,
    org_id: str | None = None,
    source_units: str | None = None,
    return_persisted_id: bool = False,
) -> dict | AnalysisRun:
    """Full analysis pipeline: hash -> dedup check -> analyze -> persist -> track.

    On cache hit returns stored result_json without running analyzers.
    On cache miss runs the full pipeline, persists, writes usage_event.
    Handles race condition via IntegrityError catch (T-03B-01).
    """
    (
        analysis_timeout_sec_fn,
        _issue_to_dict,
        _parse_mesh_fn,
        resolve_target_processes_fn,
        to_response_fn,
        parse_mesh_async_fn,
    ) = _get_route_helpers()

    start = time.time()

    # 1. Hash raw bytes BEFORE parsing (D-09, D-10)
    mesh_hash = compute_mesh_hash(file_bytes)

    # 2. Resolve target processes
    target_processes = resolve_target_processes_fn(processes)

    # 3. Resolve and validate the optional governed rule pack before cache
    # lookup. A rule pack changes issue severity, requirements, and citations,
    # so its name AND version are part of the cache identity. Without this, an
    # aerospace request could incorrectly reuse a prior ungoverned analysis of
    # the same bytes and processes.
    pack = None
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        if pack is None:
            from fastapi import HTTPException
            from src.analysis.rules import available_rule_packs

            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    # 4. Process set hash. An inch-authored STL is a different interpreted
    # geometry even when its raw bytes and requested processes are identical.
    # Keep that interpretation in the cache key or an earlier mm result can be
    # returned as a plausible-looking but 25.4×-too-small analysis. Explicit mm
    # remains byte/cache-identical to the historical unset default.
    effective_units = source_units or "mm"
    if effective_units not in {"mm", "inch"}:
        raise ValueError("source_units must be 'mm', 'inch', or None")
    process_fingerprint = [p.value for p in target_processes]
    if effective_units != "mm":
        process_fingerprint.append(f"source_units={effective_units}")
    if pack is not None:
        process_fingerprint.append(
            f"rule_pack={pack.name.lower()}@{pack.version}"
        )
    process_set_hash = compute_process_set_hash(
        process_fingerprint
    )

    # 5. Analysis version from package
    analysis_version = _app_version

    # 6. Cache check.
    # The wall-thickness map is opt-in and deliberately NOT persisted (it would
    # bloat every cached row). It needs a live GeometryContext, which only the
    # fresh path builds — so when the caller asks for it we skip the cache short
    # circuit and run analysis, then attach the map to the RETURNED dict only.
    cached = None
    if not include_thickness:
        cached = await _check_cache(
            session,
            user.user_id,
            mesh_hash,
            process_set_hash,
            analysis_version,
            org_id=org_id,
        )

    if cached is not None:
        # 7. Cache HIT
        logger.info(
            "Cache hit for user=%s mesh_hash=%.12s… version=%s",
            user.user_id,
            mesh_hash,
            analysis_version,
        )
        # A cache hit still carries the caller's exact upload bytes. Persist
        # them under the winning analysis tenant so downstream calibration and
        # governed exports can reconcile to real source evidence. Older rows
        # are therefore backfilled naturally when a user re-opens the file.
        cached_org_id = getattr(cached, "org_id", None)
        if isinstance(cached_org_id, str) and cached_org_id:
            await _persist_source_evidence(
                cached_org_id,
                mesh_hash,
                filename,
                file_bytes,
                parse_mesh_async_fn=parse_mesh_async_fn,
                source_units=effective_units,
            )
        await _write_usage_event(
            session,
            user,
            "analysis_cached",
            cached.id,
            mesh_hash,
            cached.duration_ms,
            cached.face_count,
            org_id=org_id,
        )
        return _analysis_return(
            cached.result_json,
            cached.id,
            return_persisted_id,
        )

    # 8. Cache MISS — run full pipeline.
    # Parse via the ASYNC pooled front door (spawn ProcessPool + per-rung hard
    # wall-clock caps that SIGKILL a runaway worker), NOT the synchronous
    # parse_mesh_fn — a sync gmsh call here runs on the event-loop thread and a
    # pathological periodic-surface part (e.g. nist_ctc_05) grinds 2-3 min,
    # freezing /health, signup, and EVERY other tenant (gauntlet F1). The pooled
    # path keeps the loop free and surfaces an honest error to just this request.
    mesh, suffix = await parse_mesh_async_fn(file_bytes, filename)
    if effective_units != "mm":
        # STL has no units. Convert the parsed mesh at the single geometry seam,
        # before geometry, features, universal checks, process DFM, and persisted
        # output. `scale_mesh_to_mm` returns a copy for inch and never double-scales.
        from src.costing.units import scale_mesh_to_mm

        mesh = scale_mesh_to_mm(mesh, effective_units)

    def _run_analysis_sync():
        geometry = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, geometry)
        # ctx.mesh == mesh unless build() decimated an oversize mesh; detect on
        # ctx.mesh so feature indices align with the context per-face arrays.
        features = detect_features(ctx.mesh)
        ctx.features = features
        universal_issues = run_universal_checks(mesh)
        # Honestly surface to the user when the mesh was decimated for analysis.
        dec_issue = decimation_issue(ctx)
        if dec_issue is not None:
            universal_issues.append(dec_issue)

        process_scores = []
        for proc in target_processes:
            new_analyzer = get_analyzer(proc)
            if new_analyzer is None:
                logger.warning(
                    "No registered analyzer for process %s -- skipping",
                    proc.value,
                )
                continue
            try:
                proc_issues = new_analyzer.analyze(ctx)
            except Exception:
                logger.exception("Analyzer failed for %s", proc.value)
                continue
            if pack:
                proc_issues = pack.apply(proc_issues, proc)
            ps = score_process(proc_issues, geometry, proc)
            process_scores.append(ps)

        # Customer-context Slice 1: compute the 18-dim shape signature while the
        # mesh + geometry + ctx are still alive (they are freed before persist).
        # Best-effort / NON-FATAL — a signature failure must never affect analysis.
        signature_vec = None
        try:
            from src.eval.similarity import feature_vector

            signature_vec = feature_vector(ctx.mesh, geometry, ctx).tolist()
        except Exception:
            logger.warning(
                "shape-signature computation failed — corpus write-back skipped",
                exc_info=True,
            )
        return (
            geometry, ctx, features, universal_issues, process_scores,
            signature_vec,
        )

    timeout_sec = analysis_timeout_sec_fn()
    loop = asyncio.get_event_loop()
    try:
        (
            geometry, ctx, features, universal_issues, process_scores,
            signature_vec,
        ) = (
            await asyncio.wait_for(
                loop.run_in_executor(None, _run_analysis_sync),
                timeout=timeout_sec,
            )
        )
    except asyncio.TimeoutError:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=504,
            detail=(
                f"Analysis exceeded ANALYSIS_TIMEOUT_SEC={timeout_sec:.0f}s. "
                f"Reduce scope with ?processes=... or try /validate/quick."
            ),
        )

    duration_ms = round((time.time() - start) * 1000, 1)

    result = AnalysisResult(
        filename=filename,
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

    result_dict = to_response_fn(result, features, pack)
    if effective_units != "mm":
        result_dict["source_units"] = {
            "declared": effective_units,
            "scale_to_mm": 25.4,
            "provenance": "USER",
            "note": "Source coordinates scaled once before geometry and DFM analysis.",
        }

    # Tolerance analysis for STEP files with AP242 support
    if suffix.lstrip(".") in ("step", "stp"):
        try:
            from src.parsers.step_ap242_parser import is_ap242_supported
            from src.services.tolerance_service import analyze_tolerances, tolerance_report_to_dict

            if is_ap242_supported():
                tol_report = analyze_tolerances(file_bytes, filename, target_processes)
                result_dict["tolerances"] = tolerance_report_to_dict(tol_report)
        except Exception:
            logger.exception(
                "Tolerance analysis failed for %s -- continuing without tolerances",
                filename,
            )
            result_dict["tolerances"] = {
                "has_pmi": False,
                "pmi_note": "Tolerance analysis failed; results based on geometry only.",
            }

    # Capture values needed after cleanup
    _face_count = geometry.face_count
    _verdict = result.overall_verdict

    # Opt-in wall-thickness map: serialize from the live ctx BEFORE it is freed.
    # Kept out of result_dict so the persisted/cached JSON stays lean; attached
    # to the returned dict only (see below).
    _thickness_map = None
    if include_thickness:
        from src.analysis.serialization import serialize_wall_thickness

        _thickness_map = serialize_wall_thickness(
            ctx.wall_thickness, decimation=(ctx.metadata or {}).get("decimation")
        )

    # Release mesh + context memory before async persist
    try:
        mesh._cache.clear()
    except Exception:
        pass
    del ctx, features, universal_issues, process_scores, geometry
    if _force_gc_after_analysis():
        gc.collect()

    # Persist
    persisted_analysis_id: int | None = None
    try:
        analysis = await _persist_analysis(
            session=session,
            user=user,
            mesh_hash=mesh_hash,
            process_set_hash=process_set_hash,
            analysis_version=analysis_version,
            filename=filename,
            file_type=suffix.lstrip("."),
            file_size_bytes=len(file_bytes),
            result_json=result_dict,
            verdict=_verdict,
            face_count=_face_count,
            duration_ms=duration_ms,
            signature_vec=signature_vec,
            org_id=org_id,
        )
        persisted_analysis_id = analysis.id
        # Source bytes are part of the durable evidence chain, not an optional
        # cache. A store failure aborts the request/transaction; strict health
        # preflight prevents accepting CAD into an unhealthy production store.
        if isinstance(analysis.org_id, str) and analysis.org_id:
            await _persist_source_evidence(
                analysis.org_id,
                mesh_hash,
                filename,
                file_bytes,
                parsed_mesh=mesh,
                source_units=effective_units,
            )
        await _write_usage_event(
            session,
            user,
            "analysis_complete",
            analysis.id,
            mesh_hash,
            duration_ms,
            _face_count,
            org_id=org_id,
        )

        # Audit: analysis.created
        from src.services.audit_service import emit_event
        await emit_event(
            session,
            actor_id=user.user_id,
            action="analysis.created",
            resource_type="analysis",
            resource_id=analysis.ulid, file_hash=mesh_hash,
            result_summary=_verdict,
            detail={"process_set_hash": process_set_hash, "file_name": filename},
            org_id=analysis.org_id,
        )
    except IntegrityError:
        # T-03B-01: Race condition — concurrent duplicate insert.
        # Roll back the failed flush and re-query the winning row.
        await session.rollback()
        logger.info(
            "IntegrityError on dedup insert (race), re-querying cache for user=%s mesh=%.12s…",
            user.user_id,
            mesh_hash,
        )
        cached = await _check_cache(
            session,
            user.user_id,
            mesh_hash,
            process_set_hash,
            analysis_version,
            org_id=org_id,
        )
        if cached is not None:
            await _write_usage_event(
                session,
                user,
                "analysis_cached",
                cached.id,
                mesh_hash,
                cached.duration_ms,
                cached.face_count,
                org_id=org_id,
            )
            return _analysis_return(
                _with_thickness(cached.result_json, _thickness_map),
                cached.id,
                return_persisted_id,
            )
        # If re-query also fails, just return the computed result
        # (usage event lost but the user still gets their response).
        logger.warning("Re-query after IntegrityError returned None — returning computed result")

    return _analysis_return(
        _with_thickness(result_dict, _thickness_map),
        persisted_analysis_id,
        return_persisted_id,
    )


def _with_thickness(result_dict: dict, thickness_map: dict | None) -> dict:
    """Attach the opt-in wall-thickness map to a RETURNED response dict.

    Returns a shallow copy with ``wall_thickness_map`` added so the map never
    ends up on the persisted/cached ``result_dict`` (default responses stay
    lean). A no-op when the map was not requested.
    """
    if not thickness_map:
        return result_dict
    return {**result_dict, "wall_thickness_map": thickness_map}


async def get_latest_analysis_id(
    session: AsyncSession,
    user_id: int,
    mesh_hash: str,
    *,
    org_id: str | None = None,
) -> int | None:
    """Return the latest analysis for an organization + user + mesh hash.

    Used by the async SAM-3D submit path to link the job to the just-persisted
    analysis row without changing run_analysis's return signature. Request
    paths resolve the caller's validated active organization in SQL; delayed
    workers pass their parent row's persisted ``org_id`` explicitly.
    """
    from src.auth.org_context import caller_org_subquery
    from sqlalchemy import desc

    org_scope = org_id if org_id is not None else caller_org_subquery(user_id)
    stmt = (
        select(Analysis.id)
        .where(
            Analysis.org_id == org_scope,
            Analysis.user_id == user_id,
            Analysis.mesh_hash == mesh_hash,
        )
        .order_by(desc(Analysis.created_at))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def run_quick_analysis(
    file_bytes: bytes,
    filename: str,
    user: AuthedUser,
    session: AsyncSession,
    org_id: str | None = None,
) -> dict:
    """Quick pass/fail — universal checks only, with dedup + usage tracking."""
    (
        _analysis_timeout_sec_fn,
        _issue_to_dict,
        _parse_mesh_fn,
        _resolve_target_processes_fn,
        _to_response_fn,
        parse_mesh_async_fn,
    ) = _get_route_helpers()

    start = time.time()

    mesh_hash = compute_mesh_hash(file_bytes)
    process_set_hash = compute_process_set_hash(["quick"])
    analysis_version = _app_version

    # Cache check
    cached = await _check_cache(
        session,
        user.user_id,
        mesh_hash,
        process_set_hash,
        analysis_version,
        org_id=org_id,
    )

    if cached is not None:
        logger.info(
            "Quick cache hit for user=%s mesh_hash=%.12s…",
            user.user_id,
            mesh_hash,
        )
        cached_org_id = getattr(cached, "org_id", None)
        if isinstance(cached_org_id, str) and cached_org_id:
            await _persist_source_evidence(
                cached_org_id,
                mesh_hash,
                filename,
                file_bytes,
                parse_mesh_async_fn=parse_mesh_async_fn,
            )
        await _write_usage_event(
            session,
            user,
            "analysis_cached",
            cached.id,
            mesh_hash,
            cached.duration_ms,
            cached.face_count,
            org_id=org_id,
        )
        return cached.result_json

    # Cache miss — run quick analysis. Async pooled parse (off the event loop,
    # hard-capped) — same reason as run_analysis: a sync gmsh call here freezes
    # every tenant on a pathological part (gauntlet F1).
    mesh, suffix = await parse_mesh_async_fn(file_bytes, filename)
    geometry = analyze_geometry(mesh)
    issues = run_universal_checks(mesh)
    has_errors = any(i.severity == Severity.ERROR for i in issues)

    duration_ms = round((time.time() - start) * 1000, 1)

    result_dict = {
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

    verdict = "fail" if has_errors else "pass"

    # Persist
    try:
        analysis = await _persist_analysis(
            session=session,
            user=user,
            mesh_hash=mesh_hash,
            process_set_hash=process_set_hash,
            analysis_version=analysis_version,
            filename=filename,
            file_type=suffix.lstrip("."),
            file_size_bytes=len(file_bytes),
            result_json=result_dict,
            verdict=verdict,
            face_count=geometry.face_count,
            duration_ms=duration_ms,
            org_id=org_id,
        )
        if isinstance(analysis.org_id, str) and analysis.org_id:
            await _persist_source_evidence(
                analysis.org_id,
                mesh_hash,
                filename,
                file_bytes,
                parsed_mesh=mesh,
            )
        await _write_usage_event(
            session,
            user,
            "analysis_complete",
            analysis.id,
            mesh_hash,
            duration_ms,
            geometry.face_count,
            org_id=org_id,
        )
    except IntegrityError:
        await session.rollback()
        logger.info(
            "IntegrityError on quick dedup insert, re-querying for user=%s",
            user.user_id,
        )
        cached = await _check_cache(
            session,
            user.user_id,
            mesh_hash,
            process_set_hash,
            analysis_version,
            org_id=org_id,
        )
        if cached is not None:
            await _write_usage_event(
                session,
                user,
                "analysis_cached",
                cached.id,
                mesh_hash,
                cached.duration_ms,
                cached.face_count,
                org_id=org_id,
            )
            return cached.result_json
        logger.warning("Re-query after IntegrityError returned None — returning computed result")

    return result_dict
