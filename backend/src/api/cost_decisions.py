"""Cost-decision API — persist/list/detail/export/share/compare.

Closes Phase 2 gap #3: the should-cost / make-vs-buy decision becomes a durable,
exportable, shareable, comparable artifact instead of an in-memory value that is
thrown away. Mirrors history.py (cursor pagination), pdf.py (PDF download),
share.py (share/unshare + public view).

Auth: every /api/v1/cost-decisions route is gated by require_role (which
composes require_api_key). The public GET /s/cost/{short_id} is intentionally
unauthenticated (mirrors the existing public analysis share route).

Routes (mounted at /api/v1/cost-decisions):
  GET    ""                      list (cursor paginated; filter process/date)
  GET    /compare?ids=a,b        structured diff of two owned decisions
  GET    /{id}                   full result_json envelope (owner-scoped, 404)
  PUT    /{id}/disposition       persist/withdraw the four-way human outcome
  POST   /{id}/approve           approve/sign off a decision
  DELETE /{id}/approve           reopen approval
  GET    /{id}/pdf               cost-report PDF
  GET    /{id}/export.json       raw result_json
  GET    /{id}/export.csv        estimates / line-items CSV table
  POST   /{id}/share             create public share link
  DELETE /{id}/share             revoke share link

Public (mounted at /s):
  GET    /cost/{short_id}        sanitized public cost view (no owner PII, noindex)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import caller_org_subquery
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_db_session
from src.db.models import CostDecision
from src.services import cost_decision_service as svc
from src.services import cost_pdf_service

logger = logging.getLogger("cadverify.cost_decisions")

router = APIRouter(tags=["cost-decisions"])
public_cost_share_router = APIRouter(tags=["cost-decisions"])


class ApprovalBody(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class DispositionBody(BaseModel):
    disposition: Literal["inhouse", "outside", "acquire", "redesign"] | None
    note: str | None = Field(default=None, max_length=1000)


def _parse_dt(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Invalid {field}: expected ISO 8601 datetime"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("")
@limiter.limit("60/hour;500/day")
async def list_cost_decisions(
    request: Request,
    response: Response,
    cursor: str | None = Query(None, description="ULID cursor for pagination"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
    process: str | None = Query(None, description="Filter by make-now process"),
    created_after: str | None = Query(None, description="ISO datetime lower bound"),
    created_before: str | None = Query(None, description="ISO datetime upper bound"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Paginated list of the caller's organization's saved cost decisions.

    W1 step 3: org-scoped (the tenant boundary) — in v1 the personal org makes
    this identical to the old per-user list; it never leaks another org's rows.
    """
    stmt = select(CostDecision).where(
        CostDecision.org_id == caller_org_subquery(user.user_id)
    )

    if cursor:
        stmt = stmt.where(CostDecision.ulid < cursor)
    if process:
        stmt = stmt.where(CostDecision.make_now_process == process)
    if created_after:
        stmt = stmt.where(CostDecision.created_at >= _parse_dt(created_after, "created_after"))
    if created_before:
        stmt = stmt.where(CostDecision.created_at <= _parse_dt(created_before, "created_before"))

    stmt = stmt.order_by(CostDecision.ulid.desc()).limit(limit + 1)
    rows = (await session.execute(stmt)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]

    return {
        "cost_decisions": [svc._list_item(d) for d in items],
        "next_cursor": items[-1].ulid if has_more and items else None,
        "has_more": has_more,
    }


