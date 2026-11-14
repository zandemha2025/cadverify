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
import os
import time
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
from src.auth.org_context import caller_org_subquery, resolve_org
from src.auth.require_api_key import AuthedUser
from src.db.models import Analysis, UsageEvent
from src.fixes.fix_suggester import enhance_suggestions, get_priority_fixes
from src.matcher.profile_matcher import rank_processes, score_process

logger = logging.getLogger("cadverify.analysis_service")


def _force_gc_after_analysis() -> bool:
    """Return True if FORCE_GC_AFTER_ANALYSIS=true (default false)."""
    return os.getenv("FORCE_GC_AFTER_ANALYSIS", "false").strip().lower() == "true"


# ---------------------------------------------------------------------------
# Hashing utilities
# ---------------------------------------------------------------------------


def compute_mesh_hash(file_bytes: bytes) -> str:
    """SHA-256 hex digest of raw uploaded file bytes (D-09)."""
    return hashlib.sha256(file_bytes).hexdigest()


def compute_process_set_hash(
    process_values: list[str], rule_pack_identity: str | None = None
) -> str:
    """SHA-256 of the exact process/rule-pack analysis inputs (D-11)."""
    canonical = ",".join(sorted(process_values))
    if rule_pack_identity:
        canonical += f"|rule_pack={rule_pack_identity}"
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cache lookup
# ---------------------------------------------------------------------------


