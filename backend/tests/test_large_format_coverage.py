"""Binder jetting / DED / WAAM analyzer behavior on v3 coverage fixtures.

Thresholds from the registered analyzers: binder_jetting (ExOne S-Max
Pro / Desktop Metal: 1.0mm wall, 0.5mm feature, 800x500x400), DED
(ASTM F3187: 1.5mm wall, 60deg overhang, 1500^3), WAAM (AWS D1.1 /
Lincoln: 2.0mm wall, 60deg overhang, 5000x3000x3000). All three emit
always-on near-net INFO issues (sintering shrinkage / machining stock).
"""
from pathlib import Path

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all as detect_features
from src.analysis.processes.additive.binder_jetting import BinderJettingAnalyzer
from src.analysis.processes.additive.ded import DEDAnalyzer
from src.analysis.processes.additive.waam import WAAMAnalyzer

CORPUS = Path(__file__).parent / "corpus-v3"
ANALYZERS = {"bj": BinderJettingAnalyzer(), "ded": DEDAnalyzer(), "waam": WAAMAnalyzer()}


def _codes(analyzer, name: str):
    mesh = trimesh.load_mesh(CORPUS / name)
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_features(ctx.mesh)
    return {i.code: i for i in ANALYZERS[analyzer].analyze(ctx)}


def test_wall_threshold_ladder_on_2mm_plate():
    assert "THIN_WALL" not in _codes("bj", "control-plate-2mm-flat.stl")   # 1.0 min
    assert "THIN_WALL" not in _codes("ded", "control-plate-2mm-flat.stl")  # 1.5 min
    assert "THIN_WALL" in _codes("waam", "control-plate-2mm-flat.stl")     # 2.0 min


def test_sintering_and_machining_info_always_on():
    assert "SINTERING_SHRINKAGE" in _codes("bj", "control-cube-60mm.stl")
    assert "MACHINING_ALLOWANCE" in _codes("ded", "control-cube-60mm.stl")
    assert "MACHINING_ALLOWANCE" in _codes("waam", "control-cube-60mm.stl")


def test_ded_envelope_boundary():
    assert "EXCEEDS_BUILD_VOLUME" in _codes("ded", "trap-ded-build-1600mm.stl")
    assert "EXCEEDS_BUILD_VOLUME" not in _codes("waam", "trap-ded-build-1600mm.stl")


def test_overhang_60deg_boundary():
    assert "OVERHANG" in _codes("ded", "trap-sla-overhang-10deg-from-horizontal.stl")
    assert "OVERHANG" not in _codes("ded", "control-sla-overhang-80deg-from-horizontal.stl")


def test_binder_jetting_feature_min():
    issues = _codes("bj", "trap-plate-0p2mm-foil.stl")
    assert issues["THIN_WALL"].measured_value == pytest.approx(0.193, abs=0.001)
    assert "SMALL_FEATURES" in issues  # 0.2 < 0.5 Desktop Metal feature min


def test_waam_wall_on_formed_channel():
    issues = _codes("waam", "trap-uchannel-2mm-formed.stl")
    assert issues["THIN_WALL"].measured_value == pytest.approx(1.994, abs=0.01)
