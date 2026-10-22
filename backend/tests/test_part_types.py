"""What a file holds: one solid, separate bodies, a weldment or an assembly.

Generated cases (tests/part_type_cases.py), each read through the production STL
parser, then described (src.analysis.part_types) and checked body by body
(src.services.body_check_service). Each must read correctly, and one-solid files
must read exactly as before.
"""
from __future__ import annotations

import json

import pytest
import trimesh

from tests import part_type_cases as cases


def _mesh(data: bytes, name: str = "part.stl"):
    from src.api.routes import _parse_mesh

    mesh, _suffix = _parse_mesh(data, name)
    return mesh


def _describe(data: bytes):
    from src.analysis.part_types import describe

    out = describe(_mesh(data))
    json.dumps(out)  # the block travels in the check's JSON
    return out


def _codes(data: bytes) -> dict:
    from src.analysis.base_analyzer import run_universal_checks

    return {i.code: i for i in run_universal_checks(_mesh(data))}


# ── one solid: nothing changes ──────────────────────────────────────────────


def test_a_single_solid_is_one_body_and_reads_fast():
    from src.analysis.part_types import describe

    out = describe(_mesh(cases.cube()), single_detail=False)
    assert out == {"version": 1, "kind": "single_solid", "body_count": 1, "shells": 1, "all_closed": True,
                   "summary": "One solid body."}
    assert "MULTIPLE_BODIES" not in _codes(cases.cube()) and "BODIES_SHARE_EDGES" not in _codes(cases.cube())


def test_a_solid_with_a_sealed_void_is_still_one_body():
    out = _describe(cases.cube_with_void())
    assert out["kind"] == "single_solid_with_voids" and out["body_count"] == 1
    assert out["summary"] == "One solid with 1 sealed internal void."
    assert "MULTIPLE_BODIES" not in _codes(cases.cube_with_void())


def test_one_bent_sheet_is_one_body_not_a_weldment():
    out = _describe(cases.l_bracket_bent())
    assert out["kind"] == "single_solid" and out["body_count"] == 1
    codes = _codes(cases.l_bracket_bent())
    assert "MULTIPLE_BODIES" not in codes and "NON_WATERTIGHT" not in codes


# ── several bodies ──────────────────────────────────────────────────────────


def test_two_separate_cubes():
    out = _describe(cases.two_cubes())
    assert out["kind"] == "separate_bodies" and out["body_count"] == 2
    assert out["summary"] == "This file holds 2 separate bodies that don't touch: 2 identical blocks."
    a, b = out["bodies"]
    assert a["volume_mm3"] == pytest.approx(27000) and b["volume_mm3"] == pytest.approx(27000)
    assert a["design"] == b["design"] and b["same_as"] == 1 and a["copies"] == 2
    assert a["shape"] == "Block 30 × 30 × 30 mm"
    assert out["contacts"] == []
    # each body's faces, for the 3D view: together they are the whole file, once
    faces = sorted(f for body in out["bodies"] for s, e in body["faces"] for f in range(s, e))
    assert faces == list(range(24))
    assert "2 disconnected bodies" in _codes(cases.two_cubes())["MULTIPLE_BODIES"].message


def test_a_cube_in_its_fixture_is_an_assembly_not_a_weldment():
    out = _describe(cases.cube_with_fixture())
    assert out["kind"] == "assembly"
    assert "likely an assembly, or a part with its fixture" in out["summary"]
    (contact,) = out["contacts"]
    assert contact["type"] == "touching" and not contact["weld_like"]
    # the cube sits on the pocket floor: a 40 x 40 seat, not a weld line
    assert contact["patch_mm"][1] == pytest.approx(40, abs=2)
    shapes = {b["volume_mm3"]: b["shape"] for b in out["bodies"]}
    assert shapes[64000.0] == "Block 40 × 40 × 40 mm"
    assert shapes[174360.0].startswith("Shaped part 120 × 80 × 20")