async def _check_cache(
    session: AsyncSession,
    user_id: int,
    org_id: str | None,
    mesh_hash: str,
    process_set_hash: str,
    analysis_version: str,
) -> Analysis | None:
    """Return existing Analysis row if dedup key matches, else None."""
    stmt = select(Analysis).where(
        Analysis.user_id == user_id,
        Analysis.org_id == org_id,
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


async def _persist_analysis(
    session: AsyncSession,
    user: AuthedUser,
    org_id: str | None,
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
) -> Analysis:
    """Insert a new Analysis row and flush to get the assigned id."""
    analysis = Analysis(
        ulid=str(ULID()),
        user_id=user.user_id,
        org_id=org_id,
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
    return analysis


# ---------------------------------------------------------------------------
# Usage event
# ---------------------------------------------------------------------------


async def _write_usage_event(
    session: AsyncSession,
    user: AuthedUser,
    org_id: str | None,
    event_type: str,
    analysis_id: int | None,
    mesh_hash: str | None,
    duration_ms: float | None,
    face_count: int | None,
) -> None:
    """Append a usage_events row (same transaction as analysis persist)."""
    event = UsageEvent(
        user_id=user.user_id,
        org_id=org_id,
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
        _resolve_target_processes,
        _to_response,
    )
    return (
        _analysis_timeout_sec,
        _issue_to_dict,
        _parse_mesh,
        _resolve_target_processes,
        _to_response,
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
) -> dict:
    """Full analysis pipeline: hash -> dedup check -> analyze -> persist -> track.

    On cache hit returns stored result_json without running analyzers.
    On cache miss runs the full pipeline, persists, writes usage_event.
    Handles race condition via IntegrityError catch (T-03B-01).
    """
    (
        analysis_timeout_sec_fn,
        _issue_to_dict,
        parse_mesh_fn,
        resolve_target_processes_fn,
        to_response_fn,
    ) = _get_route_helpers()

    start = time.time()

    # 1. Hash raw bytes BEFORE parsing (D-09, D-10)
    mesh_hash = compute_mesh_hash(file_bytes)

    # 2. Resolve target processes
    target_processes = resolve_target_processes_fn(processes)

    # Resolve and validate the rule pack before constructing the cache key. Its
    # version is part of that key so findings can never cross rule packs.
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

    # 3. Exact analysis-input hash (processes + optional rule pack/version)
    process_set_hash = compute_process_set_hash(
        [p.value for p in target_processes],
        f"{pack.name}@{pack.version}" if pack is not None else None,
    )

    # 4. Analysis version from package
    analysis_version = _app_version
    # Freeze the active tenant for the whole request. A concurrent org switch
    # cannot move the cache hit, persisted row, usage event, or audit halfway
    # through this analysis.
    request_org_id = org_id if org_id is not None else await resolve_org(session, user.user_id)

    # 5. Cache check.
    # The wall-thickness map is opt-in and deliberately NOT persisted (it would
    # bloat every cached row). It needs a live GeometryContext, which only the
    # fresh path builds — so when the caller asks for it we skip the cache short
    # circuit and run analysis, then attach the map to the RETURNED dict only.
    cached = None
    if not include_thickness:
        cached = await _check_cache(
            session, user.user_id, request_org_id, mesh_hash, process_set_hash, analysis_version
        )

    if cached is not None:
        # 6. Cache HIT
        logger.info(
            "Cache hit for user=%s mesh_hash=%.12s… version=%s",
            user.user_id,
            mesh_hash,
            analysis_version,
        )
        await _write_usage_event(
            session,
            user,
            request_org_id,
            "analysis_cached",
            cached.id,
            mesh_hash,
            cached.duration_ms,
            cached.face_count,
        )
        return _with_saved(cached.result_json, cached)

    # 7. Cache MISS — run full pipeline
    mesh, suffix = parse_mesh_fn(file_bytes, filename)

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
        return geometry, ctx, features, universal_issues, process_scores

    timeout_sec = analysis_timeout_sec_fn()
    loop = asyncio.get_event_loop()
    try:
        geometry, ctx, features, universal_issues, process_scores = (
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
            [float(value) for value in ctx.wall_thickness],
            decimation=(ctx.metadata or {}).get("decimation"),
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
    analysis: Analysis | None = None
    try:
        analysis = await _persist_analysis(
            session=session,
            user=user,
            org_id=request_org_id,
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
        )
        await _write_usage_event(
            session,
            user,
            request_org_id,
            "analysis_complete",
            analysis.id,
            mesh_hash,
            duration_ms,
            _face_count,
        )

        # Audit: analysis.created
        from src.services.audit_service import fire_and_forget_audit, _lookup_email
        _audit_email = await _lookup_email(user.user_id)
        asyncio.create_task(fire_and_forget_audit(
            user_id=user.user_id, user_email=_audit_email,
            org_id=request_org_id,
            action="analysis.created", resource_type="analysis",
            resource_id=analysis.ulid, file_hash=mesh_hash,
            result_summary=_verdict,
            detail={"process_set_hash": process_set_hash, "file_name": filename},
        ))
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
            session, user.user_id, request_org_id, mesh_hash, process_set_hash, analysis_version
        )
        if cached is not None:
            await _write_usage_event(
                session,
                user,
                request_org_id,
                "analysis_cached",
                cached.id,
                mesh_hash,
                cached.duration_ms,
                cached.face_count,
            )
            return _with_saved(cached.result_json, cached, _thickness_map)
        # If re-query also fails, just return the computed result
        # (usage event lost but the user still gets their response).
        logger.warning("Re-query after IntegrityError returned None — returning computed result")

    if analysis is None:
        return _with_thickness(result_dict, _thickness_map)
    return _with_saved(result_dict, analysis, _thickness_map)


def _with_thickness(result_dict: dict, thickness_map: dict | None) -> dict:
    """Attach the opt-in wall-thickness map to a RETURNED response dict.

    Returns a shallow copy with ``wall_thickness_map`` added so the map never
    ends up on the persisted/cached ``result_dict`` (default responses stay
    lean). A no-op when the map was not requested.
    """
    if not thickness_map:
        return result_dict
    return {**result_dict, "wall_thickness_map": thickness_map}


def _with_saved(
    result_dict: dict,
    analysis: Analysis,
    thickness_map: dict | None = None,
) -> dict:
    """Attach response-only pointers without mutating persisted ``result_json``."""
    return {
        **_with_thickness(result_dict, thickness_map),
        "saved": {
            "id": analysis.ulid,
            "url": f"/api/v1/analyses/{analysis.ulid}",
        },
    }


async def get_analysis_id_by_ulid(
    session: AsyncSession,
    user_id: int,
    analysis_ulid: str,
    org_id: str | None = None,
) -> int | None:
    """Resolve one exact public analysis ULID to its internal id.

    Async jobs use the ``saved.id`` returned by ``run_analysis`` so identical
    geometry analyzed with another process or rule pack can never be linked by
    an ambiguous "latest mesh" lookup.
    """
    org_scope = org_id if org_id is not None else caller_org_subquery(user_id)
    stmt = select(Analysis.id).where(
        Analysis.user_id == user_id,
        Analysis.org_id == org_scope,
        Analysis.ulid == analysis_ulid,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def run_quick_analysis(
    file_bytes: bytes,
    filename: str,
    user: AuthedUser,
    session: AsyncSession,
) -> dict:
    """Quick pass/fail — universal checks only, with dedup + usage tracking."""
    (
        _analysis_timeout_sec_fn,
        _issue_to_dict,
        parse_mesh_fn,
        _resolve_target_processes_fn,
        _to_response_fn,
    ) = _get_route_helpers()

    start = time.time()

    mesh_hash = compute_mesh_hash(file_bytes)
    process_set_hash = compute_process_set_hash(["quick"])
    analysis_version = _app_version
    org_id = await resolve_org(session, user.user_id)

    # Cache check
    cached = await _check_cache(
        session, user.user_id, org_id, mesh_hash, process_set_hash, analysis_version
    )

    if cached is not None:
        logger.info(
            "Quick cache hit for user=%s mesh_hash=%.12s…",
            user.user_id,
            mesh_hash,
        )
        await _write_usage_event(
            session,
            user,
            org_id,
            "analysis_cached",
            cached.id,
            mesh_hash,
            cached.duration_ms,
            cached.face_count,
        )
        return cached.result_json

    # Cache miss — run quick analysis
    mesh, suffix = parse_mesh_fn(file_bytes, filename)
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
            org_id=org_id,
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
        )
        await _write_usage_event(
            session,
            user,
            org_id,
            "analysis_complete",
            analysis.id,
            mesh_hash,
            duration_ms,
            geometry.face_count,
        )
    except IntegrityError:
        await session.rollback()
        logger.info(
            "IntegrityError on quick dedup insert, re-querying for user=%s",
            user.user_id,
        )
        cached = await _check_cache(
            session, user.user_id, org_id, mesh_hash, process_set_hash, analysis_version
        )
        if cached is not None:
            await _write_usage_event(
                session,
                user,
                org_id,
                "analysis_cached",
                cached.id,
                mesh_hash,
                cached.duration_ms,
                cached.face_count,
            )
            return cached.result_json
        logger.warning("Re-query after IntegrityError returned None — returning computed result")

    return result_dict
