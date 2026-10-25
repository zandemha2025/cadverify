"""Decimation advice that fits the upload (M20).

A STEP upload was told to "Re-export the part with 250,000 or fewer
triangles": a STEP has no triangles; ScaleCAD made them.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import trimesh

from src.analysis.base_analyzer import decimation_issue

ASSETS = Path(__file__).parent / "assets"
_DEC = {"decimation": {"succeeded": True, "original_faces": 900000,
                       "analysis_faces": 200000, "strategy": "quadric"}}


def _ctx(source_format):
    mesh = trimesh.creation.box()
    if source_format:
        mesh.metadata["source_format"] = source_format
    return SimpleNamespace(metadata=_DEC, mesh=mesh)


def test_cad_upload_is_not_told_to_reexport_triangles():
    fix = decimation_issue(_ctx("cad")).fix_suggestion
    assert "Re-export" not in fix and "250,000" not in fix
    assert "remove detail" in fix and "on its own" in fix


def test_stl_upload_keeps_the_triangle_count_advice():
    assert decimation_issue(_ctx("stl")).fix_suggestion.startswith("Re-export the part with 250,000 or fewer triangles")


def test_unknown_source_says_what_applies_to_each():
    fix = decimation_issue(_ctx(None)).fix_suggestion
    assert "from a mesh file" in fix and "from a STEP or IGES file" in fix


def test_parsers_tag_where_the_triangles_came_from():
    from src.api import routes

    iges = ASSETS / "bored-block-mm.iges"
    mesh, _ = routes._parse_mesh(iges.read_bytes(), iges.name)
    assert mesh.metadata.get("source_format") == "cad"
    stl = trimesh.creation.box(extents=[10, 10, 10]).export(file_type="stl")
    mesh, _ = routes._parse_mesh(stl, "box.stl")
    assert mesh.metadata.get("source_format") == "stl"
