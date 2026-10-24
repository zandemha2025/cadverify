"""Ground-truth part lookups stay inside the trusted parts directory.

``resolve_part_path`` turns a record's ``part_id`` (and an optional relative
``part_path``) into a mesh file the cost engine opens. Both names are
network-supplied on the ingest/import paths, so the lookup is confined to the
configured parts directory: an absolute name, a ``..`` escape or a symlink out
of the directory never resolves, and with no parts directory configured a
relative name resolves to nothing (never to the server's working directory).
"""
from __future__ import annotations

import os

import pytest

from src.costing.groundtruth import GroundTruthRecord, resolve_part_path


def _rec(part_id: str, part_path: str | None = None) -> GroundTruthRecord:
    return GroundTruthRecord(
        part_id=part_id, process="sls", quantity=10,
        actual_unit_cost_usd=12.5, part_path=part_path,
    )


@pytest.fixture()
def layout(tmp_path):
    parts = tmp_path / "parts"
    (parts / "sub").mkdir(parents=True)
    (parts / "a.stl").write_text("solid a\nendsolid a\n")
    (parts / "sub" / "b.stl").write_text("solid b\nendsolid b\n")
    outside = tmp_path / "outside.stl"
    outside.write_text("solid o\nendsolid o\n")
    return parts, outside


def test_part_id_absolute_path_outside_parts_dir_does_not_resolve(layout):
    parts, outside = layout
    assert resolve_part_path(_rec(str(outside)), str(parts)) is None


def test_part_id_absolute_path_without_extension_does_not_resolve(layout):
    parts, outside = layout
    assert resolve_part_path(_rec(str(outside)[: -len(".stl")]), str(parts)) is None


def test_part_id_dotdot_escape_does_not_resolve(layout):
    parts, _ = layout
    assert resolve_part_path(_rec("../outside.stl"), str(parts)) is None
    assert resolve_part_path(_rec("../outside"), str(parts)) is None
    assert resolve_part_path(_rec("sub/../../outside.stl"), str(parts)) is None


def test_part_id_symlink_out_of_parts_dir_does_not_resolve(layout):
    parts, outside = layout
    os.symlink(outside, parts / "link.stl")
    assert resolve_part_path(_rec("link.stl"), str(parts)) is None


def test_part_id_with_nul_byte_does_not_resolve(layout):
    parts, _ = layout
    assert resolve_part_path(_rec("a.stl\x00x"), str(parts)) is None


def test_relative_part_path_never_resolves_against_working_directory(layout, monkeypatch):
    parts, outside = layout
    monkeypatch.chdir(outside.parent)
    assert resolve_part_path(_rec("x", part_path="outside.stl"), None) is None
    assert resolve_part_path(_rec("outside.stl"), None) is None
    assert resolve_part_path(_rec("parts/a.stl"), None) is None


# ── the allowed paths keep working ──────────────────────────────────────────
def test_part_id_inside_parts_dir_resolves(layout):
    parts, _ = layout
    got = resolve_part_path(_rec("a.stl"), str(parts))
    assert got is not None and os.path.samefile(got, parts / "a.stl")


def test_part_id_in_subdirectory_resolves_with_implied_extension(layout):
    parts, _ = layout
    got = resolve_part_path(_rec("sub/b"), str(parts))
    assert got is not None and os.path.samefile(got, parts / "sub" / "b.stl")


def test_relative_part_path_inside_parts_dir_resolves(layout):
    parts, _ = layout
    got = resolve_part_path(_rec("unrelated-id", part_path="sub/b.stl"), str(parts))
    assert got is not None and os.path.samefile(got, parts / "sub" / "b.stl")


def test_trusted_absolute_part_path_from_in_process_caller_resolves(layout):
    # Offline evaluation and the recalibration step that has already resolved
    # a record hand the engine an absolute path built by the server itself.
    parts, outside = layout
    assert resolve_part_path(_rec("x", part_path=str(outside)), str(parts)) == str(outside)
    assert resolve_part_path(_rec("x", part_path=str(outside)), None) == str(outside)