def test_a_welded_frame_of_four_tubes():
    out = _describe(cases.welded_frame())
    assert out["kind"] == "weldment" and out["body_count"] == 4
    assert out["summary"] == "This file holds 4 separate bodies: likely a welded frame of 4 tubes."
    assert out["bodies_share_edges"] is True and out["all_closed"] is True
    shapes = sorted(b["shape"] for b in out["bodies"])
    assert shapes == ["Square tube 40 × 40 × 3 mm, 320 mm long"] * 2 + ["Square tube 40 × 40 × 3 mm, 600 mm long"] * 2
    stock = out["bodies"][0]["stock"]
    assert stock["kind"] == "rect_tube" and stock["wall_mm"] == pytest.approx(3, abs=0.1)
    assert out["designs"] == 2
    joints = out["joints"]
    assert joints["count"] == 4
    # each butt joint is a 40 x 40 tube end: about 160 mm all round, labelled an estimate
    assert 4 * 140 <= joints["weld_length_mm_estimate"] <= 4 * 170
    assert "an estimate" in joints["words"]
    assert all(c["ring"] and c["weld_like"] for c in out["contacts"])
    assert out["route"] == ["cut", "prep", "weld", "finish"]


def test_closed_bodies_that_share_edges_are_not_an_open_shell():
    codes = _codes(cases.welded_frame())
    assert "NON_WATERTIGHT" not in codes, "nothing is open: the members share edges where they touch"
    issue = codes["BODIES_SHARE_EDGES"]
    assert issue.severity.value == "error"
    assert issue.message.startswith("The file holds 4 closed bodies that share edges")
    assert "4 disconnected bodies" in codes["MULTIPLE_BODIES"].message


def test_a_t_joint_of_two_plates():
    out = _describe(cases.t_joint())
    assert out["kind"] == "weldment"
    assert out["summary"] == "This file holds 2 separate bodies: likely a welded fabrication of 2 plates."
    assert {b["shape"] for b in out["bodies"]} == {"Plate 10 mm thick, 200 × 100 mm"}
    assert out["joints"]["count"] == 1
    assert 400 <= out["joints"]["weld_length_mm_estimate"] <= 440


def test_an_l_bracket_of_two_welded_plates():
    out = _describe(cases.l_bracket_welded())
    assert out["kind"] == "weldment" and out["body_count"] == 2
    assert out["summary"] == "This file holds 2 separate bodies: likely a welded fabrication of 2 sheets."
    assert sorted(b["shape"] for b in out["bodies"]) == ["Sheet 5 mm thick, 100 × 55 mm", "Sheet 5 mm thick, 100 × 60 mm"]
    (contact,) = out["contacts"]
    assert contact["patch_mm"][0] == pytest.approx(100, abs=2)
    codes = _codes(cases.l_bracket_welded())
    assert "BODIES_SHARE_EDGES" in codes and "NON_WATERTIGHT" not in codes


def test_stock_shapes_read_from_cross_sections():
    from src.analysis.part_types import stock_of

    rod = trimesh.creation.cylinder(radius=10, height=300, sections=64)
    s = stock_of(rod, rod.volume)
    assert s["kind"] == "round_bar" and s["od_mm"] == pytest.approx(20, abs=0.2)
    pipe = trimesh.creation.annulus(r_min=21, r_max=24, height=500, sections=64)
    s = stock_of(pipe, pipe.volume)
    assert s["kind"] == "round_tube" and s["wall_mm"] == pytest.approx(3, abs=0.2)
    angle = cases.box([0, 0, 0], [50, 5, 600]).union(cases.box([0, 0, 0], [5, 50, 600]))
    s = stock_of(angle, angle.volume)
    assert s["kind"] == "angle" and s["words"].startswith("Angle 50 × 50 × 5")
    flat = cases.box([0, 0, 0], [50, 10, 500])
    assert stock_of(flat, flat.volume)["kind"] == "flat_bar"
    assert stock_of(cases.bent_l(), cases.bent_l().volume) is None, "a bent sheet isn't flat stock"


# ── body by body ────────────────────────────────────────────────────────────


