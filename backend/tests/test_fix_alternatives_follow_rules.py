"""Cross-process alternatives follow the engine's own checks (M18).

The FDM thin-wall fix said "Consider SLA (min 0.3mm) or DMLS (min 0.4mm)"
while the SLA check fails walls under 0.4 mm. Alternatives now name only the
processes whose own version of the check passed on the same part.
"""

from __future__ import annotations

from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import AnalysisResult, Issue, ProcessType, Severity
from src.analysis.processes import get_analyzer
from src.fixes.fix_suggester import enhance_suggestions
from src.matcher.profile_matcher import score_process

PT = ProcessType
TRAPS = Path(__file__).parent / "trap-corpus"


def _thin(process):
    return Issue(code="THIN_WALL", severity=Severity.ERROR, message="thin", process=process,
                 fix_suggestion="Increase wall thickness.")


def _analysis(issues_by_process):
    geometry = analyze_geometry(trimesh.creation.box(extents=[20, 20, 20]))
    scores = [score_process(issues_by_process.get(p, []), geometry, p) for p in PT]
    return AnalysisResult(filename="x.stl", file_type="stl", geometry=geometry, segments=[],
                          universal_issues=[], process_scores=scores, analysis_time_ms=0.0)


def _fix(analysis, process, code):
    (ps,) = [s for s in analysis.process_scores if s.process == process]
    return next(i.fix_suggestion for i in ps.issues if i.code == code)


def test_only_processes_that_passed_their_own_wall_check_are_named():
    analysis = enhance_suggestions(_analysis({PT.FDM: [_thin(PT.FDM)], PT.SLA: [_thin(PT.SLA)],
                                              PT.MJF: [_thin(PT.MJF)]}))
    fix = _fix(analysis, PT.FDM, "THIN_WALL")
    assert fix.endswith("\n\nAlternative: Resin printing (DLP) and Metal powder printing (DMLS) "
                        "pass their wall checks on this part.")
    assert "SLA" not in fix and "0.3" not in fix


def test_no_alternative_when_none_passes():
    every = {p: [_thin(p)] for p in (PT.FDM, PT.SLA, PT.DLP, PT.MJF, PT.DMLS)}
    fix = _fix(enhance_suggestions(_analysis(every)), PT.FDM, "THIN_WALL")
    assert "Alternative" not in fix


def test_on_a_real_0_5mm_shell_the_named_processes_really_pass():
    mesh = trimesh.load(TRAPS / "trap-wall-0.5mm-shell.stl")
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p) for p in PT]
    analysis = enhance_suggestions(AnalysisResult(filename="shell.stl", file_type="stl", geometry=geometry,
                                                  segments=[], universal_issues=[], process_scores=scores,
                                                  analysis_time_ms=0.0))
    by = {s.process: s for s in analysis.process_scores}
    fix = next(i.fix_suggestion for i in by[PT.FDM].issues if i.code == "THIN_WALL")
    alt = fix.split("Alternative: ", 1)[1] if "Alternative: " in fix else ""
    for p, acronym in ((PT.SLA, "(SLA)"), (PT.DLP, "(DLP)"), (PT.MJF, "(MJF)"), (PT.DMLS, "(DMLS)")):
        named = acronym in alt
        passed = not any(i.code == "THIN_WALL" for i in by[p].issues)
        assert named == passed, (p, alt)
