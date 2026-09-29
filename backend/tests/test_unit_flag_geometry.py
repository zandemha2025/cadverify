"""GeometryResult.unit_flag: surface the existing 1/8-inch-grid detector.

STL is unitless; an inch-authored part read as mm mis-measures every
downstream DFM value by 25.4x per axis. The costing layer already had
detect_25_4_scale_ratio; analyze_geometry now exposes it as
GeometryInfo.unit_flag so the corpus gate (and API consumers) can see it.
Detection only - geometry is never auto-rescaled.
"""
from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry

CORPUS = Path(__file__).parent / "trap-corpus"


def test_inch_cube_fixture_flagged():
    mesh = trimesh.load_mesh(CORPUS / "trap-inch-cube-25.4mm.stl")
    assert analyze_geometry(mesh).unit_flag == "suspicious_scale"


def test_fractional_inch_stock_flagged():
    # 2 x 1 x 1/2 inch plate.
    mesh = trimesh.creation.box(extents=(50.8, 25.4, 12.7))
    assert analyze_geometry(mesh).unit_flag == "suspicious_scale"


def test_ordinary_mm_parts_not_flagged():
    for dims in ((10, 10, 10), (60, 60, 5), (100, 50, 25), (80, 80, 80)):
        assert analyze_geometry(trimesh.creation.box(extents=dims)).unit_flag is None


def test_mesh_never_rescaled():
    mesh = trimesh.creation.box(extents=(25.4, 25.4, 25.4))
    g = analyze_geometry(mesh)
    span = g.bounding_box.max_x - g.bounding_box.min_x
    assert span == 25.4  # measured, not corrected
