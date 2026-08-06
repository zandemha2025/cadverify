"""Focused regression for the History -> analysis detail browser contract."""
from datetime import datetime, timezone
from types import SimpleNamespace

from src.api.history import (
    _serialize_analysis_detail,
    _serialize_analysis_summary,
)


def _analysis():
    return SimpleNamespace(
        ulid="01ANALYSIS",
        org_id="org-history",
        mesh_hash="mesh-history",
        filename="cube.step",
        file_type="step",
        verdict="issues",
        face_count=120,
        duration_ms=42.5,
        created_at=datetime(2026, 7, 13, 1, 2, 3, tzinfo=timezone.utc),
        result_json={
            "filename": "cube.step",
            "file_type": "step",
            "overall_verdict": "issues",
            "best_process": "cnc_3axis",
            "geometry": {"bounding_box_mm": [20, 15, 10]},
            "universal_issues": [{"code": "U1"}],
            "process_scores": [{"process": "cnc_3axis", "issues": []}],
        },
        is_public=False,
        share_short_id=None,
    )


def _decision():
    return SimpleNamespace(
        ulid="01DECISION",
        filename="cube.step",
        make_now_process="cnc_3axis",
        approval_status="unreviewed",
        created_at=datetime(2026, 7, 13, 1, 3, 4, tzinfo=timezone.utc),
    )


def test_history_summary_matches_fields_consumed_by_browser_table():
    row = _serialize_analysis_summary(_analysis())

    assert row["id"] == row["ulid"] == "01ANALYSIS"
    assert row["verdict"] == row["overall_verdict"] == "issues"
    assert row["duration_ms"] == row["analysis_time_ms"] == 42.5
    assert row["process_count"] == 1


def test_analysis_detail_preserves_result_and_links_exact_cost_decision():
    detail = _serialize_analysis_detail(_analysis(), [_decision()])

    assert detail["id"] == detail["ulid"] == "01ANALYSIS"
    assert detail["result"] == detail["result_json"]
    assert detail["result_json"]["geometry"]["bounding_box_mm"] == [20, 15, 10]
    assert detail["decision_links"] == [
        {
            "id": "01DECISION",
            "url": "/cost-decisions/01DECISION",
            "filename": "cube.step",
            "make_now_process": "cnc_3axis",
            "approval_status": "unreviewed",
            "created_at": "2026-07-13T01:03:04+00:00",
        }
    ]