@router.get("/compare")
@limiter.limit("60/hour;500/day")
async def compare_cost_decisions(
    request: Request,
    response: Response,
    ids: str = Query(..., description="Two comma-separated cost-decision ids, e.g. a,b"),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Structured diff of two owned cost decisions (unit cost by qty, make/tooling
    process, crossover qty, key driver deltas)."""
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    if len(parts) != 2:
        raise HTTPException(
            status_code=400, detail="Provide exactly two ids: ?ids=<a>,<b>"
        )
    a = await svc.get_owned(session, parts[0], user.user_id)
    b = await svc.get_owned(session, parts[1], user.user_id)
    return svc.build_comparison(a, b)


@router.get("/{decision_id}")
@limiter.limit("60/hour;500/day")
async def get_cost_decision(
    decision_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Full saved cost decision by id (own decisions only; 404 for others)."""
    d = await svc.get_owned(session, decision_id, user.user_id)
    return {
        "id": d.ulid,
        "filename": d.filename,
        "file_type": d.file_type,
        "label": d.label,
        "created_at": d.created_at.isoformat(),
        "engine_version": d.engine_version,
        "make_now_process": d.make_now_process,
        "crossover_qty": d.crossover_qty,
        "quantities": d.quantities or [],
        "is_public": d.is_public,
        "share_url": f"/s/cost/{d.share_short_id}" if d.share_short_id else None,
        **svc.governance_fields(d),
        "result": d.result_json,
    }


@router.put("/{decision_id}/disposition")
@limiter.limit("60/hour;300/day")
async def set_cost_decision_disposition(
    decision_id: str,
    body: DispositionBody,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Persist a human sourcing outcome, or withdraw it with ``null``.

    This changes governance metadata only; the computed engine artifact remains
    byte-for-byte intact. A changed outcome automatically reopens prior signoff.
    """
    d = await svc.set_disposition_owned(
        session,
        decision_id,
        user.user_id,
        disposition=body.disposition,
        note=body.note,
    )
    return {"id": d.ulid, **svc.governance_fields(d)}


@router.post("/{decision_id}/approve")
@limiter.limit("60/hour;300/day")
async def approve_cost_decision(
    decision_id: str,
    body: ApprovalBody,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Approve/sign off a saved decision without changing its engine artifact."""
    d = await svc.approve_owned(session, decision_id, user.user_id, note=body.note)
    return {
        "id": d.ulid,
        **svc.governance_fields(d),
    }


@router.delete("/{decision_id}/approve")
@limiter.limit("60/hour;300/day")
async def reopen_cost_decision_approval(
    decision_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Reopen approval/signoff while keeping the saved decision immutable."""
    d = await svc.reopen_owned(session, decision_id, user.user_id)
    return {
        "id": d.ulid,
        **svc.governance_fields(d),
    }


@router.get("/{decision_id}/pdf")
@limiter.limit("60/hour;500/day")
async def download_cost_pdf(
    decision_id: str,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Download the cost-report PDF for a saved decision."""
    pdf_bytes, original_filename = await cost_pdf_service.get_or_generate_cost_pdf(
        decision_id, user.user_id, session
    )
    safe_name = cost_pdf_service.safe_cost_filename(original_filename)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.get("/{decision_id}/export.json")
@limiter.limit("60/hour;500/day")
async def export_cost_json(
    decision_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Export the glass-box decision JSON plus its governance state."""
    d = await svc.get_owned(session, decision_id, user.user_id)
    payload = {
        **(d.result_json or {}),
        "governance": svc.governance_fields(d),
    }
    return Response(
        content=json.dumps(payload, separators=(",", ":")),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="'
                f'{cost_pdf_service.safe_cost_filename(d.filename)[:-4]}.json"'
            )
        },
    )


@router.get("/{decision_id}/export.csv")
@limiter.limit("60/hour;500/day")
async def export_cost_csv(
    decision_id: str,
    request: Request,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """Export estimates, line items, confidence, and governance as CSV."""
    d = await svc.get_owned(session, decision_id, user.user_id)
    csv_text = svc.build_estimates_csv(
        d.result_json or {},
        governance=svc.governance_fields(d),
    )
    stem = cost_pdf_service.safe_cost_filename(d.filename)[:-4]
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


@router.post("/{decision_id}/share")
@limiter.limit("60/hour;500/day")
async def create_cost_share(
    decision_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Share a cost decision — generates a public short URL (/s/cost/...)."""
    return await svc.create_share(decision_id, user.user_id, session)


@router.delete("/{decision_id}/share")
@limiter.limit("60/hour;500/day")
async def revoke_cost_share(
    decision_id: str,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Revoke sharing — the public link 404s immediately."""
    await svc.revoke_share(decision_id, user.user_id, session)
    return {"message": "Share revoked"}


@public_cost_share_router.get("/cost/{short_id}")
@limiter.limit("120/hour")
async def get_shared_cost_decision(
    short_id: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
):
    """Public cost-decision view — sanitized (no owner PII), noindex, no auth."""
    data = await svc.get_shared(short_id, session)
    if data is None:
        raise HTTPException(status_code=404, detail="Shared cost decision not found")
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Cache-Control"] = "private, no-store"
    return data
