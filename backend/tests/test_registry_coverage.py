"""Regression: registry covers all ProcessType values; constants are centralized."""
from __future__ import annotations

import pytest

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer


def test_registry_covers_every_process_type():
    """CORE-03: every ProcessType resolves to a registered analyzer."""
    missing = [p.value for p in ProcessType if get_analyzer(p) is None]
    assert not missing, f"Processes without registry entry: {missing}"


def test_constants_module_is_single_source(cube_10mm):
    """CORE-04: additive_analyzer imports MIN_WALL_THICKNESS from constants."""
    import src.analysis.additive_analyzer as aa
    import src.analysis.constants as c
    assert aa.MIN_WALL_THICKNESS is c.MIN_WALL_THICKNESS, (
        "additive_analyzer.MIN_WALL_THICKNESS must be the same object as "
        "constants.MIN_WALL_THICKNESS (imported, not redefined)"
    )


def test_registry_dispatch_on_cube_produces_scores(cube_10mm):
    """Smoke: every analyzer runs on the universal cube without raising."""
    info = analyze_geometry(cube_10mm)
    ctx = GeometryContext.build(cube_10mm, info)
    for proc in ProcessType:
        analyzer = get_analyzer(proc)
        assert analyzer is not None, f"No analyzer for {proc.value}"
        issues = analyzer.analyze(ctx)  # must not raise
        assert isinstance(issues, list)
