"""FDM bridging: a flat span between walls prints without support.

``src.analysis.support.support_regions`` splits the faces the overhang rule
marks into connected regions and leaves a flat region off the support list when
its lines run from an anchor to an anchor (an edge where the part continues
below it). FDM's check uses it (``check_overhangs(..., bridges=True)``); resin
and metal printers don't bridge, so their checks are unchanged. The
orientation comparison reports the same FDM faces as the check.

The rule was checked against PrusaSlicer 2.7.2 (MK4 IS profile, every overhang
supported vs "don't support bridges") on generated spans of 5–80 mm, a
window frame, cantilevers, a table and a C bracket in all six orientations
(the reference set in the slicer calibration; see ``src.costing.print_model``).
"""
from __future__ import annotations

import numpy as np
import pytest
import trimesh

import src.analysis.processes  # noqa: F401  populate the analyzer registry
from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.orientation import orientation_options
from src.analysis.processes.base import get_analyzer
from src.analysis.processes.checks import check_overhangs
from src.analysis.support import support_regions


def _box(size, centre):
    b = trimesh.creation.box(size)
    b.apply_translation(centre)
    return b


def _union(*parts) -> trimesh.Trimesh:
    try:
        out = trimesh.boolean.union(list(parts))
    except Exception as exc:  # pragma: no cover - CSG backend missing
        pytest.skip(f"boolean backend unavailable: {exc}")
    assert out.is_watertight
    return out


def _bridge(span: float, tail: float = 0.0) -> trimesh.Trimesh:
    """Two 10×10×30 pillars and a 10×10×5 beam on top spanning ``span`` between them.

    ``tail`` extends the beam past the second pillar (a cantilever, which needs support).
    """
    length = 20 + span + tail
    return _union(_box((10, 10, 30), (5, 5, 15)), _box((10, 10, 30), (15 + span, 5, 15)),
                  _box((length, 10, 5), (length / 2, 5, 32.5)))


def _gamma() -> trimesh.Trimesh:
    """A 10×20×40 column with a 40×20×8 arm reaching 30 mm past it: a cantilever."""
    return _union(_box((10, 20, 40), (5, 10, 20)), _box((40, 20, 8), (20, 10, 36)))


def _table() -> trimesh.Trimesh:
    """A 70×70×5 top on four 8×8×30 corner legs: lines across it rest on a leg at most at one end."""
    legs = [_box((8, 8, 30), (x, y, 15)) for x in (4, 66) for y in (4, 66)]
    return _union(*legs, _box((70, 70, 5), (35, 35, 32.5)))


def _window() -> trimesh.Trimesh:
    """A window frame standing up: two 10×10×70 posts, a sill and a lintel spanning 60 mm."""
    return _union(_box((10, 10, 70), (5, 5, 35)), _box((10, 10, 70), (75, 5, 35)),
                  _box((80, 10, 10), (40, 5, 5)), _box((80, 10, 10), (40, 5, 65)))


def _ctx(mesh: trimesh.Trimesh) -> GeometryContext:
    return GeometryContext.build(mesh, analyze_geometry(mesh))


def _codes(mesh: trimesh.Trimesh, process: str) -> list[str]:
    return [i.code for i in get_analyzer(ProcessType(process)).analyze(_ctx(mesh))]


@pytest.mark.parametrize("span", [5, 20, 80])
def test_a_span_between_two_pillars_is_a_bridge_for_fdm_only(span):
    mesh = _bridge(span)
    ctx = _ctx(mesh)
    plain = check_overhangs(ctx, 45.0, ProcessType.FDM)
    assert plain and plain[0].code == "OVERHANG"  # the rule alone marks the beam's underside
    assert check_overhangs(ctx, 45.0, ProcessType.FDM, bridges=True) == []
    assert "OVERHANG" not in _codes(mesh, "fdm")
    # Resin doesn't bridge: its check still asks for support under the span.
    assert "OVERHANG" in _codes(mesh, "sla")
    est = support_regions(mesh, 45.0)
    assert est.bridges == 1 and est.area_mm2 == 0.0 and est.column_mm3 == 0.0
    assert est.longest_bridge_mm == pytest.approx(span, abs=0.5)
    assert est.bridge_area_mm2 == pytest.approx(span * 10.0, rel=1e-6)


