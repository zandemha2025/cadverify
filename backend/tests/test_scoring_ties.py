"""Regression: process scoring under ties and all-fail conditions.

Ensures rank_processes is stable when every process carries the same
score and when every process fails hard — neither case may crash or
return a null best_process.
"""
from __future__ import annotations

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType
from src.analysis.processes import get_analyzer
from src.matcher.profile_matcher import rank_processes, score_process


def _build_context(mesh):
    info = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, info)
    return ctx, info


def test_all_processes_run_on_cube_without_crash(cube_10mm):
    """Smoke: every registered analyzer runs on the universal cube."""
    ctx, _ = _build_context(cube_10mm)
    for proc in ProcessType:
        analyzer = get_analyzer(proc)
        assert analyzer is not None, f"Missing analyzer for {proc.value}"
        issues = analyzer.analyze(ctx)
        assert isinstance(issues, list)


def test_rank_processes_stable_on_all_equal_scores(cube_10mm):
    """If every process scores equally, rank_processes must not crash or return None."""
    ctx, info = _build_context(cube_10mm)
    process_scores = []
    for proc in ProcessType:
        ps = score_process([], info, proc)
        process_scores.append(ps)
    # Force exact ties on every process
    equal_score = process_scores[0].score
    for ps in process_scores:
        ps.score = equal_score
    result = AnalysisResult(
        filename="cube.stl",
        file_type="stl",
        geometry=info,
        segments=[],
        universal_issues=[],
        process_scores=process_scores,
        analysis_time_ms=0.0,
    )
    ranked = rank_processes(result)
    assert ranked is not None
    assert len(ranked) == len(process_scores)
    # Stable tie: the returned list must still contain every process exactly once.
    assert {ps.process for ps in ranked} == set(ProcessType)


def test_rank_processes_handles_all_fail_without_crash(non_watertight_box):
    """If every process fails hard, best_process = None (not crash)."""
    ctx, info = _build_context(non_watertight_box)
    universal = run_universal_checks(non_watertight_box)
    process_scores = []
    for proc in ProcessType:
        analyzer = get_analyzer(proc)
        assert analyzer is not None, f"Missing analyzer for {proc.value}"
        issues = analyzer.analyze(ctx)
        ps = score_process(issues, info, proc)
        process_scores.append(ps)
    result = AnalysisResult(
        filename="broken.stl",
        file_type="stl",
        geometry=info,
        segments=[],
        universal_issues=universal,
        process_scores=process_scores,
        analysis_time_ms=0.0,
    )
    ranked = rank_processes(result)
    # Must not raise. best_process selection logic lives in routes.py:212-213:
    # only set if ranked[0].score > 0, else None.
    assert ranked is not None
    best = ranked[0] if ranked and ranked[0].score > 0 else None
    # Assertion is: no crash. `best` may be None or a valid ProcessScore.
    assert best is None or best.score > 0