def test_separate_bodies_are_priced_body_by_body_never_as_one_block():
    from src.services.body_check_service import check_bodies_sync

    r = check_bodies_sync(_mesh(cases.two_cubes()), filename="two.stl", quantities=[1, 100])
    json.dumps(r)
    (design,) = r["designs"]
    assert design["bodies"] == [1, 2] and design["copies"] == 2 and design["status"] == "ok"
    one = design["by_quantity"]["1"]
    # at 1 file there are 2 of this body to make
    assert one["quantity_each"] == 2 and one["per_file_usd"] == pytest.approx(2 * one["unit_cost_usd"], abs=0.01)
    assert r["total"]["per_file_usd"]["1"] == pytest.approx(one["per_file_usd"], abs=0.01)
    assert r["total"]["complete"] is True and r["checks_used"] == 0
    # the whole file as one block would be priced on the box around both cubes; per body it isn't
    assert design["processes"]["can_make"] >= 1


def test_a_weldment_shows_members_and_says_welding_isnt_priced():
    from src.services.body_check_service import check_bodies_sync

    r = check_bodies_sync(_mesh(cases.welded_frame()), filename="frame.stl", quantities=[1, 10])
    json.dumps(r)
    assert r["part_type"]["kind"] == "weldment"
    assert r["material_class"] == "steel" and r["material_basis"] == "weldment_default"
    assert r["total"] is None, "no total that pretends welding is in it"
    w = r["weldment"]
    assert w["joints"] == 4 and w["material_complete"] is True
    assert "welding" in w["not_priced"] and w["not_priced"][0] == "cutting 4 tubes"
    assert w["words"].startswith("ScaleCAD doesn't price welding yet.")
    # 4 tubes of 40 x 40 x 3: 0.000816 m^3 of steel, about 6.4 kg
    assert w["material_kg"] == pytest.approx(0.81696 * 7.85, rel=0.05)
    assert {d["copies"] for d in r["designs"]} == {2}


def test_a_declared_material_is_kept_for_a_weldment():
    from src.services.body_check_service import check_bodies_sync

    r = check_bodies_sync(_mesh(cases.t_joint()), filename="t.stl", quantities=[1],
                          material_class="aluminum", material_class_is_user=True)
    assert r["material_class"] == "aluminum" and r["material_basis"] == "request"


def test_one_solid_has_no_body_checks():
    from src.services.body_check_service import check_bodies_sync

    r = check_bodies_sync(_mesh(cases.cube()), filename="cube.stl", quantities=[1])
    assert r["designs"] == [] and r["total"] is None
    assert r["note"] == "One body: the part's own check is the answer."


def test_a_body_as_its_own_part_is_that_body_alone():
    from src.services.body_check_service import body_stl_bytes

    data, meta = body_stl_bytes(_mesh(cases.welded_frame()), 3)
    body = _mesh(data, "frame - body 3.stl")
    assert body.is_watertight and meta["of"] == 4 and meta["id"] == 3
    assert sorted(body.extents.round(1)) == [40.0, 40.0, 320.0]
    with pytest.raises(LookupError):
        body_stl_bytes(_mesh(cases.welded_frame()), 9)


# ── a STEP assembly: its product tree ───────────────────────────────────────


@pytest.mark.slow
def test_a_step_assembly_reads_its_product_tree():
    pytest.importorskip("gmsh")
    from tests.cad_fixtures import as1_fixture_bytes

    from src.analysis.part_types import describe
    from src.parsers.assembly_mesher import extract_assembly_from_bytes
    from src.services.body_check_service import resolve_bodies

    try:
        data = as1_fixture_bytes()
    except FileNotFoundError:
        pytest.skip("the AS1 assembly fixture isn't installed")
    model = extract_assembly_from_bytes(data, "as1.step")
    space, bodies, source = resolve_bodies(None, model)
    assert source["source"] == "step_product_tree" and source["parts"] == 18
    out = describe(space, bodies=bodies, product_tree=source)
    assert out["kind"] == "assembly" and out["body_count"] == 18
    assert "named in the file's product tree" in out["summary"]
    names = {b["name"] for b in out["bodies"]}
    assert {"nut", "bolt", "plate", "rod"} <= names
    assert all(b["closed"] for b in out["bodies"])
    # identical nuts share one design: 18 parts, 5 designs
    assert out["designs"] == len(model.unique_designs)
