"""Deterministic, tenant-local precedent retrieval over saved analyses."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src import __version__ as CURRENT_ANALYSIS_VERSION
from src.db.models import Analysis

ALGORITHM_VERSION = "geometry-precedent/v3"
CORPUS_VERSION = "org-saved-analyses/v1"
# Conservative abstention threshold until organization outcomes can calibrate it.
# A one-order-of-magnitude miss in one of five comparable measures alone scores
# about 0.45, so 0.35 excludes clearly different geometry.
MAX_GEOMETRY_DISTANCE = 0.35
MAX_PRECEDENT_CANDIDATES = 500


@dataclass(frozen=True)
class _Geometry:
    bbox_mm: tuple[float, float, float]
    shape_ratios: tuple[float, float]
    volume_mm3: float | None
    surface_area_mm2: float | None
    faces: float | None
    feature_counts: dict[str, int] | None


def _positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _geometry(result_json: object) -> _Geometry | None:
    if not isinstance(result_json, dict):
        return None
    raw = result_json.get("geometry")
    if not isinstance(raw, dict):
        return None
    bbox = raw.get("bounding_box_mm")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 3:
        return None
    dimensions = [_positive_number(value) for value in bbox]
    if any(value is None for value in dimensions):
        return None
    values = sorted(value for value in dimensions if value is not None)
    ordered = (values[0], values[1], values[2])
    longest = ordered[2]

    feature_counts: dict[str, int] | None = None
    features = result_json.get("features")
    if isinstance(features, list):
        counts = Counter(
            row["kind"]
            for row in features
            if isinstance(row, dict)
            and isinstance(row.get("kind"), str)
            and 0 < len(row["kind"]) <= 64
        )
        feature_counts = dict(counts)

    return _Geometry(
        bbox_mm=ordered,
        shape_ratios=(ordered[0] / longest, ordered[1] / longest),
        volume_mm3=_positive_number(raw.get("volume_mm3")),
        surface_area_mm2=_positive_number(raw.get("surface_area_mm2")),
        faces=_positive_number(raw.get("faces")),
        feature_counts=feature_counts,
    )


def _distance(left: _Geometry, right: _Geometry) -> float:
    components = [
        left.shape_ratios[0] - right.shape_ratios[0],
        left.shape_ratios[1] - right.shape_ratios[1],
        math.log10(left.bbox_mm[2] / right.bbox_mm[2]),
    ]
    for left_value, right_value in (
        (left.volume_mm3, right.volume_mm3),
        (left.surface_area_mm2, right.surface_area_mm2),
        (left.faces, right.faces),
    ):
        if left_value is not None and right_value is not None:
            # A value of 1.0 is one order of magnitude apart.
            components.append(math.log10(left_value / right_value))

    if left.feature_counts is not None and right.feature_counts is not None:
        for kind in sorted(left.feature_counts.keys() | right.feature_counts.keys()):
            components.append(
                math.log1p(left.feature_counts.get(kind, 0))
                - math.log1p(right.feature_counts.get(kind, 0))
            )
    return math.sqrt(sum(value * value for value in components) / len(components))


def _shared_geometry(left: _Geometry, right: _Geometry) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = [
        {
            "name": "sorted_bounding_box_mm",
            "target": [round(value, 3) for value in left.bbox_mm],
            "candidate": [round(value, 3) for value in right.bbox_mm],
            "provenance": "MEASURED",
        },
        {
            "name": "bbox_shape_ratios",
            "target": [round(value, 6) for value in left.shape_ratios],
            "candidate": [round(value, 6) for value in right.shape_ratios],
            "provenance": "MEASURED_DERIVED",
        },
    ]
    for name, left_value, right_value in (
        ("volume_mm3", left.volume_mm3, right.volume_mm3),
        ("surface_area_mm2", left.surface_area_mm2, right.surface_area_mm2),
        ("faces", left.faces, right.faces),
    ):
        if left_value is not None and right_value is not None:
            descriptors.append(
                {
                    "name": name,
                    "target": round(left_value, 3),
                    "candidate": round(right_value, 3),
                    "provenance": "MEASURED",
                }
            )
            break
    return descriptors


def _engine_fields(result_json: object) -> dict[str, str | None]:
    result = result_json if isinstance(result_json, dict) else {}
    verdict = result.get("overall_verdict") or result.get("verdict")
    best_process = result.get("best_process")
    verdict = verdict if isinstance(verdict, str) and verdict else None
    best_process = (
        best_process if isinstance(best_process, str) and best_process else None
    )
    material = machine = None
    scores = result.get("process_scores")
    if best_process and isinstance(scores, list):
        score = next(
            (
                row
                for row in scores
                if isinstance(row, dict) and row.get("process") == best_process
            ),
            None,
        )
        if score:
            raw_material = score.get("recommended_material")
            raw_machine = score.get("recommended_machine")
            material = raw_material if isinstance(raw_material, str) else None
            machine = raw_machine if isinstance(raw_machine, str) else None
    return {
        "verdict": verdict,
        "best_process": best_process,
        "recommended_material": material,
        "recommended_machine": machine,
    }


def _isoformat(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def rank_precedents(
    target: Analysis,
    candidates: list[Analysis],
    limit: int,
    *,
    search_truncated: bool = False,
) -> dict:
    """Rank already tenant-filtered analyses; defensively re-check the boundary."""
    target_geometry = _geometry(target.result_json)
    response: dict[str, Any] = {
        "status": "available",
        "reason": None,
        "analysis_id": target.ulid,
        "authority": "ADVISORY_ONLY",
        "may_affect_deterministic_verdict": False,
        "corpus_version": CORPUS_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "analysis_version": target.analysis_version,
        "current_analysis_version": CURRENT_ANALYSIS_VERSION,
        "max_distance": MAX_GEOMETRY_DISTANCE,
        "candidate_limit": MAX_PRECEDENT_CANDIDATES,
        "candidates_examined": len(candidates),
        "search_truncated": search_truncated,
        "cases": [],
        "provenance": {
            "corpus": "ACTIVE_ORGANIZATION_SAVED_ANALYSES",
            "similarity": "DETERMINISTIC_DERIVED_FROM_MEASURED_GEOMETRY",
        },
    }
    if target_geometry is None:
        return {**response, "status": "unavailable", "reason": "target_geometry_unusable"}

    ranked: list[tuple[float, str, Analysis, _Geometry]] = []
    for candidate in candidates:
        if candidate.ulid == target.ulid or candidate.org_id != target.org_id:
            continue
        target_hash = getattr(target, "mesh_hash", None)
        candidate_hash = getattr(candidate, "mesh_hash", None)
        if target_hash and candidate_hash == target_hash:
            continue
        candidate_geometry = _geometry(candidate.result_json)
        if candidate_geometry is None:
            continue
        distance = _distance(target_geometry, candidate_geometry)
        if distance > MAX_GEOMETRY_DISTANCE:
            continue
        ranked.append(
            (
                distance,
                candidate.ulid,
                candidate,
                candidate_geometry,
            )
        )
    ranked.sort(key=lambda row: (row[0], row[1]))

    for distance, _, candidate, candidate_geometry in ranked[: max(1, min(limit, 5))]:
        response["cases"].append(
            {
                "analysis_id": candidate.ulid,
                "analysis_url": f"/analyses/{candidate.ulid}",
                "analysis_api_url": f"/api/v1/analyses/{candidate.ulid}",
                "filename": candidate.filename,
                "created_at": _isoformat(candidate.created_at),
                "distance": round(distance, 6),
                "shared_geometry": _shared_geometry(target_geometry, candidate_geometry),
                **_engine_fields(candidate.result_json),
                "analysis_version": candidate.analysis_version,
                "stale": candidate.analysis_version != CURRENT_ANALYSIS_VERSION,
                "provenance": {
                    "identity": "SAVED_ANALYSIS_METADATA",
                    "geometry": "MEASURED",
                    "similarity": "DETERMINISTIC",
                    "verdict": "ENGINE",
                    "route": "ENGINE",
                    "material": "ENGINE",
                    "machine": "ENGINE",
                    "staleness": "SAVED_ANALYSIS_METADATA",
                    "actual_outcome": "NOT_LINKED",
                },
            }
        )
    if not response["cases"]:
        response.update(
            status="no_match",
            reason=(
                "no_match_in_bounded_recent_candidates"
                if search_truncated
                else "no_usable_org_precedents"
            ),
        )
    return response


async def get_org_precedents(
    session: AsyncSession,
    org_id: str,
    analysis_ulid: str,
    limit: int = 3,
) -> dict | None:
    """Load and rank saved analyses within exactly one active organization."""
    target = (
        await session.execute(
            select(Analysis).where(
                Analysis.ulid == analysis_ulid,
                Analysis.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        return None
    candidates = (
        (
            await session.execute(
                select(Analysis).where(
                    Analysis.org_id == org_id,
                    Analysis.ulid != analysis_ulid,
                )
                .order_by(Analysis.ulid.desc())
                .limit(MAX_PRECEDENT_CANDIDATES + 1)
            )
        )
        .scalars()
        .all()
    )
    search_truncated = len(candidates) > MAX_PRECEDENT_CANDIDATES
    return rank_precedents(
        target,
        list(candidates[:MAX_PRECEDENT_CANDIDATES]),
        limit,
        search_truncated=search_truncated,
    )
