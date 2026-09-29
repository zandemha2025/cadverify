"""MJF analyzer behavior on the v3 MJF coverage fixtures.

Thresholds from the registered analyzer (additive/mjf.py), citing
HP MJF Design Guide v5.0: 0.5mm min wall, 0.2mm min feature,
380x284x380 build volume (Jet Fusion 5200), 5mm drain for enclosed
cavities, repo-generic 10:1 aspect ratio.
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.processes.additive.mjf import MJFAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"


def _issues(name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return {i.code: i for i in MJFAnalyzer().analyze(ctx)}


def test_sub_min_feature_rib_trips_small_features():
    issues = _issues("trap-mjf-rib-0p1mm.stl")
    assert issues["SMALL_FEATURES"].measured_value == pytest.approx(0.1, abs=0.01)
    assert "THIN_WALL" in issues  # 0.094mm rib < 0.5mm min wall


def test_oversized_bar_trips_build_volume():
    issues = _issues("trap-mjf-build-400mm.stl")
    assert "EXCEEDS_BUILD_VOLUME" in issues  # 400mm > 380mm envelope


def test_12to1_rod_trips_aspect_warning_only():
    issues = _issues("trap-mjf-rod-12to1.stl")
    assert list(issues) == ["EXTREME_ASPECT_RATIO"]
    assert issues["EXTREME_ASPECT_RATIO"].measured_value == pytest.approx(12.0)


def test_0p3mm_rib_clears_feature_but_not_wall():
    issues = _issues("trap-single-0p3mm-rib-among-many.stl")
    assert "SMALL_FEATURES" not in issues  # 0.286 > 0.2 min feature
    assert "THIN_WALL" in issues          # 0.286 < 0.5 min wall


def test_clean_cube_passes_all_mjf_checks():
    assert _issues("control-cube-60mm.stl") == {}
