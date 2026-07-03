"""Findings-API deepening — serialization/plumbing tests.

Covers the five real fixes so the Inspection experience binds to richer data:
  1. Untruncated affected_faces (analyzer 100-clip + API 20-clip both killed).
  2. Structured citations (cite strings -> Citation object; analyzer standards
     bibliography serialized).
  3. Opt-in per-face wall-thickness map.
  4. Cost-side DFM blockers re-linked to their structured Issues.
  5. Honest whole-part scope for unlocalizable findings.

DFM verdict logic is untouched — these assert serialization only.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.base_analyzer import (
    analyze_geometry,
    check_degenerate_faces,
    run_universal_checks,
)
from src.analysis.citations import parse_citation
from src.analysis.context import GeometryContext
from src.analysis.models import (
    AnalysisResult,
    Citation,
    Issue,
    ProcessType,
    Severity,
)
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
from src.analysis.processes.checks import check_wall_thickness
from src.analysis.serialization import (
    MAX_SERIALIZED_AFFECTED_FACES,
    serialize_citation,
    serialize_issue,
    serialize_wall_thickness,
)
import src.analysis.processes  # noqa: F401  populate registry
from src.matcher.profile_matcher import rank_processes, score_process


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _ctx(mesh):
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    from src.analysis.features import detect_all
    ctx.features = detect_all(ctx.mesh)
    return info, ctx


def _thin_plate(subdivisions: int = 3) -> trimesh.Trimesh:
    """A 0.4mm plate, finely tessellated so thin faces exceed the old 100 clip."""
    m = trimesh.creation.box(extents=[60.0, 60.0, 0.4])
    for _ in range(subdivisions):
        m = m.subdivide()
    return m


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    scores = [
        score_process(get_analyzer(p).analyze(ctx), geometry, p)
        for p in pbase._REGISTRY if get_analyzer(p)
    ]
    result = AnalysisResult(
        filename="part.stl", file_type="stl", geometry=geometry,
        segments=ctx.segments, universal_issues=run_universal_checks(mesh),
        process_scores=scores,
    )
    rank_processes(result)
    return result, mesh, ctx


# ──────────────────────────────────────────────────────────────
# Item 1 — untruncated affected faces
# ──────────────────────────────────────────────────────────────
def test_analyzer_no_longer_clips_affected_faces_at_100():
    """The analyzer-side thin_faces[:100] clip is gone — the Issue carries all."""
    _, ctx = _ctx(_thin_plate())
    issues = check_wall_thickness(ctx, 0.8, ProcessType.FDM, cite="Stratasys DFM §3.")
    tw = issues[0]
    assert tw.code == "THIN_WALL"
    # Fine plate has hundreds of thin faces; the old code capped this at 100.
    assert len(tw.affected_faces) > 100


def test_degenerate_faces_universal_check_reports_true_count_not_clipped():
    """base_analyzer.check_degenerate_faces must carry the TRUE affected-face
    count into the Issue — the sibling universal-check path used to pre-clip the
    list to 100, so serialize_issue reported 100 for a 150-degenerate part and
    never flagged the drop (silently wrong). Now the full list rides through."""
    box = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
    # 150 zero-area faces (each references two identical vertices -> area 0).
    degen = np.array([[0, 0, 1]] * 150)
    faces = np.vstack([box.faces, degen])
    mesh = trimesh.Trimesh(vertices=box.vertices, faces=faces, process=False)

    issue = next(i for i in check_degenerate_faces(mesh) if i.code == "DEGENERATE_FACES")
    assert "150 degenerate" in issue.message
    assert len(issue.affected_faces) == 150            # NOT pre-clipped to 100

    d = serialize_issue(issue)
    assert d["affected_face_count"] == 150             # honest total, not 100
    assert len(d["affected_faces_sample"]) == 150      # 150 < cap -> full sample
    assert "affected_faces_truncated" not in d         # nothing silently dropped


def test_serialize_issue_reports_true_count_and_full_sample_under_cap():
    faces = list(range(150))  # > old 20/100 clips, < serialization cap
    issue = Issue(code="THIN_WALL", severity=Severity.ERROR, message="m",
                  process=ProcessType.FDM, affected_faces=faces)
    d = serialize_issue(issue)
    assert d["affected_face_count"] == 150            # true total, not clipped
    assert d["affected_faces_sample"] == faces        # full list under the cap
    assert "affected_faces_truncated" not in d        # nothing dropped


def test_serialize_issue_caps_huge_lists_but_never_lies_about_count():
    n = MAX_SERIALIZED_AFFECTED_FACES + 777
    issue = Issue(code="OVERHANG", severity=Severity.WARNING, message="m",
                  process=ProcessType.FDM, affected_faces=list(range(n)))
    d = serialize_issue(issue)
    assert d["affected_face_count"] == n                       # honest total
    assert len(d["affected_faces_sample"]) == MAX_SERIALIZED_AFFECTED_FACES
    assert d["affected_faces_truncated"] is True              # flagged, not silent


def test_api_issue_dict_carries_untruncated_sample():
    """routes._issue_to_dict delegates to serialize_issue — no 20-face clip."""
    from src.api.routes import _issue_to_dict

    issue = Issue(code="THIN_WALL", severity=Severity.ERROR, message="m",
                  process=ProcessType.FDM, affected_faces=list(range(300)))
    d = _issue_to_dict(issue)
    assert d["affected_face_count"] == 300
    assert len(d["affected_faces_sample"]) == 300


# ──────────────────────────────────────────────────────────────
# Item 2 — structured citations
# ──────────────────────────────────────────────────────────────
def test_parse_citation_colon_split_with_clause():
    c = parse_citation("NADCA §3: 1° min external, 2° internal.")
    assert c.standard == "NADCA"
    assert c.clause == "§3"
    assert c.text == "1° min external, 2° internal."
    assert c.rule_id is None


def test_parse_citation_plain_colon():
    c = parse_citation("DIN 6935: radius >= thickness.")
    assert c.standard == "DIN 6935"
    assert c.clause is None
    assert c.text == "radius >= thickness."


def test_parse_citation_bare_identifier_is_standard():
    c = parse_citation("Sodick ALC600G.")
    assert c.standard == "Sodick ALC600G"
    assert c.text is None


def test_parse_citation_sentence_never_fabricates_standard():
    """An advisory sentence with no source must NOT be mislabelled as a standard."""
    c = parse_citation("Wire EDM cuts a 2D profile extruded in Z.")
    assert c.standard is None
    assert c.text == "Wire EDM cuts a 2D profile extruded in Z."


def test_parse_citation_colon_descriptor_never_fabricates_standard():
    """The colon-split path must NOT promote a process/material/geometry
    descriptor to `standard`. The left side of a "STANDARD: detail" split only
    becomes `standard` when it reads as a real citation source; a descriptor
    keeps the WHOLE cite as honest free text (standard=None)."""
    offenders = [
        "3-axis: tool access from +Z only.",
        "Forging: no undercuts — die cannot open.",
        "Green part: 1mm min wall; 0.8mm post-sinter.",
        "Metal powder: 5mm+ drain holes.",
        "Multi-axis DED: 60° threshold.",
        "Multi-axis WAAM: 60° practical limit.",
    ]
    for cite in offenders:
        c = parse_citation(cite)
        assert c is not None
        assert c.standard is None, f"fabricated standard for {cite!r}: {c.standard!r}"
        # The descriptor text is preserved as free text, not discarded.
        left = cite.split(":", 1)[0]
        assert c.text and c.text.startswith(left), f"{cite!r} -> text {c.text!r}"


def test_parse_citation_colon_real_standard_still_parses():
    """A genuine standards spec / vendor guide left side still yields `standard`."""
    c = parse_citation("ASME Y14.5-2018: GD&T datum callouts.")
    assert c.standard == "ASME Y14.5-2018"
    assert c.text == "GD&T datum callouts."
    # A vendor source carrying descriptive lowercase words survives too (the
    # descriptor guard is targeted, not a blanket lowercase reject).
    c2 = parse_citation("EOS Ti/Inconel data sheets: 0.4mm min.")
    assert c2.standard == "EOS Ti/Inconel data sheets"
    assert c2.text == "0.4mm min."


def test_parse_citation_empty_is_none():
    assert parse_citation("") is None
    assert parse_citation(None) is None
    assert parse_citation("   ") is None


def test_serialize_citation_drops_null_fields():
    assert serialize_citation(Citation(standard="DIN 6935", text="r>=t")) == {
        "standard": "DIN 6935", "text": "r>=t",
    }
    assert serialize_citation(None) is None
    assert serialize_citation(Citation()) is None  # all-empty -> no object


def test_analyzer_issue_serializes_structured_citation():
    _, ctx = _ctx(_thin_plate(subdivisions=1))
    issues = check_wall_thickness(ctx, 0.8, ProcessType.FDM,
                                  cite="Formlabs Form 4: 0.3mm min.")
    d = serialize_issue(issues[0])
    assert d["citation"]["standard"] == "Formlabs Form 4"
    assert d["citation"]["text"] == "0.3mm min."


def test_to_response_serializes_analyzer_standards_bibliography():
    """The analyzer standards list — declared but previously never serialized."""
    from src.api.routes import _to_response

    result, mesh, _ = _analyze(trimesh.creation.box(extents=[40.0, 30.0, 25.0]))
    resp = _to_response(result)
    assert resp["process_scores"], "expected scored processes"
    for ps in resp["process_scores"]:
        assert "standards" in ps
        assert isinstance(ps["standards"], list)
    fdm = next((p for p in resp["process_scores"] if p["process"] == "fdm"), None)
    assert fdm is not None and len(fdm["standards"]) > 0


# ──────────────────────────────────────────────────────────────
# Item 3 — opt-in wall-thickness map
# ──────────────────────────────────────────────────────────────
def test_serialize_wall_thickness_inf_becomes_null():
    wt = serialize_wall_thickness(np.array([1.5, np.inf, 2.25, np.nan]))
    assert wt["n_faces"] == 4
    assert wt["units"] == "mm"
    assert wt["values"] == [1.5, None, 2.25, None]


def test_serialize_wall_thickness_echoes_decimation():
    wt = serialize_wall_thickness(
        np.array([1.0, 2.0]),
        decimation={"succeeded": True, "original_faces": 900000, "analysis_faces": 2},
    )
    assert wt["decimated"] is True
    assert wt["original_faces"] == 900000


def test_to_response_thickness_map_is_opt_in():
    from src.api.routes import _to_response

    result, mesh, ctx = _analyze(_thin_plate(subdivisions=1))
    # Default: lean, no map.
    assert "wall_thickness_map" not in _to_response(result)
    # Opt-in: map present, aligned to the analyzed mesh face count.
    resp = _to_response(result, wall_thickness=ctx.wall_thickness)
    assert "wall_thickness_map" in resp
    assert resp["wall_thickness_map"]["n_faces"] == len(ctx.wall_thickness)


# ──────────────────────────────────────────────────────────────
# Item 4 — cost-side DFM blockers re-linked to their Issues
# ──────────────────────────────────────────────────────────────
def test_cost_estimate_carries_structured_blocker_details():
    """A box fails injection-molding draft; the estimate must carry the FULL
    serialized blocker Issue (faces/region/citation), not just its message."""
    from src.costing import EstimateOptions, estimate_decision

    result, mesh, ctx = _analyze(trimesh.creation.box(extents=[40.0, 30.0, 25.0]))
    report = estimate_decision(
        result, mesh, ctx.features, EstimateOptions(quantities=[100])
    )

    blocked = [e for e in report.estimates if e["dfm_blockers"]]
    assert blocked, "expected at least one DFM-blocked estimate for a draftless box"

    for e in blocked:
        details = e["dfm_blocker_details"]
        # Parallel arrays: one structured detail per message, same order.
        assert len(details) == len(e["dfm_blockers"])
        for msg, det in zip(e["dfm_blockers"], details):
            assert det["message"] == msg
            assert det["severity"] == "error"
            assert "scope" in det

    # The draft blocker is localizable — prove we carry the geometry, not text.
    draft = None
    for e in blocked:
        for det in e["dfm_blocker_details"]:
            if det["code"] == "INSUFFICIENT_DRAFT":
                draft = det
    assert draft is not None
    assert draft["scope"] == "localized"
    assert len(draft["affected_faces_sample"]) > 0
    assert draft["citation"]["standard"]  # structured standard rode through


def test_cost_dfm_blockers_strings_unchanged_for_legacy_consumers():
    """dfm_blockers stays a list[str] (decision.py / report.py depend on it)."""
    from src.costing import EstimateOptions, estimate_decision

    result, mesh, ctx = _analyze(trimesh.creation.box(extents=[40.0, 30.0, 25.0]))
    report = estimate_decision(
        result, mesh, ctx.features, EstimateOptions(quantities=[100])
    )
    for e in report.estimates:
        assert all(isinstance(b, str) for b in e["dfm_blockers"])


# ──────────────────────────────────────────────────────────────
# Item 5 — honest scope for unlocalizable findings
# ──────────────────────────────────────────────────────────────
def test_scope_localized_when_faces_or_region_present():
    assert serialize_issue(Issue(
        code="THIN_WALL", severity=Severity.ERROR, message="m",
        process=ProcessType.FDM, affected_faces=[1, 2, 3],
    ))["scope"] == "localized"
    assert serialize_issue(Issue(
        code="TRAPPED_VOLUME", severity=Severity.ERROR, message="m",
        process=ProcessType.SLA, region_center=(1.0, 2.0, 3.0),
    ))["scope"] == "localized"


def test_scope_whole_part_for_unlocalizable_findings():
    """DECIMATED_MESH et al. have neither faces nor a region — never fake one."""
    d = serialize_issue(Issue(
        code="DECIMATED_MESH", severity=Severity.WARNING,
        message="Analyzed on a decimated mesh.", process=None,
    ))
    assert d["scope"] == "whole_part"
    assert "affected_faces_sample" not in d
    assert "region_center" not in d


def test_with_thickness_never_mutates_the_persisted_dict():
    """The opt-in map is attached to a COPY, so the persisted/cached result_dict
    (built before attach) stays lean — the no-bloat guarantee for the hot path."""
    from src.services.analysis_service import _with_thickness

    persisted = {"filename": "p.stl", "process_scores": []}
    thickness = {"n_faces": 3, "units": "mm", "values": [1.0, None, 2.0]}

    returned = _with_thickness(persisted, thickness)
    assert returned is not persisted                     # separate object
    assert "wall_thickness_map" not in persisted         # persisted stays lean
    assert returned["wall_thickness_map"] == thickness

    # No map requested -> passthrough, untouched.
    assert _with_thickness(persisted, None) is persisted


def test_run_analysis_accepts_include_thickness_kwarg():
    """The opt-in flag is threaded through the service entry point."""
    import inspect

    from src.services.analysis_service import run_analysis

    params = inspect.signature(run_analysis).parameters
    assert "include_thickness" in params
    assert params["include_thickness"].default is False  # default = lean/off


def test_decimation_issue_serializes_as_whole_part():
    """The real DECIMATED_MESH issue path is honestly whole-part scoped."""
    from src.analysis.base_analyzer import decimation_issue

    class _Ctx:
        metadata = {"decimation": {"succeeded": True, "original_faces": 900000,
                                   "analysis_faces": 200000, "strategy": "quadric"}}

    issue = decimation_issue(_Ctx())
    assert issue is not None and issue.code == "DECIMATED_MESH"
    assert serialize_issue(issue)["scope"] == "whole_part"
