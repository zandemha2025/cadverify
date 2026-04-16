"""History API — list and detail endpoints for past analyses.

GET /analyses          — cursor-paginated list (summary fields)
GET /analyses/{id}     — full result_json in metadata envelope
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import Analysis

logger = logging.getLogger("cadverify.history")

router = APIRouter(tags=["history"])

_VALID_VERDICTS = frozenset({"pass", "issues", "fail"})


@router.get("")
@limiter.limit("60/hour;500/day")
async def list_analyses(
    request: Request,
    response: Response,
    cursor: str | None = Query(None, description="ULID cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
    verdict: str | None = Query(None, description="Filter: pass, issues, fail"),
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Return paginated list of the authenticated user's analyses."""
    stmt = select(Analysis).where(Analysis.user_id == user.user_id)

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
        "analyses": [
            {
                "id": a.ulid,
                "filename": a.filename,
                "file_type": a.file_type,
                "verdict": a.verdict,
                "face_count": a.face_count,
                "duration_ms": a.duration_ms,
                "created_at": a.created_at.isoformat(),
                "process_count": len(
                    (a.result_json or {}).get("process_scores", [])
                ),
                "best_process": (a.result_json or {}).get("best_process"),
            }
            for a in items
        ],
        "next_cursor": items[-1].ulid if has_more and items else None,
        "has_more": has_more,
    }


@router.get("/{analysis_id}")
@limiter.limit("60/hour;500/day")
async def get_analysis(
    analysis_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    """Return full analysis result by ULID (own analyses only)."""
    stmt = select(Analysis).where(
        Analysis.ulid == analysis_id,
        Analysis.user_id == user.user_id,
    )
    result = await session.execute(stmt)
    analysis = result.scalar_one_or_none()

    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {
        "id": analysis.ulid,
        "filename": analysis.filename,
        "file_type": analysis.file_type,
        "created_at": analysis.created_at.isoformat(),
        "is_public": analysis.is_public,
        "share_url": f"/s/{analysis.share_short_id}" if analysis.share_short_id else None,
        "result": analysis.result_json,
    }
