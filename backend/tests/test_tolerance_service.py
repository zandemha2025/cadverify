"""Tests for tolerance_service (11-03).

Uses mocking for AP242 parser and GD&T extractor to test orchestration
logic without requiring OCP XDE modules.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.models import ProcessType
from src.analysis.tolerance_models import (
    AchievabilityVerdict,
    ToleranceAchievability,
    ToleranceEntry,
    ToleranceReport,
    ToleranceType,
)
from src.services.tolerance_service import (
    analyze_tolerances,
    tolerance_report_to_dict,
)


@patch("src.parsers.step_ap242_parser.is_ap242_supported", return_value=False)
def test_analyze_tolerances_no_ocp(mock_supported):
    """When OCP is unavailable, return has_pmi=False with note."""
    report = analyze_tolerances(b"fake", "test.step", [ProcessType.CNC_3AXIS])
    assert report.has_pmi is False
    assert "not available" in report.pmi_note.lower()


@patch("src.parsers.gdt_extractor.extract_surface_finish", return_value=[])
@patch("src.parsers.gdt_extractor.extract_gdt", return_value=([], []))
@patch("src.parsers.step_ap242_parser.parse_ap242_from_bytes")
@patch("src.parsers.step_ap242_parser.is_ap242_supported", return_value=True)
def test_analyze_tolerances_no_pmi(mock_supported, mock_parse, mock_gdt, mock_sf):
    """When STEP has no PMI, return has_pmi=False with geometry-only note."""
    mock_doc = MagicMock()
    mock_doc.has_pmi = False
    mock_parse.return_value = mock_doc

    report = analyze_tolerances(b"fake", "test.step", [ProcessType.CNC_3AXIS])
    assert report.has_pmi is False
    assert "geometry only" in report.pmi_note.lower()


def test_tolerance_report_to_dict_structure():
    """tolerance_report_to_dict produces correct top-level structure."""
    report = ToleranceReport(
        has_pmi=True,
        pmi_note="Test note",
        tolerances=[
            ToleranceEntry(
                tolerance_id="TOL-001",
                tolerance_type=ToleranceType.FLATNESS,
                value_mm=0.05,
                datum_refs=["A"],
                feature_description="Top face",
            ),
        ],
        achievability=[
            ToleranceAchievability(
                tolerance_id="TOL-001",
                process=ProcessType.CNC_3AXIS,
                verdict=AchievabilityVerdict.ACHIEVABLE,
                process_capability_mm=0.005,
                margin_mm=0.045,
            ),
        ],
        summary_score=100.0,
    )

    d = tolerance_report_to_dict(report)
    assert d["has_pmi"] is True
    assert d["summary_score"] == 100.0
    assert d["pmi_note"] == "Test note"
    assert len(d["entries"]) == 1

    entry = d["entries"][0]
    assert entry["tolerance_id"] == "TOL-001"
    assert entry["tolerance_type"] == "flatness"
    assert entry["value_mm"] == 0.05
    assert len(entry["process_verdicts"]) == 1
    assert entry["process_verdicts"][0]["verdict"] == "achievable"


def test_summary_score_calculation():
    """4 tolerances, 3 achievable by best process -> score = 75.0."""
    from src.services.tolerance_service import _calculate_summary_score

    tolerances = [
        ToleranceEntry(tolerance_id=f"TOL-{i:03d}", tolerance_type=ToleranceType.FLATNESS, value_mm=0.1)
        for i in range(1, 5)
    ]

    achievability = [
        # CNC_3AXIS: 3 achievable, 1 not
        ToleranceAchievability("TOL-001", ProcessType.CNC_3AXIS, AchievabilityVerdict.ACHIEVABLE, 0.005, 0.095),
        ToleranceAchievability("TOL-002", ProcessType.CNC_3AXIS, AchievabilityVerdict.ACHIEVABLE, 0.005, 0.095),
        ToleranceAchievability("TOL-003", ProcessType.CNC_3AXIS, AchievabilityVerdict.ACHIEVABLE, 0.005, 0.095),
        ToleranceAchievability("TOL-004", ProcessType.CNC_3AXIS, AchievabilityVerdict.NOT_ACHIEVABLE, 0.005, -0.005),
        # FDM: 1 achievable
        ToleranceAchievability("TOL-001", ProcessType.FDM, AchievabilityVerdict.ACHIEVABLE, 0.15, -0.05),
        ToleranceAchievability("TOL-002", ProcessType.FDM, AchievabilityVerdict.NOT_ACHIEVABLE, 0.15, -0.05),
        ToleranceAchievability("TOL-003", ProcessType.FDM, AchievabilityVerdict.NOT_ACHIEVABLE, 0.15, -0.05),
        ToleranceAchievability("TOL-004", ProcessType.FDM, AchievabilityVerdict.NOT_ACHIEVABLE, 0.15, -0.05),
    ]

    score = _calculate_summary_score(
        tolerances,
        achievability,
        [ProcessType.CNC_3AXIS, ProcessType.FDM],
    )
    assert score == 75.0


def test_tolerance_report_to_dict_empty_report():
    """Empty report serializes cleanly."""
    report = ToleranceReport(has_pmi=False, pmi_note="No PMI")
    d = tolerance_report_to_dict(report)
    assert d["has_pmi"] is False
    assert d["entries"] == []
    assert d["summary_score"] == 0.0
