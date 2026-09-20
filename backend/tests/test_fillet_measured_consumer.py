"""check_fillet_requirements: measured path via fitted concave fillet radii.

Detected internal fillets carry fitted radii (features/fillets.py). A
fillet measurably below min_fillet_mm trips MISSING_FILLETS with the
fitted radius as measured_value. Parts with adequate fillets or only
fully-sharp corners keep the original qualitative issue (no
measured_value - no fabricated precision).
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.processes.formative.die_casting import DieCastingAnalyzer
from src.analysis.processes.formative.forging import ForgingAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _mf(analyzer, name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return [i for i in analyzer.analyze(ctx) if i.code == "MISSING_FILLETS"]


def test_undersized_r1_fillets_trip_with_measured_radius():
    (issue,) = _mf(ForgingAnalyzer(), "trap-pocket-undersized-r1-fillets.stl")
    assert issue.measured_value == pytest.approx(1.0, abs=1e-3)  # fitted, not nominal
    assert issue.required_value == 3.0
    assert issue.severity.value == "warning"


def test_adequate_r4_fillets_produce_no_measured_trip():
    # r4 >= 3.0 min: the pocket's sharp mouth rims may still fire the
    # qualitative path, but never with a measured_value.
    for issue in _mf(ForgingAnalyzer(), "control-pocket-r4-fillets.stl"):
        assert issue.measured_value is None


def test_fillet_exactly_at_die_casting_minimum_clears():
    # Fitted 1.0000005mm vs 1.0mm min: not below, so no measured trip.
    for issue in _mf(DieCastingAnalyzer(), "trap-pocket-undersized-r1-fillets.stl"):
        assert issue.measured_value is None


def test_sharp_only_corners_stay_qualitative():
    (issue,) = _mf(ForgingAnalyzer(), "trap-pocket-grid-16-sharp-corners.stl")
    assert issue.measured_value is None  # sharp edges have no fittable radius


def test_cylinder_hole_is_not_a_measured_fillet():
    for issue in _mf(ForgingAnalyzer(), "control-hole-8mmx16mm.stl"):
        assert issue.measured_value is None


def test_convex_part_emits_nothing():
    assert _mf(ForgingAnalyzer(), "control-cube-60mm.stl") == []
