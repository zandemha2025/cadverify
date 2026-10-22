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


# ── W7: sheet metal says can't for plate, bar, block and tube ────────────────
@pytest.mark.parametrize("part,code", [
    ("cube30", "TOO_THICK_SHEET"),
    ("cylinder", "TOO_THICK_SHEET"),
    ("tube", "TOO_THICK_SHEET"),
    ("pocketed_block", "NOT_SHEET_STOCK"),
])
def test_sheet_metal_refuses_parts_that_are_not_sheet(part, code):
    if part == "cube30":
        mesh = _box((30, 30, 30))
    elif part == "cylinder":
        mesh = trimesh.creation.cylinder(radius=10, height=60, sections=128)
    elif part == "tube":
        mesh = trimesh.creation.annulus(r_min=15, r_max=20, height=80, sections=128)
    else:
        mesh = _diff(_box((80, 60, 30)), _box((60, 40, 25), at=(10, 10, 10)))
    ctx = _ctx(_stl(mesh))
    issue = next(i for i in _issues(ctx, "sheet_metal") if i.code == code)
    assert issue.severity == Severity.ERROR
    assert _verdict(ctx, "sheet_metal") == "fail"


@pytest.mark.parametrize("part", ["plate", "lbracket"])
def test_sheet_parts_are_not_refused(part):
    mesh = _box((100, 60, 3)) if part == "plate" else _union(_box((40, 30, 3)), _box((3, 30, 40)))
    ctx = _ctx(_stl(mesh))
    codes = _codes(ctx, "sheet_metal")
    assert not {"TOO_THICK_SHEET", "NOT_SHEET_STOCK", "TOO_THIN_SHEET"} & codes
    assert _verdict(ctx, "sheet_metal") != "fail"


# ── M10: FDM leaves a sealed void empty; powder and resin trap material ──────
def test_fdm_needs_no_drain_for_a_sealed_void_but_resin_and_powder_do():
    ctx = _ctx(_stl(_sealed_cube()))
    fdm = _codes(ctx, "fdm")
    assert "TRAPPED_VOLUME" not in fdm
    assert "SEALED_VOID_SUPPORT" in fdm  # its flat ceiling needs support that stays sealed in
    for process in ("sla", "sls", "mjf", "dmls"):
        assert "TRAPPED_VOLUME" in _codes(ctx, process), process


# ── M4 / M5: a binary STL cube is a clean pass, as its exact twin is ─────────
@pytest.mark.parametrize("offset", [(0, 0, 0), (1234.5, -567.8, 250.0)])
def test_a_binary_stl_cube_reads_like_the_exact_cube(offset):
    exact = _box((10, 10, 10), at=offset)
    stl = _stl(exact)
    assert stl.metadata["coordinate_error"] > 0
    for mesh in (exact, stl):
        ctx = _ctx(mesh)
        assert "SETUP_ACCESS_UNVERIFIED" not in _codes(ctx, "cnc_3axis")
        assert "WALL_THICKNESS_PRECISION" not in _codes(ctx, "fdm")
        assert _verdict(ctx, "fdm") == "pass"
        assert _verdict(ctx, "cnc_3axis") == "pass"


def test_a_wall_on_the_limit_still_says_the_file_cannot_settle_it():
    # FDM's wall floor is 0.6 mm (1.5x a 0.4 mm nozzle; audit W2).
    ctx = _ctx(_stl(_box((60, 40, 0.6), at=(100, 200, 300))))
    issue = next(i for i in _issues(ctx, "fdm") if i.code == "WALL_THICKNESS_PRECISION")
    assert issue.severity == Severity.WARNING
    assert issue.required_value == 0.6 and abs(issue.measured_value - 0.6) < 1e-3


# ── M7 / C10: build-direction aspect and real ribs ───────────────────────────
@pytest.mark.parametrize("process", ["fdm", "sls", "mjf"])
def test_a_flat_plate_is_not_tall_and_thin(process):
    flat = _ctx(_stl(_box((100, 60, 3))))
    assert "EXTREME_ASPECT_RATIO" not in _codes(flat, process)
    standing = _ctx(_stl(_box((3, 60, 100))))  # the same plate stood on its edge
    assert "EXTREME_ASPECT_RATIO" in _codes(standing, process)


def test_a_flat_plate_has_no_rib_and_a_cylinder_gets_no_rib_guidance():
    plate = _ctx(_stl(_box((100, 60, 3))))
    assert "HIGH_RIB_RATIO" not in _codes(plate, "forging")
    assert plate.ribs == []
    cylinder = _ctx(_stl(trimesh.creation.cylinder(radius=10, height=60, sections=256)))
    assert cylinder.info.face_count > 200
    assert "RIB_RULES_CHECK" not in _codes(cylinder, "injection_molding")


