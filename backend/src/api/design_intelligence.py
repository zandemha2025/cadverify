"""Authenticated advisory design-intelligence endpoint."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.org_context import resolve_org
from src.auth.rate_limit import limiter
from src.auth.rbac import Role, require_role
from src.auth.require_api_key import AuthedUser
from src.db.engine import get_db_session
from src.db.models import Analysis, AuditLog
from src.services import design_intelligence_service as service
from src.services import org_precedent_service
from src.services.audit_service import _lookup_email, emit_event

logger = logging.getLogger("cadverify.design_intelligence_api")
router = APIRouter()


class FindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    code: str = Field(min_length=1, max_length=128)
    severity: Literal["error", "warning", "info"]
    message: str = Field(min_length=1, max_length=2000)
    fix_suggestion: Optional[str] = Field(default=None, max_length=3000)
    process: Optional[str] = Field(default=None, max_length=128)
    measured_value: Optional[float] = None
    required_value: Optional[float] = None


class ExplainFindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    finding: FindingInput
    limit: int = Field(default=3, ge=1, le=5)


class FindingRef(BaseModel):
    """Stable locator for a finding already persisted by the engine."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, strict=True
    )

    scope: Literal["universal", "process"]
    code: str = Field(min_length=1, max_length=128)
    occurrence: int = Field(default=0, ge=0, le=10_000)
    process: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "process" and self.process is None:
            raise ValueError("process is required for process scope")
        if self.scope == "universal" and self.process is not None:
            raise ValueError("process is only valid for process scope")
        return self

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class AnalysisExplainRequest(FindingRef):
    limit: int = Field(default=3, ge=1, le=5)

    def finding_ref(self) -> dict[str, Any]:
        return self.model_dump(exclude={"limit"}, exclude_none=True)


class AnalysisFeedbackRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, strict=True
    )

    decision: Optional[
        Literal[
            "make_in_house",
            "make_outside",
            "acquire_capability",
            "redesign",
        ]
    ] = None
    advisory: Optional[Literal["helpful", "not_relevant", "incorrect"]] = None
    finding_ref: Optional[FindingRef] = None

    @model_validator(mode="after")
    def validate_signal(self):
        if self.decision is None and self.advisory is None:
            raise ValueError("decision or advisory is required")
        if (self.advisory is None) != (self.finding_ref is None):
            raise ValueError("finding_ref is required exactly when advisory is set")
        return self


_FINDING_FIELDS = frozenset(
    {
        "code",
        "severity",
        "message",
        "fix_suggestion",
        "process",
        "measured_value",
        "required_value",
    }
)


def _resolve_finding(result_json: object, locator: FindingRef) -> dict | None:
    """Resolve one engine finding without accepting any finding content from a caller."""
    if not isinstance(result_json, dict):
        return None
    if locator.scope == "universal":
        issue_groups = [result_json.get("universal_issues")]
    else:
        scores = result_json.get("process_scores")
        issue_groups = (
            [
                score.get("issues")
                for score in scores
                if isinstance(score, dict)
                and score.get("process") == locator.process
            ]
            if isinstance(scores, list)
            else []
        )

    matches = [
        issue
        for issues in issue_groups
        if isinstance(issues, list)
        for issue in issues
        if isinstance(issue, dict) and issue.get("code") == locator.code
    ]
    if locator.occurrence >= len(matches):
        return None
    # Old saved rows can contain extra visualization/citation fields. Retrieval
    # needs only the same bounded fields accepted by the live compatibility API.
    finding = {
        key: value
        for key, value in matches[locator.occurrence].items()
        if key in _FINDING_FIELDS
    }
    if locator.scope == "process":
        finding["process"] = locator.process
    return finding