def test_a_bridge_limit_keeps_longer_spans_on_the_support_list():
    mesh = _bridge(40)
    assert support_regions(mesh, 45.0, bridge_limit_mm=10.0).bridges == 0
    assert support_regions(mesh, 45.0, bridge_limit_mm=10.0).area_mm2 == pytest.approx(400.0, rel=1e-6)
    assert support_regions(mesh, 45.0, bridge_limit_mm=50.0).bridges == 1


def test_a_cantilever_still_needs_support_and_keeps_every_face():
    mesh = _gamma()
    ctx = _ctx(mesh)
    plain = check_overhangs(ctx, 45.0, ProcessType.FDM)
    bridged = check_overhangs(ctx, 45.0, ProcessType.FDM, bridges=True)
    assert plain and bridged
    assert bridged[0].affected_faces == plain[0].affected_faces
    assert bridged[0].message == plain[0].message
    est = support_regions(mesh, 45.0)
    assert est.bridges == 0 and est.area_mm2 == pytest.approx(30 * 20, rel=1e-6)
    # Footprint 30×20 mm, 32 mm above the plate.
    assert est.column_mm3 == pytest.approx(30 * 20 * 32, rel=1e-6)


def test_a_table_top_on_corner_legs_needs_support():
    mesh = _table()
    est = support_regions(mesh, 45.0, keep_regions=True)
    assert est.bridges == 0 and est.area_mm2 > 0
    assert "OVERHANG" in _codes(mesh, "fdm")


def test_a_window_lintel_bridges_and_the_sill_rests_on_the_plate():
    mesh = _window()
    assert "OVERHANG" not in _codes(mesh, "fdm")
    est = support_regions(mesh, 45.0)
    assert est.bridges == 1 and est.longest_bridge_mm == pytest.approx(60.0, abs=0.5)


def test_a_bridge_and_a_cantilever_together_mark_only_the_cantilever():
    mesh = _bridge(20, tail=15)
    ctx = _ctx(mesh)
    issues = check_overhangs(ctx, 45.0, ProcessType.FDM, bridges=True)
    assert len(issues) == 1
    faces = np.asarray(issues[0].affected_faces)
    centres = ctx.centroids[faces]
    # Every marked face is under the tail, past the second pillar (x > 40).
    assert np.all(centres[:, 0] > 40.0 - 1e-6)
    assert float(ctx.face_areas[faces].sum()) == pytest.approx(15 * 10, rel=1e-6)
    assert "A flat span between walls" in issues[0].message and "20 mm across" in issues[0].message
    assert issues[0].region_center[0] > 40.0


def test_the_orientation_comparison_reports_the_check_s_fdm_faces():
    mesh = _bridge(20, tail=15)
    options = orientation_options(mesh)
    for cand in options["candidates"]:
        from src.analysis.orientation import Orientation

        placed = Orientation.of(np.asarray(cand["rotation"], dtype=float)).apply(mesh)
        issues = check_overhangs(_ctx(placed), 45.0, ProcessType.FDM, bridges=True)
        faces = len(issues[0].affected_faces) if issues else 0
        assert cand["support"]["fdm"]["faces"] == faces, cand["id"]
        assert ("OVERHANG" in cand["flags"]["fdm"]) == bool(faces), cand["id"]
    as_file = next(c for c in options["candidates"] if c["id"] == "down-z")
    fdm = as_file["support"]["fdm"]
    assert fdm["bridges"] == 1 and fdm["longest_bridge_mm"] == pytest.approx(20.0, abs=0.5)
    assert fdm["area_mm2"] == pytest.approx(150.0, rel=1e-4)
    # The bridged faces' centres, as fractions of the placed box: under the beam between the pillars.
    (box,) = fdm["bridge_boxes"]
    x0, y0, z0, x1, y1, z1 = box
    assert 10 / 55 - 1e-3 <= x0 < x1 <= 30 / 55 + 1e-3
    assert z0 == pytest.approx(30 / 35, abs=1e-4) and z1 == pytest.approx(30 / 35, abs=1e-4)
    # Resin doesn't bridge: the whole underside past the pillars still needs support.
    assert as_file["support"]["sla"]["area_mm2"] == pytest.approx(350.0, rel=1e-4)


def test_bridging_is_deterministic():
    mesh = _window()
    a = support_regions(mesh, 45.0, keep_regions=True)
    b = support_regions(mesh.copy(), 45.0, keep_regions=True)
    assert (a.area_mm2, a.column_mm3, a.bridges, a.longest_bridge_mm) == (b.area_mm2, b.column_mm3, b.bridges, b.longest_bridge_mm)
    assert [r.faces.tolist() for r in a.regions] == [r.faces.tolist() for r in b.regions]
