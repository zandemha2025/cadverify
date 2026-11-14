"""Deterministic recurring-blocker rollup over an org's saved analyses."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import __version__ as CURRENT_ANALYSIS_VERSION
from src.db.models import Analysis, PartSummary

ALGORITHM_VERSION = "recurring-blockers/v1"
MAX_BLOCKER_PARTS = 1_000
BLOCKING_SEVERITIES = frozenset({"error", "critical", "fail"})
KNOWN_SEVERITIES = BLOCKING_SEVERITIES | {"warning", "warn", "info"}


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _latest_by_part(analyses: Iterable[Analysis], org_id: str) -> dict[str, Analysis]:
    latest: dict[str, Analysis] = {}
    for analysis in analyses:
        mesh_hash = getattr(analysis, "mesh_hash", None)
        if getattr(analysis, "org_id", None) != org_id or not isinstance(mesh_hash, str):
            continue
        current = latest.get(mesh_hash)
        # Reuse the catalog/part-summary convention: lexicographically greatest
        # ULID wins. ULIDs are the persisted monotonic recency key.
        if current is None or str(analysis.ulid) > str(current.ulid):
            latest[mesh_hash] = analysis
    return latest


def _summary_analysis_id(summary: PartSummary) -> tuple[str | None, bool]:
    row = getattr(summary, "row_json", None)
    if not isinstance(row, dict):
        return None, True
    ref = row.get("analysis")
    if ref is None:
        return None, False
    if not isinstance(ref, dict) or not isinstance(ref.get("id"), str):
        return None, True
    return ref["id"], False


def _summaries_by_part(
    summaries: Iterable[PartSummary], org_id: str
) -> tuple[dict[str, PartSummary], int]:
    by_part: dict[str, PartSummary] = {}
    malformed = 0
    for summary in summaries:
        mesh_hash = getattr(summary, "mesh_hash", None)
        if getattr(summary, "org_id", None) != org_id or not isinstance(mesh_hash, str):
            continue
        # The DB constraint allows one summary per org+mesh. The id comparison
        # only keeps this helper deterministic for malformed duplicate inputs.
        if mesh_hash not in by_part or str(getattr(summary, "id", "")) > str(
            getattr(by_part[mesh_hash], "id", "")
        ):
            by_part[mesh_hash] = summary
    for summary in by_part.values():
        malformed += int(_summary_analysis_id(summary)[1])
    return by_part, malformed


def _blocking_findings(result_json: object) -> tuple[list[dict[str, Any]], bool]:
    """Return real engine blockers plus stable saved-finding locators."""
    if not isinstance(result_json, dict):
        return [], True

    findings: list[dict[str, Any]] = []
    malformed = False
    occurrences: defaultdict[tuple[str, str | None, str], int] = defaultdict(int)

    def collect(issues: object, scope: str, process: str | None) -> None:
        nonlocal malformed
        if issues is None:
            return
        if not isinstance(issues, list):
            malformed = True
            return
        for issue in issues:
            if not isinstance(issue, dict):
                malformed = True
                continue
            code = issue.get("code")
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 128
                or code != code.strip()
            ):
                malformed = True
                continue
            occurrence_key = (scope, process, code)
            occurrence = occurrences[occurrence_key]
            occurrences[occurrence_key] += 1
            severity = issue.get("severity")
            message = issue.get("message")
            if (
                not isinstance(severity, str)
                or severity.lower() not in KNOWN_SEVERITIES
                or not isinstance(message, str)
                or not message
                or len(message) > 2000
            ):
                malformed = True
                continue
            if severity.lower() not in BLOCKING_SEVERITIES:
                continue
            finding_ref: dict[str, Any] = {
                "scope": scope,
                "code": code,
                "occurrence": occurrence,
            }
            if process is not None:
                finding_ref["process"] = process
            fix = issue.get("fix_suggestion")
            if fix is not None and (not isinstance(fix, str) or len(fix) > 3000):
                malformed = True
                fix = None
            findings.append(
                {
                    "key": (scope, process, code),
                    "message": message,
                    "fix_suggestion": fix,
                    "finding_ref": finding_ref,
                }
            )

    collect(result_json.get("universal_issues"), "universal", None)
    scores = result_json.get("process_scores")
    if scores is not None and not isinstance(scores, list):
        malformed = True
    elif isinstance(scores, list):
        for score in scores:
            if not isinstance(score, dict):
                malformed = True
                continue
            process = score.get("process")
            if (
                not isinstance(process, str)
                or not process
                or len(process) > 128
                or process != process.strip()
            ):
                malformed = True
                continue
            collect(score.get("issues"), "process", process)
    return findings, malformed


def _projection_status(analysis: Analysis, summary: PartSummary | None) -> str:
    if summary is None:
        return "missing"
    analysis_id, malformed = _summary_analysis_id(summary)
    if malformed:
        return "malformed"
    return "current" if analysis_id == analysis.ulid else "out_of_sync"


def cluster_blockers(
    analyses: Iterable[Analysis],
    summaries: Iterable[PartSummary],
    org_id: str,
    *,
    current_analysis_version: str = CURRENT_ANALYSIS_VERSION,
) -> dict[str, Any]:
    """Cluster blocking findings across distinct latest parts in one org."""
    latest = _latest_by_part(analyses, org_id)
    summary_by_part, malformed_summary_count = _summaries_by_part(summaries, org_id)
    clusters: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    malformed_analysis_count = 0
    parts_with_blockers: set[str] = set()

    for part_key in sorted(latest):
        analysis = latest[part_key]
        findings, malformed = _blocking_findings(analysis.result_json)
        malformed_analysis_count += int(malformed)
        seen: set[tuple[str, str | None, str]] = set()
        for finding in findings:
            key = finding["key"]
            if key in seen:
                continue
            seen.add(key)
            parts_with_blockers.add(part_key)
            summary = summary_by_part.get(part_key)
            projection_status = _projection_status(analysis, summary)
            version_stale = analysis.analysis_version != current_analysis_version
            stale = version_stale or projection_status in {
                "missing",
                "malformed",
                "out_of_sync",
            }
            cluster = clusters.setdefault(
                key,
                {
                    "messages": set(),
                    "fixes": set(),
                    "affected_parts": [],
                },
            )
            cluster["messages"].add(finding["message"])
            if finding["fix_suggestion"]:
                cluster["fixes"].add(finding["fix_suggestion"])
            cluster["affected_parts"].append(
                {
                    "part_key": part_key,
                    "filename": analysis.filename,
                    "analysis": {
                        "id": analysis.ulid,
                        "url": f"/api/v1/analyses/{analysis.ulid}",
                    },
                    "finding_ref": finding["finding_ref"],
                    "message": finding["message"],
                    "fix_suggestion": finding["fix_suggestion"],
                    "created_at": _iso(analysis.created_at),
                    "analysis_version": analysis.analysis_version,
                    "stale": stale,
                    "staleness": {
                        "analysis_version": "stale" if version_stale else "current",
                        "part_summary": projection_status,
                    },
                }
            )

    result = []
    for (scope, process, code), cluster in clusters.items():
        affected = cluster["affected_parts"]
        if len(affected) < 2:
            continue
        affected.sort(key=lambda row: (row["part_key"], row["analysis"]["id"]))
        stale_count = sum(bool(row["stale"]) for row in affected)
        result.append(
            {
                "id": f"{scope}:{process or '*'}:{code}",
                "code": code,
                "scope": scope,
                "process": process,
                "severity": "error",
                "message": (
                    next(iter(cluster["messages"]))
                    if len(cluster["messages"]) == 1
                    else "Engine finding recurs with part-specific details"
                ),
                "fix_suggestion": (
                    next(iter(cluster["fixes"]))
                    if len(cluster["fixes"]) == 1
                    else None
                ),
                "affected_part_count": len(affected),
                "count_basis": "distinct_latest_parts",
                "severity_basis": "saved engine finding severity: error|critical|fail",
                "stale": stale_count > 0,
                "stale_part_count": stale_count,
                "affected_parts": affected,
                "provenance": {
                    "findings": "SAVED_ENGINE_FINDINGS",
                    "part_identity": "ANALYSIS_MESH_HASH_WITH_PART_SUMMARY_ALIGNMENT",
                    "aggregation": "DETERMINISTIC_EXACT_SCOPE_PROCESS_CODE",
                    "validation": "NOT_INFERRED",
                },
            }
        )

    result.sort(
        key=lambda row: (
            -row["affected_part_count"],
            row["scope"],
            row["process"] or "",
            row["code"],
        )
    )
    recurring_parts = {
        row["part_key"]
        for cluster in result
        for row in cluster["affected_parts"]
    }
    stale_recurring_parts = {
        row["part_key"]
        for cluster in result
        for row in cluster["affected_parts"]
        if row["stale"]
    }
    return {
        "clusters": result,
        "summary": {
            "latest_part_count": len(latest),
            "parts_with_blockers": len(parts_with_blockers),
            "recurring_cluster_count": len(result),
            "recurring_affected_part_count": len(recurring_parts),
            "stale_affected_part_count": len(stale_recurring_parts),
            "part_summary_count": len(summary_by_part),
            "malformed_analysis_count": malformed_analysis_count,
            "malformed_part_summary_count": malformed_summary_count,
            "truncated": False,
        },
        "provenance": {
            "source": "ACTIVE_ORGANIZATION_LATEST_SAVED_ANALYSES",
            "part_summaries": "ORG_SCOPED_PROJECTION_METADATA",
            "algorithm_version": ALGORITHM_VERSION,
            "current_analysis_version": current_analysis_version,
            "minimum_distinct_parts": 2,
            "blocking_severities": sorted(BLOCKING_SEVERITIES),
            "llm_inference": False,
        },
    }


async def build_blocker_clusters(
    session: AsyncSession, org_id: str | None
) -> dict[str, Any]:
    """Load only the active org's artifacts and build its blocker rollup."""
    if not org_id:
        return cluster_blockers([], [], "")
    latest = (
        select(
            Analysis.mesh_hash.label("mesh_hash"),
            func.max(Analysis.ulid).label("ulid"),
        )
        .where(Analysis.org_id == org_id)
        .group_by(Analysis.mesh_hash)
        .subquery()
    )
    analyses = (
        (
            await session.execute(
                select(Analysis)
                .join(
                    latest,
                    and_(
                        Analysis.mesh_hash == latest.c.mesh_hash,
                        Analysis.ulid == latest.c.ulid,
                    ),
                )
                .where(Analysis.org_id == org_id)
                .order_by(Analysis.ulid.desc())
                .limit(MAX_BLOCKER_PARTS + 1)
            )
        )
        .scalars()
        .all()
    )
    truncated = len(analyses) > MAX_BLOCKER_PARTS
    analyses = analyses[:MAX_BLOCKER_PARTS]
    mesh_hashes = [row.mesh_hash for row in analyses]
    summaries = []
    if mesh_hashes:
        summaries = (
            (
                await session.execute(
                    select(PartSummary).where(
                        PartSummary.org_id == org_id,
                        PartSummary.has_analysis.is_(True),
                        PartSummary.mesh_hash.in_(mesh_hashes),
                    )
                )
            )
            .scalars()
            .all()
        )
    result = cluster_blockers(analyses, summaries, org_id)
    result["summary"]["truncated"] = truncated
    result["provenance"]["candidate_limit"] = MAX_BLOCKER_PARTS
    result["provenance"]["scope"] = (
        "MOST_RECENT_LATEST_PARTS_BOUNDED" if truncated else "WHOLE_ORGANIZATION"
    )
    return result