def test_a_real_rib_is_measured_and_judged():
    base = _box((100, 60, 4), at=(-50, -30, 0))
    rib = _box((60, 2, 20), at=(-30, -1, 4))
    ctx = _ctx(_stl(_union(base, rib)))
    (found,) = ctx.ribs
    assert found["thickness_mm"] == pytest.approx(2.0, abs=1e-3)
    assert found["height_mm"] == pytest.approx(20.0, abs=1e-3)
    assert found["base_thickness_mm"] == pytest.approx(4.0, abs=1e-3)
    forging = next(i for i in _issues(ctx, "forging") if i.code == "HIGH_RIB_RATIO")
    assert forging.measured_value == pytest.approx(10.0, abs=1e-2)
    molding = next(i for i in _issues(ctx, "injection_molding") if i.code == "RIB_RULES_CHECK")
    assert "20mm tall" in molding.message


def test_a_faceted_shaft_has_no_ribs():
    """Opposite facet strips of a tessellated cylinder face each other across it: slivers, not plates."""
    parts = [trimesh.creation.cylinder(radius=r, height=h, sections=256) for r, h in ((15, 30), (10, 40), (5, 20))]
    z = 0.0
    for p, (_r, h) in zip(parts, ((15, 30), (10, 40), (5, 20))):
        p.apply_translation((0, 0, z + h / 2))
        z += h
    ctx = _ctx(_stl(_union(*parts)))
    assert ctx.ribs == []
    assert "RIB_RULES_CHECK" not in _codes(ctx, "injection_molding")


def test_fins_on_a_heat_sink_are_ribs_and_the_gaps_between_them_are_not_plates():
    base = _box((100, 60, 4))
    fins = [_box((1.5, 60, 20), at=(5 + i * 6, 0, 4)) for i in range(15)]
    ctx = _ctx(_stl(_union(base, *fins)))
    assert len(ctx.ribs) == 15
    assert {round(r["thickness_mm"], 3) for r in ctx.ribs} == {1.5}
    assert {round(r["height_mm"], 3) for r in ctx.ribs} == {20.0}


# ── M11: the pull direction a check assumed, and a turned re-check ──────────
def test_a_turned_recheck_uses_that_orientation_for_the_pull_and_says_so():
    from src.analysis.orientation import Orientation, rotation_down

    # A cup with 3-degree drafted walls, drawn lying on its side: its walls
    # run along the file's X axis, its opening facing +X.
    outer = trimesh.creation.cone(radius=30, height=400, sections=128)
    outer = _diff(outer, _box((200, 200, 400), at=(-100, -100, 40)))  # a 40 mm frustum
    inner = outer.copy()
    inner.apply_scale(0.8)
    inner.apply_translation((0, 0, 8.01))
    cup = _diff(outer, inner)
    side = cup.copy()
    side.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 1, 0)))
    as_drawn = _issues(_ctx(side), "injection_molding")
    draft = next(i for i in as_drawn if i.code == "INSUFFICIENT_DRAFT")
    assert "the file's +Z" in draft.message
    # Re-check with the file's -X side down (+X up): the tool now opens along the walls.
    turned = Orientation.of(rotation_down([-1.0, 0.0, 0.0])).apply(side)
    after = _issues(_ctx(turned), "injection_molding")
    assert "INSUFFICIENT_DRAFT" not in {i.code for i in after}
    undercut = [i for i in after if i.code == "UNDERCUT_MOLDING"]
    assert all("the file's +X" in i.message for i in undercut)


# ── M16: moving or mirroring a part changes no finding ───────────────────────
def test_mirroring_a_wedge_reads_the_same_walls():
    wedge = trimesh.creation.extrude_polygon(
        __import__("shapely.geometry", fromlist=["Polygon"]).Polygon([(0, 0), (30, 0), (30, 4), (0, 2)]), 20)
    mirrored = wedge.copy()
    mirrored.apply_transform(np.diag([-1.0, 1.0, 1.0, 1.0]))
    a, b = _ctx(_stl(wedge)), _ctx(_stl(mirrored))
    assert np.min(a.wall_thickness) == pytest.approx(np.min(b.wall_thickness), abs=1e-4)
    for process in ("injection_molding", "waam", "fdm"):
        assert _codes(a, process) == _codes(b, process), process


def test_moving_a_stepped_shaft_keeps_its_uneven_walls_finding():
    parts = [trimesh.creation.cylinder(radius=r, height=h, sections=256) for r, h in ((15, 30), (10, 40), (5, 20))]
    z = 0.0
    for p, (_r, h) in zip(parts, ((15, 30), (10, 40), (5, 20))):
        p.apply_translation((0, 0, z + h / 2))
        z += h
    shaft = _union(*parts)
    moved = shaft.copy()
    moved.apply_translation((1234.5, -567.8, 250.0))
    a, b = _ctx(_stl(shaft)), _ctx(_stl(moved))
    for process in ("injection_molding", "die_casting", "sand_casting"):
        assert ("NON_UNIFORM_WALLS" in _codes(a, process)) == ("NON_UNIFORM_WALLS" in _codes(b, process)), process
