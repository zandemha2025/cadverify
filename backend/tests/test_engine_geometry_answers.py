"""Geometry answers the engine audit found wrong (round 6).

Each test states the physical fact and checks the engine's own analyzers on a
known part: sealed voids, blind cavities and wire EDM, sheet stock, STL vs STEP
agreement, wall-precision caveats, build-direction aspect, real ribs, resin
cups, the pull direction a check assumed, and moving or mirroring a part.
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType, Severity
from src.analysis.processes import get_analyzer
from src.matcher.profile_matcher import score_process
from src.parsers.stl_parser import parse_stl_from_bytes


def _box(ext, at=(0.0, 0.0, 0.0)):
    m = trimesh.creation.box(extents=ext)
    m.apply_translation(np.asarray(at, float) + np.asarray(ext, float) / 2.0)
    return m


def _diff(a, *b):
    return trimesh.boolean.difference([a, *b], engine="manifold")


def _union(*m):
    return trimesh.boolean.union(list(m), engine="manifold")


def _sealed_cube():
    """40 mm cube with a sealed 20 mm cubic void: one solid, two shells."""
    inner = _box((20, 20, 20), at=(10, 10, 10))
    inner.invert()
    return trimesh.util.concatenate([_box((40, 40, 40)), inner])


def _stl(mesh):
    """The bytes an upload carries: binary STL, float32 coordinates."""
    return parse_stl_from_bytes(mesh.export(file_type="stl"))


def _ctx(mesh):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = detect_all(ctx.mesh)
    return ctx


def _issues(ctx, process):
    return get_analyzer(ProcessType(process)).analyze(ctx)


def _codes(ctx, process):
    return {i.code for i in _issues(ctx, process)}


def _verdict(ctx, process):
    return score_process(_issues(ctx, process), ctx.info, ProcessType(process)).verdict


# ── W16: a solid with a sealed void is one body ──────────────────────────────
def test_a_sealed_void_is_part_of_one_body_not_a_second_body():
    codes = {i.code for i in run_universal_checks(_sealed_cube())}
    assert "MULTIPLE_BODIES" not in codes


def test_two_separate_solids_and_an_island_in_a_void_are_still_separate_bodies():
    apart = trimesh.util.concatenate([_box((10, 10, 10)), _box((10, 10, 10), at=(30, 0, 0))])
    issue = next(i for i in run_universal_checks(apart) if i.code == "MULTIPLE_BODIES")
    assert "2 disconnected bodies" in issue.message
    island = trimesh.util.concatenate([_sealed_cube(), _box((4, 4, 4), at=(18, 18, 18))])
    issue = next(i for i in run_universal_checks(island) if i.code == "MULTIPLE_BODIES")
    assert "2 disconnected bodies" in issue.message


# ── W6 / W8: no cutter or wire reaches a sealed void; no wire cuts a blind floor ─
@pytest.mark.parametrize("process", ["cnc_3axis", "cnc_5axis", "cnc_turning", "wire_edm"])
@pytest.mark.parametrize("fmt", ["exact", "stl"])
def test_machining_cannot_reach_a_sealed_void(process, fmt):
    mesh = _sealed_cube() if fmt == "exact" else _stl(_sealed_cube())
    ctx = _ctx(mesh)
    issue = next(i for i in _issues(ctx, process) if i.code == "SEALED_VOID_NO_ACCESS")
    assert issue.severity == Severity.ERROR
    assert _verdict(ctx, process) == "fail"


def test_a_plain_block_has_no_sealed_void():
    ctx = _ctx(_box((30, 30, 30)))
    assert "SEALED_VOID_NO_ACCESS" not in _codes(ctx, "cnc_3axis")


@pytest.mark.parametrize("part", ["cup", "blind_hole", "pocket"])
def test_a_wire_cannot_cut_the_floor_of_a_closed_bottom_cavity(part):
    if part == "cup":  # 40 x 40 x 30 open-top box, 0.5 mm walls and floor
        mesh = _diff(_box((40, 40, 30)), _box((39, 39, 30), at=(0.5, 0.5, 0.5)))
    elif part == "blind_hole":
        hole = trimesh.creation.cylinder(radius=0.5, height=31, sections=64)
        hole.apply_translation((5, 5, 5 + 15.5))
        mesh = _diff(_box((10, 10, 35)), hole)
    else:
        mesh = _diff(_box((80, 60, 30)), _box((60, 40, 25), at=(10, 10, 10)))
    ctx = _ctx(_stl(mesh))
    assert "WIRE_CANNOT_REACH" in _codes(ctx, "wire_edm")
    assert _verdict(ctx, "wire_edm") == "fail"


@pytest.mark.parametrize("part", ["through_hole", "through_pocket", "plate"])
def test_through_profiles_stay_wire_cuttable(part):
    if part == "through_hole":
        hole = trimesh.creation.cylinder(radius=0.5, height=32, sections=64)
        hole.apply_translation((5, 5, 15))
        mesh = _diff(_box((10, 10, 30)), hole)
    elif part == "through_pocket":
        mesh = _diff(_box((80, 60, 20)), _box((40, 20, 22), at=(20, 20, -1)))
    else:
        mesh = _box((100, 60, 3))
    ctx = _ctx(_stl(mesh))
    assert "WIRE_CANNOT_REACH" not in _codes(ctx, "wire_edm")
    assert _verdict(ctx, "wire_edm") != "fail"


# ── M10: FDM leaves a sealed void empty; powder and resin trap material ──────
def test_fdm_needs_no_drain_for_a_sealed_void_but_resin_and_powder_do():
    ctx = _ctx(_stl(_sealed_cube()))
    fdm = _codes(ctx, "fdm")
    assert "TRAPPED_VOLUME" not in fdm
    assert "SEALED_VOID_SUPPORT" in fdm  # its flat ceiling needs support that stays sealed in
    for process in ("sla", "sls", "mjf", "dmls"):
        assert "TRAPPED_VOLUME" in _codes(ctx, process), process


