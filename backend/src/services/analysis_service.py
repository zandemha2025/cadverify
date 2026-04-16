"""Analysis service — pipeline orchestration with hash, dedup, persist.

Wraps the existing analysis pipeline (analyzers, features, scoring) with
SHA-256 hashing, per-user dedup cache lookup, ORM persistence, and usage
event tracking.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src import __version__ as _app_version
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
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


# ---------------------------------------------------------------------------
# Cache lookup
# ---------------------------------------------------------------------------


async def _check_cache(
    session: AsyncSession,
    user_id: int,
    mesh_hash: str,
    process_set_hash: str,
    analysis_version: str,
) -> Analysis | None:
    """Return existing Analysis row if dedup key matches, else None."""
    stmt = select(Analysis).where(
        Analysis.user_id == user_id,
        Analysis.mesh_hash == mesh_hash,
        Analysis.process_set_hash == process_set_hash,
        Analysis.analysis_version == analysis_version,
    )
    return (await session.execute(stmt)).scalars().first()


# ---------------------------------------------------------------------------
# Persist analysis
# ---------------------------------------------------------------------------


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
) -> Analysis:
    """Insert a new Analysis row and flush to get the assigned id."""
    analysis = Analysis(
        ulid=str(ULID()),
        user_id=user.user_id,
        api_key_id=user.api_key_id,
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
) -> None:
    """Append a usage_events row (same transaction as analysis persist)."""
    event = UsageEvent(
        user_id=user.user_id,
        api_key_id=user.api_key_id,
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

    # 3. Process set hash
    process_set_hash = compute_process_set_hash(
        [p.value for p in target_processes]
    )

    # 4. Analysis version from package
    analysis_version = _app_version

    # 5. Cache check
    cached = await _check_cache(
        session, user.user_id, mesh_hash, process_set_hash, analysis_version
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
            "analysis_cached",
            cached.id,
            mesh_hash,
            cached.duration_ms,
            cached.face_count,
        )
        return cached.result_json

    # 7. Cache MISS — run full pipeline
    mesh, suffix = parse_mesh_fn(file_bytes, filename)

    # Resolve rule pack
    pack = None
    if rule_pack:
        pack = get_rule_pack(rule_pack)
        # Invalid rule_pack already caught by routes.py caller; but guard anyway
        if pack is None:
            from fastapi import HTTPException
            from src.analysis.rules import available_rule_packs

            raise HTTPException(
                status_code=400,
                detail=f"Unknown rule pack '{rule_pack}'. Available: {available_rule_packs()}",
            )

    def _run_analysis_sync():
        geometry = analyze_geometry(mesh)
        ctx = GeometryContext.build(mesh, geometry)
        features = detect_features(mesh)
        ctx.features = features
        universal_issues = run_universal_checks(mesh)

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
            verdict=result.overall_verdict,
            face_count=geometry.face_count,
            duration_ms=duration_ms,
        )
        await _write_usage_event(
            session,
            user,
            "analysis_complete",
            analysis.id,
            mesh_hash,
            duration_ms,
            geometry.face_count,
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
            session, user.user_id, mesh_hash, process_set_hash, analysis_version
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
            )
            return cached.result_json
        # If re-query also fails, just return the computed result
        # (usage event lost but the user still gets their response).
        logger.warning("Re-query after IntegrityError returned None — returning computed result")

    return result_dict


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

    # Cache check
    cached = await _check_cache(
        session, user.user_id, mesh_hash, process_set_hash, analysis_version
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
            session, user.user_id, mesh_hash, process_set_hash, analysis_version
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
            )
            return cached.result_json
        logger.warning("Re-query after IntegrityError returned None — returning computed result")

    return result_dict
