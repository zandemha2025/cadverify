"""ASCII STL files meet the triangle cap before trimesh reads them.

trimesh's ASCII reader decodes, lowercases and splits the whole file in
memory, so a file whose facet count is over the cap is refused from a cheap
count of its ``vertex`` keywords (three per facet, any letter case) before any
of that work starts.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.upload_validation import enforce_stl_triangle_count_cap
from src.parsers import stl_parser


def ascii_stl(facets: int, *, keyword: str = "vertex", pad: int = 0) -> bytes:
    lines = ["solid part"]
    for i in range(facets):
        lines += [
            "facet normal 0 0 1" + " " * pad,
            "outer loop",
            f"{keyword} {i} 0 0",
            f"{keyword} {i + 1} 0 0",
            f"{keyword} {i} 1 0",
            "endloop",
            "endfacet",
        ]
    lines.append("endsolid part")
    return ("\n".join(lines) + "\n").encode()


def test_ascii_facet_count_matches_vertex_keywords():
    assert stl_parser.ascii_stl_facet_count(ascii_stl(7)) == 7


def test_ascii_facet_count_ignores_letter_case():
    assert stl_parser.ascii_stl_facet_count(ascii_stl(5, keyword="VERTEX")) == 5
    assert stl_parser.ascii_stl_facet_count(ascii_stl(4, keyword="Vertex")) == 4


def test_ascii_facet_count_sees_keyword_split_across_scan_windows(monkeypatch):
    data = ascii_stl(40, pad=3)
    for window in (5, 7, 11, 64):
        monkeypatch.setattr(stl_parser, "_ASCII_SCAN_CHUNK", window)
        assert stl_parser.ascii_stl_facet_count(data) == 40


def test_ascii_stl_over_cap_is_refused_before_trimesh_parses(monkeypatch):
    monkeypatch.setenv("MAX_TRIANGLES", "10")

    def _must_not_parse(*_a, **_k):
        raise AssertionError("trimesh parsed an ASCII STL that was over the cap")

    monkeypatch.setattr(stl_parser.trimesh, "load", _must_not_parse)
    from src.api import routes

    with pytest.raises(HTTPException) as exc:
        routes._raw_tessellate_in_thread(ascii_stl(11), ".stl", "big.stl")
    assert exc.value.status_code == 400
    assert "11" in exc.value.detail and "MAX_TRIANGLES" in exc.value.detail


def test_ascii_stl_over_demo_cap_is_refused_with_demo_status():
    with pytest.raises(HTTPException) as exc:
        enforce_stl_triangle_count_cap(
            ascii_stl(11), limit=10, limit_name="DEMO_MAX_TRIANGLES",
            status_code=413, subject="Public demo STL",
        )
    assert exc.value.status_code == 413


def test_ascii_stl_at_cap_still_parses(monkeypatch):
    monkeypatch.setenv("MAX_TRIANGLES", "10")
    from src.api import routes

    mesh = routes._raw_tessellate_in_thread(ascii_stl(10), ".stl", "ok.stl")
    assert len(mesh.faces) == 10
