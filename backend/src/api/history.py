"""History API — list and detail endpoints for past analyses.

GET /analyses          — cursor-paginated list (summary fields)
GET /analyses/{id}     — full result_json in metadata envelope
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import caller_org_subquery
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Analysis, CostDecision

logger = logging.getLogger("cadverify.history")

router = APIRouter(tags=["history"])

_VALID_VERDICTS = frozenset({"pass", "issues", "fail"})


def _serialize_analysis_summary(analysis: Analysis) -> dict:
    """Return the browser contract plus legacy aliases used by API clients."""
    return {
        "id": analysis.ulid,
        "ulid": analysis.ulid,
        "filename": analysis.filename,
        "file_type": analysis.file_type,
        "verdict": analysis.verdict,
        "overall_verdict": analysis.verdict,
        "face_count": analysis.face_count,
        "duration_ms": analysis.duration_ms,
        "analysis_time_ms": analysis.duration_ms,
        "created_at": analysis.created_at.isoformat(),
        "process_count": len(
            (analysis.result_json or {}).get("process_scores", [])
        ),
        "best_process": (analysis.result_json or {}).get("best_process"),
    }


def _serialize_decision_link(decision: CostDecision) -> dict:
    return {
        "id": decision.ulid,
        "url": f"/cost-decisions/{decision.ulid}",
        "filename": decision.filename,
        "make_now_process": decision.make_now_process,
        "approval_status": decision.approval_status,
        "created_at": decision.created_at.isoformat(),
    }


def _serialize_analysis_detail(
    analysis: Analysis,
    decisions: list[CostDecision],
) -> dict:
    return {
        "id": analysis.ulid,
        "ulid": analysis.ulid,
        "filename": analysis.filename,
        "file_type": analysis.file_type,
        "verdict": analysis.verdict,
        "overall_verdict": analysis.verdict,
        "face_count": analysis.face_count,
        "duration_ms": analysis.duration_ms,
        "analysis_time_ms": analysis.duration_ms,
        "created_at": analysis.created_at.isoformat(),
        "is_public": analysis.is_public,
        "share_url": (
            f"/s/{analysis.share_short_id}" if analysis.share_short_id else None
        ),
        "result": analysis.result_json,
        "result_json": analysis.result_json,
        "decision_links": [_serialize_decision_link(row) for row in decisions],
    }


@router.get("")
@limiter.limit("60/hour;500/day")
async def list_analyses(
    request: Request,
    response: Response,
    cursor: str | None = Query(None, description="ULID cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
    verdict: str | None = Query(None, description="Filter: pass, issues, fail"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Return paginated list of analyses owned by the caller's organization.

    W1 step 3: scoped by ``org_id`` (the tenant boundary), resolved from the
    caller via a correlated subquery. In v1 each user has a personal org, so
    this is identical to the old per-user list; once an org holds more than one
    member the list is the org's shared history. Never leaks another org's rows.
    """
    stmt = select(Analysis).where(
        Analysis.org_id == caller_org_subquery(user.user_id)
    )

    if cursor:
        stmt = stmt.where(Analysis.ulid < cursor)

    if verdict and verdict in _VALID_VERDICTS:
        stmt = stmt.where(Analysis.verdict == verdict)

    # Fetch one extra row to detect whether more pages exist.
    stmt = stmt.order_by(Analysis.ulid.desc()).limit(limit + 1)

    result = await session.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]

    return {
        "analyses": [_serialize_analysis_summary(a) for a in items],
        "next_cursor": items[-1].ulid if has_more and items else None,
        "has_more": has_more,
    }


@router.get("/{analysis_id}")
@limiter.limit("60/hour;500/day")
async def get_analysis(
    analysis_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Return full analysis result by ULID (caller's org only; 404 otherwise)."""
    stmt = select(Analysis).where(
        Analysis.ulid == analysis_id,
        Analysis.org_id == caller_org_subquery(user.user_id),
    )
    result = await session.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    decision_result = await session.execute(
        select(CostDecision)
        .where(
            CostDecision.org_id == analysis.org_id,
            CostDecision.mesh_hash == analysis.mesh_hash,
        )
        .order_by(CostDecision.created_at.desc())
        .limit(20)
    )
    decisions = list(decision_result.scalars().all())

    return _serialize_analysis_detail(analysis, decisions)