async def _active_org_analysis(
    session: AsyncSession, user_id: int, analysis_ulid: str
) -> tuple[Analysis, str]:
    """Resolve an analysis without revealing whether another org owns it."""
    org_id = await resolve_org(session, user_id)
    if org_id is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    analysis = (
        await session.execute(
            select(Analysis).where(
                Analysis.ulid == analysis_ulid,
                Analysis.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis, org_id


_FEEDBACK_ACTION = "design_intelligence.feedback_recorded"
_FEEDBACK_SOURCE = "authenticated_user"
_FEEDBACK_PROVENANCE = "user"


async def _latest_feedback_row(
    session: AsyncSession,
    org_id: str,
    analysis_ulid: str,
    key: str,
    finding_ref: FindingRef | None = None,
) -> AuditLog | None:
    statement = select(AuditLog).where(
        AuditLog.org_id == org_id,
        AuditLog.action == _FEEDBACK_ACTION,
        AuditLog.resource_type == "analysis",
        AuditLog.resource_id == analysis_ulid,
        AuditLog.detail_json[key].as_string().is_not(None),
    )
    if finding_ref is not None:
        statement = statement.where(
            AuditLog.detail_json["finding_ref"].contains(finding_ref.as_dict())
        )
    return (
        await session.execute(statement.order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none()


def _feedback_response(
    analysis_ulid: str,
    decision_row: AuditLog | None,
    advisory_row: AuditLog | None,
) -> dict[str, Any]:
    decision = (decision_row.detail_json or {}) if decision_row else {}
    advisory = (advisory_row.detail_json or {}) if advisory_row else {}
    return {
        "analysis_id": analysis_ulid,
        "saved": True,
        "decision": decision.get("decision"),
        "advisory": advisory.get("advisory"),
        "finding_ref": advisory.get("finding_ref"),
        "source": _FEEDBACK_SOURCE,
        "provenance": _FEEDBACK_PROVENANCE,
    }


def _citation_urls(result: dict) -> list[str]:
    """Return distinct cited URLs for audit detail, never corpus excerpts."""
    urls: list[str] = []
    for key in ("possible_intents", "relevant_requirements", "workflow_evidence"):
        for row in result.get(key, []):
            url = row.get("source_url") if isinstance(row, dict) else None
            if isinstance(url, str) and url and url not in urls:
                urls.append(url)
    return urls


@router.post("/explain")
@limiter.limit("120/hour;1000/day")
async def explain_finding(
    payload: ExplainFindingRequest,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    if not service.design_intelligence_enabled():
        raise HTTPException(status_code=503, detail="Design intelligence is disabled")
    if await resolve_org(session, user.user_id) is None:
        raise HTTPException(status_code=403, detail="Organization membership required")
    result = await service.explain_finding_async(
        payload.finding.model_dump(exclude_none=True), limit=payload.limit
    )
    logger.info(
        "design_intelligence_explain code=%s status=%s evidence=%d research=%s",
        payload.finding.code,
        result["status"],
        len(result["workflow_evidence"]),
        result.get("research_mode", False),
    )
    return result


@router.post("/analyses/{analysis_ulid}/explain")
@limiter.limit("120/hour;1000/day")
async def explain_saved_finding(
    analysis_ulid: str,
    payload: AnalysisExplainRequest,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Explain a server-owned finding from an analysis in the caller's active org."""
    if not service.design_intelligence_enabled():
        raise HTTPException(status_code=503, detail="Design intelligence is disabled")
    analysis, org_id = await _active_org_analysis(
        session, user.user_id, analysis_ulid
    )

    finding = _resolve_finding(analysis.result_json, payload)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    result = await service.explain_finding_async(finding, limit=payload.limit)
    finding_ref = payload.finding_ref()
    emit_event(
        user.user_id,
        "design_intelligence.explained",
        "analysis",
        analysis.ulid,
        {
            "finding_ref": finding_ref,
            "status": result["status"],
            "citations": _citation_urls(result),
        },
        org_id,
    )
    logger.info(
        "design_intelligence_explain_saved analysis=%s code=%s status=%s evidence=%d research=%s",
        analysis.ulid,
        payload.code,
        result["status"],
        len(result["workflow_evidence"]),
        result.get("research_mode", False),
    )
    return {
        **result,
        "analysis_id": analysis.ulid,
        "finding_ref": finding_ref,
    }


@router.put("/analyses/{analysis_ulid}/feedback")
@limiter.limit("120/hour;600/day")
async def record_analysis_feedback(
    analysis_ulid: str,
    payload: AnalysisFeedbackRequest,
    request: Request,
    response: Response,
    user: AuthedUser = Depends(require_role(Role.analyst)),
    session: AsyncSession = Depends(get_db_session),
):
    """Durably record user feedback and/or a decision for a saved analysis."""
    analysis, org_id = await _active_org_analysis(
        session, user.user_id, analysis_ulid
    )
    if payload.finding_ref is not None and _resolve_finding(
        analysis.result_json, payload.finding_ref
    ) is None:
        raise HTTPException(status_code=404, detail="Finding not found")

    decision_row = await _latest_feedback_row(
        session, org_id, analysis.ulid, "decision"
    )
    advisory_row = await _latest_feedback_row(
        session, org_id, analysis.ulid, "advisory", payload.finding_ref
    )
    decision_detail = (decision_row.detail_json or {}) if decision_row else {}
    advisory_detail = (advisory_row.detail_json or {}) if advisory_row else {}
    current_decision = decision_detail.get("decision")
    current_advisory = advisory_detail.get("advisory")
    current_ref = advisory_detail.get("finding_ref")
    finding_ref = payload.finding_ref.as_dict() if payload.finding_ref else None
    unchanged = (
        (payload.decision is None or payload.decision == current_decision)
        and (payload.advisory is None or payload.advisory == current_advisory)
        and (finding_ref is None or finding_ref == current_ref)
    )

    if not unchanged:
        actor_email = await _lookup_email(user.user_id)
        detail: dict[str, Any] = {
            "source": _FEEDBACK_SOURCE,
            "provenance": _FEEDBACK_PROVENANCE,
        }
        if payload.decision is not None:
            detail["decision"] = payload.decision
        if payload.advisory is not None:
            detail["advisory"] = payload.advisory
            detail["finding_ref"] = finding_ref
        entry = AuditLog(
            user_id=user.user_id,
            org_id=org_id,
            user_email=actor_email,
            action=_FEEDBACK_ACTION,
            resource_type="analysis",
            resource_id=analysis.ulid,
            detail_json=detail,
        )
        session.add(entry)
        if payload.decision is not None:
            decision_row = entry
        if payload.advisory is not None:
            advisory_row = entry

    await session.commit()
    return _feedback_response(analysis.ulid, decision_row, advisory_row)


@router.get("/analyses/{analysis_ulid}/feedback")
@limiter.limit("120/hour;1000/day")
async def get_analysis_feedback(
    analysis_ulid: str,
    request: Request,
    response: Response,
    scope: Literal["universal", "process"] | None = Query(default=None),
    code: str | None = Query(default=None, min_length=1, max_length=128),
    occurrence: int | None = Query(default=None, ge=0, le=10_000),
    process: str | None = Query(default=None, min_length=1, max_length=128),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Read analysis-wide decision memory and optionally one finding's feedback."""
    analysis, org_id = await _active_org_analysis(
        session, user.user_id, analysis_ulid
    )
    locator: FindingRef | None = None
    if any(value is not None for value in (scope, code, occurrence, process)):
        if scope is None or code is None:
            raise HTTPException(
                status_code=422,
                detail="scope and code are required for finding feedback",
            )
        try:
            locator = FindingRef(
                scope=scope,
                code=code,
                occurrence=occurrence if occurrence is not None else 0,
                process=process,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if _resolve_finding(analysis.result_json, locator) is None:
            raise HTTPException(status_code=404, detail="Finding not found")
    decision_row = await _latest_feedback_row(
        session, org_id, analysis.ulid, "decision"
    )
    advisory_row = await _latest_feedback_row(
        session, org_id, analysis.ulid, "advisory", locator
    )
    return _feedback_response(analysis.ulid, decision_row, advisory_row)


@router.get("/analyses/{analysis_ulid}/precedents")
@limiter.limit("120/hour;1000/day")
async def get_saved_analysis_precedents(
    analysis_ulid: str,
    request: Request,
    response: Response,
    limit: int = Query(default=3, ge=1, le=5),
    user: AuthedUser = Depends(require_role(Role.viewer)),
    session: AsyncSession = Depends(get_db_session),
):
    """Return deterministic geometry precedents from the active org only."""
    org_id = await resolve_org(session, user.user_id)
    if org_id is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    result = await org_precedent_service.get_org_precedents(
        session, org_id, analysis_ulid, limit
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    emit_event(
        user.user_id,
        "design_intelligence.precedents_viewed",
        "analysis",
        analysis_ulid,
        {
            "status": result["status"],
            "case_count": len(result["cases"]),
            "algorithm_version": result["algorithm_version"],
        },
        org_id,
    )
    return result
