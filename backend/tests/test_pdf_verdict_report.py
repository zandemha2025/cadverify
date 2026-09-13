"""Coverage for the DFM verdict PDF report (analysis PDF).

Contract under test: the PDF mirrors the on-screen verdict using the persisted
analysis record only - overall verdict, issue summary grouped by severity with
measured evidence, location refs, recommended actions and citations, declared
source-unit provenance, limits section, and build identity. Unknown fields are
omitted, never invented.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.services import pdf_service
from src.services.pdf_service import (
    PDF_TEMPLATE_VERSION,
    _render_pdf_sync,
    _safe_filename,
    build_pdf_context,
)


def _analysis(**overrides):
    base = SimpleNamespace(
        ulid="01TESTPDFVERDICT000000000",
        filename="bracket & housing.step",
        file_type="step",
        verdict="fail",
        face_count=12844,
        duration_ms=2310.0,
        created_at=datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc),
        analysis_version="1.2.3",
        mesh_hash="b" * 64,
        result_json={
            "overall_verdict": "fail",
            "best_process": "cnc_3axis",
            "universal_issues": [
                {
                    "code": "NON_MANIFOLD",
                    "severity": "error",
                    "message": "Mesh has 3 non-manifold edges",
                    "fix_suggestion": "Repair the mesh and re-upload",
                    "measured_value": 3,
                    "scope": "whole_part",
                }
            ],
            "process_scores": [
                {
                    "process": "cnc_3axis",
                    "score": 62,
                    "verdict": "issues",
                    "recommended_material": "6061-T6",
                    "recommended_machine": "3-axis mill",
                    "issues": [
                        {
                            "code": "INTERNAL_CORNER_RADIUS",
                            "severity": "warning",
                            "message": "Internal corner radius below tool minimum",
                            "fix_suggestion": "Increase internal radii to at least 1.0 mm",
                            "measured_value": 0.5,
                            "required_value": 1.0,
                            "region_center": [12.5, -3.0, 8.25],
                            "affected_face_count": 214,
                            "scope": "localized",
                            "citation": {
                                "standard": "Internal tooling guide",
                                "clause": "§4.2",
                                "text": "Smallest end mill determines internal radius.",
                            },
                        }
                    ],
                }
            ],
            "geometry": {
                "volume_mm3": 8042.1,
                "surface_area_mm2": 3310.5,
                "bounding_box_mm": [40.0, 25.0, 12.0],
                "vertices": 6400,
                "faces": 12844,
                "is_watertight": True,
                "is_manifold": False,
            },
            "source_units": {
                "declared": "in",
                "scale_to_mm": 25.4,
                "provenance": "USER",
            },
        },
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_context_uses_persisted_record_only():
    ctx = build_pdf_context(_analysis())
    assert ctx["analysis_id"] == "01TESTPDFVERDICT000000000"
    assert ctx["overall_verdict"] == "fail"
    assert ctx["best_process"] == "cnc_3axis"
    assert ctx["analysis_version"] == "1.2.3"
    assert ctx["mesh_hash"] == "b" * 12
    assert ctx["source_units"]["declared"] == "in"


def test_context_falls_back_to_column_verdict_and_omits_unknowns():
    a = _analysis()
    a.result_json = {}
    ctx = build_pdf_context(a)
    assert ctx["overall_verdict"] == "fail"  # column fallback, not invented
    assert ctx["best_process"] is None
    assert ctx["source_units"] is None


def _render_html(analysis) -> str:
    template = pdf_service._jinja_env.get_template("analysis_report.html")
    return template.render(**build_pdf_context(analysis))


def test_html_mirrors_verdict_and_issue_detail():
    html = _render_html(_analysis())
    # Header + verdict + identity
    assert "DFM Verdict Report" in html
    assert "bracket &amp; housing.step" in html  # escaped, not injected
    assert "01TESTPDFVERDICT000000000" in html
    assert "FAIL" in html
    assert "Recommended route: cnc_3axis" in html
    # Severity grouping
    assert "Errors (1)" in html
    assert "Warnings (1)" in html
    # Issue detail: code, finding, measured evidence, location, action, citation
    assert "NON_MANIFOLD" in html
    assert "Applies to the whole part." in html
    assert "INTERNAL_CORNER_RADIUS" in html
    assert "measured 0.5 &middot; required 1.0" in html
    assert "Region center (12.5, -3.0, 8.25) mm." in html
    assert "214 affected faces." in html
    assert "Increase internal radii to at least 1.0 mm" in html
    assert "Internal tooling guide" in html and "§4.2" in html
    # Declared material/process context + provenance + limits + build identity
    assert "6061-T6" in html
    assert "Declared source units: in" in html
    assert "Limits and Provenance" in html
    assert "analysis engine 1.2.3" in html
    assert "mesh bbbbbbbbbbbb" in html


def test_html_omits_absent_fields():
    a = _analysis()
    a.result_json = {
        "overall_verdict": "pass",
        "universal_issues": [],
        "process_scores": [],
        "geometry": {},
    }
    html = _render_html(a)
    assert "No issues found." in html
    assert "Source Units" not in html
    assert "Recommended route" not in html


def test_generated_pdf_text_extracts(tmp_path):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        pytest.skip("pdftotext is required for PDF text-extraction coverage")

    pdf_path = tmp_path / "verdict.pdf"
    pdf_path.write_bytes(_render_pdf_sync(build_pdf_context(_analysis())))
    text = subprocess.run(
        [pdftotext, str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    for expected in (
        "DFM Verdict Report",
        "NON_MANIFOLD",
        "INTERNAL_CORNER_RADIUS",
        "6061-T6",
        "Limits and Provenance",
        "01TESTPDFVERDICT000000000",
    ):
        assert expected in text, f"missing in extracted PDF text: {expected}"


def test_cache_key_versions_template():
    assert PDF_TEMPLATE_VERSION == "v2"
    assert "v2" in PDF_TEMPLATE_VERSION


def test_safe_filename_contract():
    assert _safe_filename("bracket & housing.step") == "bracket___housing-dfm-report.pdf"
    assert _safe_filename("") == "analysis-dfm-report.pdf"
    assert _safe_filename("part.step") == "part-dfm-report.pdf"
