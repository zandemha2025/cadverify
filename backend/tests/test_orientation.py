"""A chosen orientation: exact turns, the check's own rules, a deterministic choice.

The engine reads +Z as the build direction (printing) and the opening direction
(molding). These tests pin what turning the part does and doesn't change:

* 90° turns are exact: extents are permuted, volume and area are unchanged and
  the faces keep their order; turning back gives the same coordinates.
* A part with a large overhang in the file's orientation has none once laid on
  its flat side, by the real FDM analyzer.
* The comparison marks exactly the faces the analyzers mark, uses the
  analyzers' own limits, and picks the same orientation every time.
* Prices don't change with orientation (the cost model picks the build
  placement itself and doesn't price support material).
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest
import trimesh

import src.analysis.processes  # noqa: F401  populate the analyzer registry
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.orientation import (
    DRAFT_MIN_DEG,
    OVERHANG_LIMIT_DEG,
    Orientation,
    OrientationError,
    orientation_options,
    parse_orientation,
    rotation_down,
    rotation_from_turns,
)
from src.analysis.processes.base import _REGISTRY, get_analyzer


def _gamma() -> trimesh.Trimesh:
    """A Γ bracket: a 10×20×40 column with a 40×20×10 arm on top.

    In the file's orientation the arm's underside (30×20 mm, 30 mm up) hangs
    over nothing: it needs support for every printing process. Laid on its
    20 mm side (the Γ profile on the plate) nothing overhangs.
    """
    column = trimesh.creation.box((10, 20, 40))
    column.apply_translation((5, 10, 20))
    arm = trimesh.creation.box((40, 20, 10))
    arm.apply_translation((20, 10, 35))
    try:
        out = trimesh.boolean.union([column, arm])
    except Exception as exc:  # pragma: no cover - CSG backend missing
        pytest.skip(f"boolean backend unavailable: {exc}")
    assert out.is_watertight and abs(out.volume - 14000.0) < 1e-6
    return out


def _issues(mesh: trimesh.Trimesh, process: str):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    return get_analyzer(ProcessType(process)).analyze(ctx)


ALL_TURNS = [
    rotation_from_turns(t)
    for t in itertools.product(("x0", "x90", "x180", "x270"), ("y0", "y90", "y180", "y270"), ("z0", "z90"))
]


def test_quarter_turns_are_exact_and_reach_all_24_orientations():
    mesh = _gamma()
    seen = set()
    for R in ALL_TURNS:
        o = Orientation.of(R)
        seen.add(o.key)
        assert o.exact
        placed = o.apply(mesh)
        # Same faces, same order; coordinates are a signed permutation, exactly.
        assert np.array_equal(placed.faces, mesh.faces)
        perm = np.abs(o.R).argmax(axis=1)
        sign = o.R[np.arange(3), perm]
        assert np.array_equal(placed.vertices, mesh.vertices[:, perm] * sign)
        assert np.array_equal(np.sort(placed.extents), np.sort(mesh.extents))
        assert np.array_equal(placed.extents, mesh.extents[perm])
        assert placed.volume == pytest.approx(mesh.volume, rel=1e-12)
        assert placed.area == pytest.approx(mesh.area, rel=1e-12)
        # Turning back is the file's own coordinates, bit for bit.
        assert np.array_equal(o.unapply(placed).vertices, mesh.vertices)
        assert mesh.metadata == placed.metadata
    assert len(seen) == 24


def test_a_tilted_face_down_keeps_volume_and_faces():
    mesh = _gamma()
    o = Orientation.of(rotation_down([1.0, 1.0, -1.0]))
    assert not o.exact
    placed = o.apply(mesh)
    assert np.array_equal(placed.faces, mesh.faces)
    assert placed.volume == pytest.approx(mesh.volume, rel=1e-12)
    assert o.R @ (np.array([1.0, 1.0, -1.0]) / np.sqrt(3)) == pytest.approx([0, 0, -1], abs=1e-12)
    assert np.max(np.abs(o.unapply(placed).vertices - mesh.vertices)) < 1e-12


def test_every_way_of_asking_names_the_same_orientation():
    up_x = parse_orientation("down:-1,0,0")
    assert up_x.key == parse_orientation('{"down": [-1, 0, 0]}').key
    assert up_x.key == parse_orientation("turns:y-90").key
    assert up_x.key == parse_orientation("rotation:0,0,-1,0,1,0,1,0,0").key
    assert up_x.label == "File +X up" and up_x.up.tolist() == [1.0, 0.0, 0.0]
    assert parse_orientation('{"rotation": [[0,0,-1],[0,1,0],[1,0,0]]}').key == up_x.key
    # The file's own orientation is no orientation.
    for own in (None, "", "file", "turns:x90,x-90", "rotation:1,0,0,0,1,0,0,0,1", '{"down": [0, 0, -1]}'):
        assert parse_orientation(own) is None, own
    for bad in ("rotation:1,0,0,0,1,0,0,0,-1", "rotation:1,1,0,0,1,0,0,0,1", "turns:w90",
                "down:0,0,0", "down:1,2", "spin:90", '{"rotation": [[1,0,0]], "down": [0,0,1]}', "{not json"):
        with pytest.raises(OrientationError):
            parse_orientation(bad)
    # Six sides land exactly, each with that side down.
    for d in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]):
        R = rotation_down(d)
        assert set(np.unique(R)) <= {-1.0, 0.0, 1.0}
        assert (R @ np.array(d, float)).tolist() == [0.0, 0.0, -1.0]


def test_a_big_overhang_goes_when_laid_on_its_flat_side():
    mesh = _gamma()
    standing = [i for i in _issues(mesh, "fdm") if i.code == "OVERHANG"]
    assert len(standing) == 1
    arm_under = standing[0]
    assert arm_under.measured_value == pytest.approx(90.0)  # a flat ceiling
    opts = orientation_options(mesh)
    file_side = next(c for c in opts["candidates"] if c["id"] == "down-z")
    assert file_side["support"]["fdm"]["area_mm2"] == pytest.approx(600.0)  # 30 × 20 mm under the arm
    assert file_side["support"]["fdm"]["faces"] == len(arm_under.affected_faces)
    best = next(c for c in opts["candidates"] if c["id"] == opts["best"]["fdm"])
    assert best["id"] == "down-y" and best["support"]["fdm"]["area_mm2"] == 0.0
    assert best["height_mm"] == pytest.approx(20.0)
    lying = Orientation.of(best["rotation"]).apply(mesh)
    assert not [i for i in _issues(lying, "fdm") if i.code == "OVERHANG"]
    assert lying.extents.tolist() == pytest.approx([40.0, 40.0, 20.0])


def test_the_comparison_marks_the_faces_the_analyzers_mark():
    mesh = _gamma()
    opts = orientation_options(mesh)
    for c in opts["candidates"]:
        placed = Orientation.of(c["rotation"]).apply(mesh)
        for proc in ("fdm", "sla", "dmls"):
            found = [i for i in _issues(placed, proc) if i.code == "OVERHANG"]
            assert c["support"][proc]["faces"] == (len(found[0].affected_faces) if found else 0), (c["id"], proc)
        drafts = [i for i in _issues(placed, "injection_molding") if i.code == "INSUFFICIENT_DRAFT"]
        assert c["draft"]["injection_molding"]["faces"] == (len(drafts[0].affected_faces) if drafts else 0)


def test_the_limits_are_the_analyzers_own():
    """Every analyzer that checks overhangs or draft uses the comparison's number."""
    mesh = _gamma()
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    overhang, draft = {}, {}
    for proc in _REGISTRY:
        for issue in get_analyzer(proc).analyze(ctx):
            if issue.code == "OVERHANG":
                overhang[proc.value] = issue.required_value
            if issue.code == "INSUFFICIENT_DRAFT":
                draft[proc.value] = issue.required_value
    assert overhang == OVERHANG_LIMIT_DEG
    assert draft == DRAFT_MIN_DEG


