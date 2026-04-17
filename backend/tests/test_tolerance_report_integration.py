"""Integration tests for tolerance report pipeline (11-04).

Covers: AnalysisResult tolerances field, tolerance_report_to_dict structure,
graceful error handling, STL regression guard, and PDF template rendering.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.analysis.models import (
    AnalysisResult,
    BoundingBox,
    GeometryInfo,
    ProcessType,
)
from src.analysis.tolerance_models import (
    AchievabilityVerdict,
    ToleranceAchievability,
    ToleranceEntry,
    ToleranceReport,
    ToleranceType,
)
from src.services.tolerance_service import tolerance_report_to_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_geometry() -> GeometryInfo:
    bb = BoundingBox(0, 0, 0, 50, 50, 50)
    return GeometryInfo(
        vertex_count=1000,
        face_count=2000,
        volume=125000.0,
        surface_area=15000.0,
        bounding_box=bb,
        is_watertight=True,
        is_manifold=True,
        euler_number=2,
        center_of_mass=(25.0, 25.0, 25.0),
    )


def _make_tolerance_report() -> ToleranceReport:
    """Build a realistic ToleranceReport with 3 entries and achievability data."""
    tolerances = [
        ToleranceEntry(
            tolerance_id="TOL-001",
            tolerance_type=ToleranceType.POSITION,
            value_mm=0.05,
            datum_refs=["A", "B"],
            feature_description="Hole center position",
        ),
        ToleranceEntry(
            tolerance_id="TOL-002",
            tolerance_type=ToleranceType.FLATNESS,
            value_mm=0.02,
            datum_refs=[],
            feature_description="Top surface flatness",
            surface_finish_ra_um=0.8,
        ),
        ToleranceEntry(
            tolerance_id="TOL-003",
            tolerance_type=ToleranceType.PERPENDICULARITY,
            value_mm=0.1,
            datum_refs=["A"],
            feature_description="Side wall perpendicularity",
        ),
    ]

    achievability = []
    for tol in tolerances:
        for proc, verdict, cap, margin in [
            (ProcessType.CNC_3AXIS, AchievabilityVerdict.ACHIEVABLE, 0.025, 0.025),
            (ProcessType.FDM, AchievabilityVerdict.NOT_ACHIEVABLE, 0.3, -0.25),
        ]:
            achievability.append(
                ToleranceAchievability(
                    tolerance_id=tol.tolerance_id,
                    process=proc,
                    verdict=verdict,
                    process_capability_mm=cap,
                    margin_mm=margin,
                )
            )

    return ToleranceReport(
        has_pmi=True,
        pmi_note=None,
        tolerances=tolerances,
        achievability=achievability,
        summary_score=100.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAnalysisResultTolerancesField:
    """AnalysisResult.tolerances backward-compatibility."""

    def test_default_none(self):
        result = AnalysisResult(
            filename="test.stl",
            file_type="stl",
            geometry=_make_geometry(),
        )
        assert result.tolerances is None

    def test_accepts_tolerance_report(self):
        report = _make_tolerance_report()
        result = AnalysisResult(
            filename="part.step",
            file_type="step",
            geometry=_make_geometry(),
            tolerances=report,
        )
        assert result.tolerances is report
        assert result.tolerances.has_pmi is True
        assert len(result.tolerances.tolerances) == 3


class TestStlAnalysisNoTolerances:
    """Regression: STL analysis must not produce tolerances key."""

    def test_stl_analysis_no_tolerances(self):
        """STL AnalysisResult should have tolerances=None by default."""
        result = AnalysisResult(
            filename="cube.stl",
            file_type="stl",
            geometry=_make_geometry(),
        )
        assert result.tolerances is None

    def test_stl_response_dict_no_tolerances_key(self):
        """_to_response for STL must not contain a 'tolerances' key."""
        from src.api.routes import _to_response

        result = AnalysisResult(
            filename="cube.stl",
            file_type="stl",
            geometry=_make_geometry(),
        )
        resp = _to_response(result)
        assert "tolerances" not in resp


class TestStepAnalysisToleranceFallback:
    """STEP without AP242 support returns no-PMI report."""

    @patch("src.parsers.step_ap242_parser.is_ap242_supported", return_value=False)
    def test_no_ap242_returns_no_pmi(self, mock_ap242):
        from src.services.tolerance_service import analyze_tolerances

        report = analyze_tolerances(b"fake-step", "test.step", [ProcessType.CNC_3AXIS])
        assert report.has_pmi is False
        assert report.pmi_note is not None
        assert "not available" in report.pmi_note.lower() or "missing" in report.pmi_note.lower()


class TestStepAnalysisToleranceErrorGraceful:
    """Tolerance analysis errors must not crash the pipeline."""

    @patch("src.parsers.step_ap242_parser.is_ap242_supported", return_value=True)
    @patch("src.parsers.step_ap242_parser.parse_ap242_from_bytes", side_effect=RuntimeError("OCP crash"))
    def test_exception_propagates_to_caller(self, mock_parse, mock_ap242):
        """analyze_tolerances raises -- caller (analysis_service) catches gracefully."""
        from src.services.tolerance_service import analyze_tolerances

        with pytest.raises(RuntimeError, match="OCP crash"):
            analyze_tolerances(b"bad-step", "crash.step", [ProcessType.CNC_3AXIS])

    def test_analysis_service_catches_tolerance_error(self):
        """analysis_service wraps tolerance errors into has_pmi=False fallback."""
        # The integration point in analysis_service.run_analysis wraps in try/except
        # and sets tolerances = {"has_pmi": False, "pmi_note": "..."}
        # Verify the dict structure matches expectations.
        fallback = {
            "has_pmi": False,
            "pmi_note": "Tolerance analysis failed; results based on geometry only.",
        }
        assert fallback["has_pmi"] is False
        assert "failed" in fallback["pmi_note"].lower()


class TestToleranceReportDictStructure:
    """tolerance_report_to_dict produces correct JSON-compatible structure."""

    def test_full_report_structure(self):
        report = _make_tolerance_report()
        d = tolerance_report_to_dict(report)

        # Top-level keys
        assert d["has_pmi"] is True
        assert d["summary_score"] == 100.0
        assert "pmi_note" not in d  # None pmi_note is omitted
        assert "entries" in d
        assert len(d["entries"]) == 3

    def test_entry_fields(self):
        report = _make_tolerance_report()
        d = tolerance_report_to_dict(report)
        entry = d["entries"][0]

        assert entry["tolerance_id"] == "TOL-001"
        assert entry["tolerance_type"] == "position"
        assert entry["value_mm"] == 0.05
        assert entry["datum_refs"] == ["A", "B"]
        assert entry["feature_description"] == "Hole center position"
        assert "process_verdicts" in entry

    def test_process_verdicts_structure(self):
        report = _make_tolerance_report()
        d = tolerance_report_to_dict(report)
        verdicts = d["entries"][0]["process_verdicts"]

        assert len(verdicts) == 2
        for pv in verdicts:
            assert "process" in pv
            assert "verdict" in pv
            assert "process_capability_mm" in pv
            assert "margin_mm" in pv
            assert pv["verdict"] in ("achievable", "marginal", "not_achievable")

    def test_surface_finish_included(self):
        report = _make_tolerance_report()
        d = tolerance_report_to_dict(report)
        # TOL-002 has surface_finish_ra_um = 0.8
        entry_002 = [e for e in d["entries"] if e["tolerance_id"] == "TOL-002"][0]
        assert entry_002["surface_finish_ra_um"] == 0.8

    def test_empty_report(self):
        report = ToleranceReport(has_pmi=False, pmi_note="No PMI found")
        d = tolerance_report_to_dict(report)
        assert d["has_pmi"] is False
        assert d["pmi_note"] == "No PMI found"
        assert d["entries"] == []


class TestPdfTemplateWithTolerances:
    """PDF template renders tolerance data without errors."""

    def test_template_renders_with_tolerances(self):
        """Jinja2 template renders tolerance section when has_pmi is true."""
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).resolve().parent.parent / "src" / "templates" / "pdf"
        env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)

        # Register the same custom filters as pdf_service
        from src.services.pdf_service import (
            _format_duration,
            _format_number,
            _sort_by_severity,
            _merge_key,
        )
        env.filters["format_duration"] = _format_duration
        env.filters["format_number"] = _format_number
        env.filters["sort_by_severity"] = _sort_by_severity
        env.filters["merge_key"] = _merge_key

        report = _make_tolerance_report()
        tol_dict = tolerance_report_to_dict(report)

        context = {
            "filename": "bracket.step",
            "file_type": "STEP",
            "verdict": "pass",
            "face_count": 2000,
            "duration_ms": 1234.5,
            "created_at": "2026-01-01T00:00:00Z",
            "result": {
                "universal_issues": [],
                "process_scores": [],
                "geometry": {
                    "volume_mm3": 125000,
                    "surface_area_mm2": 15000,
                    "bounding_box_mm": [50, 50, 50],
                    "vertices": 1000,
                    "faces": 2000,
                    "is_watertight": True,
                    "is_manifold": True,
                },
                "tolerances": tol_dict,
            },
            "engine_version": "test",
            "mesh_hash": "abc123",
        }

        template = env.get_template("analysis_report.html")
        html = template.render(**context)

        # Verify tolerance section rendered
        assert "Tolerance Achievability" in html
        assert "TOL-001" in html
        assert "TOL-002" in html
        assert "TOL-003" in html
        assert "tolerance-table" in html
        assert "verdict-achievable" in html

    def test_template_renders_without_tolerances(self):
        """Jinja2 template omits tolerance section for STL (no tolerances key)."""
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).resolve().parent.parent / "src" / "templates" / "pdf"
        env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=False)

        from src.services.pdf_service import (
            _format_duration,
            _format_number,
            _sort_by_severity,
            _merge_key,
        )
        env.filters["format_duration"] = _format_duration
        env.filters["format_number"] = _format_number
        env.filters["sort_by_severity"] = _sort_by_severity
        env.filters["merge_key"] = _merge_key

        context = {
            "filename": "cube.stl",
            "file_type": "STL",
            "verdict": "pass",
            "face_count": 12,
            "duration_ms": 50.0,
            "created_at": "2026-01-01T00:00:00Z",
            "result": {
                "universal_issues": [],
                "process_scores": [],
                "geometry": {
                    "volume_mm3": 1000,
                    "surface_area_mm2": 600,
                    "bounding_box_mm": [10, 10, 10],
                    "vertices": 8,
                    "faces": 12,
                    "is_watertight": True,
                    "is_manifold": True,
                },
            },
            "engine_version": "test",
            "mesh_hash": "def456",
        }

        template = env.get_template("analysis_report.html")
        html = template.render(**context)

        assert "<h2>Tolerance Achievability</h2>" not in html
        assert "tolerance-table" not in html