def test_the_suggestion_is_deterministic():
    mesh = _gamma()
    first = orientation_options(mesh)
    assert orientation_options(mesh.copy()) == first
    assert orientation_options(mesh) == first
    # A face picked in the 3D view is one more candidate; the rest stay as they were.
    picked = orientation_options(mesh, down=[0.0, 1.0, 0.0])
    assert picked["candidates"][:-1] == first["candidates"]
    assert picked["candidates"][-1]["support"] == next(c for c in first["candidates"] if c["id"] == "down+y")["support"]
    assert first["best"]["injection_molding"] in {c["id"] for c in first["candidates"]}


def test_prices_do_not_change_with_orientation():
    from src.api.routes import _run_cost_engine_ctx
    from src.costing import EstimateOptions, estimate_decision, report_to_dict

    mesh = _gamma()

    def prices(o):
        m = o.apply(mesh) if o is not None else mesh
        result, mm, ctx = _run_cost_engine_ctx(m, "gamma.stl", orientation=o)
        rep = report_to_dict(estimate_decision(result, mm, ctx.features, EstimateOptions(quantities=[1, 100])))
        return {(e["process"], e["quantity"], e["material"]): e["unit_cost_usd"] for e in rep["estimates"]}, result

    base, base_result = prices(None)
    turned, turned_result = prices(parse_orientation("down:0,-1,0"))
    assert base and turned == base
    # ...while the findings that read the build direction do change.
    codes = lambda r, p: {i.code for ps in r.process_scores if ps.process.value == p for i in ps.issues}
    assert "OVERHANG" in codes(base_result, "fdm") and "OVERHANG" not in codes(turned_result, "fdm")


def test_region_centres_come_back_in_file_coordinates():
    from src.api.routes import _run_cost_engine_ctx

    mesh = _gamma()
    # Stood on the arm's end (file +X down) the column sticks out sideways and overhangs.
    o = parse_orientation("down:1,0,0")
    result, _, _ = _run_cost_engine_ctx(o.apply(mesh), "gamma.stl", orientation=o)
    sla = next(ps for ps in result.process_scores if ps.process.value == "sla")
    oh = next(i for i in sla.issues if i.code == "OVERHANG")
    # The flagged faces' centroids, in the FILE's coordinates, average to the reported centre.
    file_centroids = mesh.triangles_center[oh.affected_faces[:50]].mean(axis=0)
    assert np.array(oh.region_center) == pytest.approx(file_centroids, abs=1e-9)
    placed_centroids = o.apply(mesh).triangles_center[oh.affected_faces[:50]].mean(axis=0)
    assert not np.allclose(placed_centroids, file_centroids)
