"""The slicer-calibrated print model: time and material for FDM and SLA, the part as checked.

``src.costing.print_model`` is fitted to PrusaSlicer 2.7.2 on a reference set of
parts in their six face-down orientations (the fit's held-out error is in
``CALIBRATION``). These tests pin:

* the features it reads (volume, area, walls, height, footprint, support under
  the faces needing it) on parts whose numbers are known exactly;
* that it stays close to the slicer on generated parts, against PrusaSlicer's
  own recorded output for them (MK4 IS '0.20mm SPEED', SL1S '0.05 Normal');
* the resin time, which is exactly linear in layers;
* the plate: per-part time ÷ parts per plate, the footprint as checked, and a
  part too tall standing as checked priced the lowest way it fits;
* that the price follows the orientation through the real cost path.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from src.costing import print_model
from src.costing.print_model import (
    PrintFeatures,
    fdm_estimate,
    placed_features,
    plate_capacity,
    resin_estimate,
)


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


def _cantilever(reach: float = 30.0) -> trimesh.Trimesh:
    """The reference set's gen-cantilever: a 10×20×40 column, an 8 mm arm reaching ``reach`` past it."""
    return _union(_box((10, 20, 40), (5, 10, 20)), _box((10 + reach, 20, 8), ((10 + reach) / 2, 10, 36)))


def _bridge(span: float) -> trimesh.Trimesh:
    """gen-bridge-span: two 10×10×30 pillars, a 10×10×5 beam spanning ``span`` between them."""
    return _union(_box((10, 10, 30), (5, 5, 15)), _box((10, 10, 30), (15 + span, 5, 15)),
                  _box((20 + span, 10, 5), ((20 + span) / 2, 5, 32.5)))


def _sphere() -> trimesh.Trimesh:
    s = trimesh.creation.icosphere(subdivisions=4, radius=20)
    s.apply_translation((20, 20, 20))
    return s


def _features(mesh) -> PrintFeatures:
    m = mesh.copy()
    m.apply_translation(-m.bounds[0])
    return placed_features(m)


def test_features_of_a_box_are_exact():
    f = _features(_box((40, 30, 20), (0, 0, 0)))
    assert f.volume_cm3 == pytest.approx(24.0)
    assert f.area_cm2 == pytest.approx((2 * (40 * 30 + 40 * 20 + 30 * 20)) / 100)
    assert f.wall_cm2 == pytest.approx(2 * (40 * 20 + 30 * 20) / 100)
    assert (f.x_mm, f.y_mm, f.height_mm) == pytest.approx((40, 30, 20))
    assert f.footprint_cm2 == pytest.approx(12.0)
    assert (f.fdm_need_cm2, f.fdm_column_cm3, f.fdm_bridges, f.resin_column_cm3) == (0.0, 0.0, 0, 0.0)
    # Memoized by the exact coordinates: a re-price reads the same object.
    m = _box((40, 30, 20), (20, 15, 10))
    assert placed_features(m) is placed_features(m.copy())


def test_support_reads_the_faces_needing_it_and_leaves_bridges_out():
    f = _features(_cantilever(30))
    # The arm's underside: 30 × 20 mm, 32 mm above the plate.
    assert f.fdm_need_cm2 == pytest.approx(6.0)
    assert f.fdm_column_cm3 == pytest.approx(6.0 * 3.2)
    assert f.resin_column_cm3 == pytest.approx(6.0 * 3.2)
    b = _features(_bridge(8))
    assert (b.fdm_need_cm2, b.fdm_column_cm3, b.fdm_bridges) == (0.0, 0.0, 1)
    # Resin doesn't bridge: the span is supported (8 × 10 mm, 30 mm up).
    assert b.resin_column_cm3 == pytest.approx(0.8 * 3.0)
    assert fdm_estimate(b, 1).support_cm3 == 0.0
    assert "bridged without support" in fdm_estimate(b, 1).material_source
    # Longer than desktop FDM's 10 mm bridge limit, a span is supported (20 × 10 mm, 30 mm up).
    long = _features(_bridge(20))
    assert (long.fdm_need_cm2, long.fdm_bridges) == (pytest.approx(2.0), 0)
    assert long.fdm_column_cm3 == pytest.approx(2.0 * 3.0)
    assert fdm_estimate(long, 1).support_cm3 > 0.0


def _tee():
    return _union(_box((10, 20, 40), (25, 10, 20)), _box((60, 20, 8), (30, 10, 44)))


# PrusaSlicer 2.7.2's own output for these parts as built (+Z up), one on the plate (MK4 IS):
# (time s, filament cm³) with supports off, and with every overhang supported (None: no overhang).
SLICED_MK4IS = {
    "cube 10 mm": (lambda: _box((10, 10, 10), (5, 5, 5)), (419.0, 0.60), None),
    "cantilever 30": (lambda: _cantilever(30), (1833.0, 5.14), (2027.0, 8.87)),
    "cantilever 60": (lambda: _cantilever(60), (2011.0, 7.18), (2398.0, 14.50)),
    "tee": (_tee, (2285.0, 7.29), (2746.0, 14.90)),
    "sphere 40": (_sphere, (1846.0, 9.61), (2076.0, 10.22)),
    "bridge span 10": (lambda: _bridge(10), (1530.0, 3.48), None),  # bridged (at the limit): no support
}


@pytest.mark.parametrize("name", sorted(SLICED_MK4IS))
def test_fdm_time_and_filament_stay_close_to_the_slicer(name):
    make, (seconds, filament), supported = SLICED_MK4IS[name]
    f = _features(make())
    plain = fdm_estimate(PrintFeatures(**{**f.__dict__, "fdm_need_cm2": 0.0, "fdm_column_cm3": 0.0}), 1)
    assert plain.material_cm3 == pytest.approx(filament, rel=0.10), plain.material_source
    assert plain.hours_per_part * 3600 == pytest.approx(seconds, rel=0.10), plain.source
    est = fdm_estimate(f, 1)
    if supported is None:
        assert est.support_cm3 == 0.0
    else:
        # The held-out p90 is under 20% for time with supports and about 40% for support alone.
        assert est.hours_per_part * 3600 == pytest.approx(supported[0], rel=0.20), est.source
        assert est.material_cm3 == pytest.approx(supported[1], rel=0.20), est.material_source


def test_resin_time_is_linear_in_layers_like_the_slicer():
    f = _features(_cantilever(30))
    est = resin_estimate(f, 1)
    c = print_model.RESIN
    layers = math.ceil(round((40.0 + c["lift_mm"]) / c["layer_mm"], 6))
    assert est.layers == layers == 920  # PrusaSlicer: 920 layers for this part
    assert est.hours_per_part * 3600 == pytest.approx(c["t0_s"] + c["t_layer_s"] * layers)
    assert est.hours_per_part * 3600 == pytest.approx(4551.9, rel=0.01)  # the slicer's own estimate
    assert est.material_cm3 == pytest.approx(16.24, rel=0.15)  # resin with supports and pad
    # A plate of 4 shares the same layers.
    assert resin_estimate(f, 4).hours_per_part == pytest.approx(est.hours_per_part / 4)


# PrusaSlicer 2.7.2 SL1S ('0.05 Normal', default supports and pad), the calibration coupons and
# generated parts in their file orientation: resin ml per part (a coupon's from its full plate;
# each part on a plate has its own pad, so it matches the part sliced alone).
SLICED_SL1S_RESIN = {
    "cv_cal_small_flat_housing.stl": 8.422,
    "cv_cal_small_rotational_sensor.stl": 6.934,
    "cv_cal_tiny_boxy_cover.stl": 4.729,
    "cv_cal_tiny_flat_gasket.stl": 1.230,
    "cv_cal_tiny_rotational_adapter.stl": 4.293,
    "cv_cal_tiny_rotational_ring.stl": 1.984,
    "cv_cal_small_boxy_bracket.stl": 45.333,
}


def test_the_resin_pad_follows_the_parts_outline_not_its_box():
    # Round 7: the pad was priced over the box footprint, 26% over on the coupons' plates and
    # 2.5x on a thin gasket. Over the outline from above grown by 2 mm it stays within 12%.
    from pathlib import Path as _P

    from src.costing.calibration_fixtures import ensure_calibration_fixtures

    root = ensure_calibration_fixtures(_P(__file__).resolve().parents[2] / ".pytest_cache")
    errors = {}
    for name, slicer_ml in SLICED_SL1S_RESIN.items():
        f = placed_features(trimesh.load(root / name, force="mesh"))
        est = resin_estimate(f, 1)
        errors[name] = est.material_cm3 / slicer_ml - 1
        assert "the part's outline and 2 mm around it" in est.material_source
    assert all(abs(e) < 0.12 for e in errors.values()), errors
    assert sorted(abs(e) for e in errors.values())[len(errors) // 2] < 0.08, errors
    # A box's pad is its footprint grown by 2 mm on every side; a ring's leaves its hole open.
    box = _features(_box((20, 15, 10), (0, 0, 5)))
    assert box.pad_cm2 == pytest.approx(24 * 19 / 100.0, rel=0.005)
    ring = _features(trimesh.creation.annulus(r_min=10, r_max=20, height=5, sections=256))
    assert ring.pad_cm2 == pytest.approx(math.pi * (22 ** 2 - 8 ** 2) / 100.0, rel=0.01)
    assert ring.pad_cm2 < 0.85 * (ring.x_mm + 4) * (ring.y_mm + 4) / 100.0
    # Features built without an outline fall back to the box grown by the margin.
    bare = PrintFeatures(**{**box.__dict__, "pad_cm2": 0.0})
    assert resin_estimate(bare, 1).material_cm3 == pytest.approx(resin_estimate(box, 1).material_cm3, rel=0.005)


def test_plate_capacity_uses_the_footprint_as_checked():
    f = _features(_box((100, 100, 20), (0, 0, 0)))
    # 250 × 250 plate, 4 mm apart: a 2 × 2 grid; 0.5 areal packing allows int(0.5·62500/104²) = 2.
    assert plate_capacity(f, (250, 250, 250), 4.0, 0.5) == 2
    assert plate_capacity(f, (250, 250, 250), 4.0, 1.0) == 4
    tall = _features(_box((10, 10, 300), (0, 0, 0)))
    assert plate_capacity(tall, (250, 250, 250), 4.0, 0.5) == 0
    # Too long for the plate either way, but it fits turned on the diagonal.
    long = _features(_box((300, 20, 10), (0, 0, 0)))
    assert plate_capacity(long, (250, 250, 250), 4.0, 0.5) == 1


def test_fdm_time_per_part_falls_with_parts_per_plate():
    f = _features(_cantilever(30))
    one, many = fdm_estimate(f, 1), fdm_estimate(f, 20)
    assert many.hours_per_part < one.hours_per_part
    assert many.material_cm3 == one.material_cm3
    assert "20 per plate" in many.source and "÷ 20" in many.source


def test_a_part_too_tall_standing_is_priced_the_lowest_way_it_fits():
    from src.costing.drivers import GeoDrivers

    mesh = _box((20, 20, 300), (10, 10, 150))
    f = placed_features(mesh)
    drivers = GeoDrivers(volume_cm3=f.volume_cm3, surface_area_cm2=f.area_cm2, bbox_mm=(20, 20, 300),
                         bbox_volume_cm3=120.0, hull_volume_cm3=120.0, nominal_wall_mm=5.0, face_count=12,
                         max_bbox_mm=300, is_valid=True, rotational=False, rot_axis_len_mm=0, rot_cross_dia_mm=0,
                         print_features=f, print_mesh=mesh)
    est, placement = print_model.plan("fdm", drivers, (250, 250, 250), 4.0, 0.5)
    assert "doesn't fit the 250 × 250 × 250 mm work area standing (300 mm tall" in placement
    assert "20 mm tall" in placement
    assert est.layers == 100
    assert print_model.plan("fdm", drivers, (100, 100, 100), 4.0, 0.5) is None


def test_the_other_ways_down_are_the_part_turned_and_measured():
    from src.analysis.orientation import Orientation, rotation_down

    mesh = _cantilever(30)
    ways = print_model.alternates(mesh)
    assert [w for w, _ in ways] == [w for w, _ in print_model.alternates(mesh)]  # memoized, same order
    heights = [g.height_mm for _, g in ways]
    assert heights == sorted(heights)
    sides = {"upside down": "+Z", **{f"on its {n} side (as checked)": n for n in ("−X", "+X", "−Y", "+Y")}}
    for words, g in ways:
        direction = dict(print_model._SIDES)[sides[words]]
        want = placed_features(Orientation.of(rotation_down(direction)).apply(mesh))
        for name in ("volume_cm3", "area_cm2"):  # the part's own, as checked: the same every way down
            assert getattr(g, name) == pytest.approx(getattr(want, name), rel=1e-9)
        for name in ("wall_cm2", "height_mm", "x_mm", "y_mm", "footprint_cm2", "fdm_need_cm2", "fdm_column_cm3",
                     "fdm_bridges", "resin_column_cm3", "pad_cm2", "outline_xy", "layer_perimeter_mm",
                     "layer_area_mm2"):
            assert getattr(g, name) == getattr(want, name), (words, name)


def test_a_mesh_changed_in_place_is_measured_again():
    m = _box((40, 30, 20), (20, 15, 10))
    before = placed_features(m)
    assert placed_features(m) is before
    m.apply_scale(2.0)  # the same object, new coordinates
    after = placed_features(m)
    assert after.volume_cm3 == pytest.approx(8 * before.volume_cm3)


def test_a_400k_triangle_stl_is_decimated_once_per_price(tmp_path, monkeypatch):
    """A part over the face cap, too tall to stand: its other ways down turn the one bounded copy
    (the make-vs-buy crossover prices it at dozens of quantities, for FDM and SLA)."""
    from collections import OrderedDict

    from src.analysis import context
    from src.costing.drivers import GeoDrivers
    from src.parsers.stl_parser import parse_stl

    for store in ("_cache", "_alternates", "_bounded", "_keys"):
        monkeypatch.setattr(print_model, store, OrderedDict())
    tall = trimesh.creation.cylinder(radius=10, height=260, sections=100_000)
    tall.apply_translation(-tall.bounds[0])
    path = tmp_path / "tall-400k.stl"
    tall.export(path)
    mesh = parse_stl(path)
    assert len(mesh.faces) == 400_000 > context._max_analysis_faces()
    decimated = []
    real = context._decimate_to
    monkeypatch.setattr(context, "_decimate_to", lambda m, target: decimated.append(len(m.faces)) or real(m, target))

    f = placed_features(mesh)
    assert decimated == [400_000]
    drivers = GeoDrivers(volume_cm3=f.volume_cm3, surface_area_cm2=f.area_cm2, bbox_mm=(20, 20, 260),
                         bbox_volume_cm3=104.0, hull_volume_cm3=f.volume_cm3, nominal_wall_mm=5.0,
                         face_count=400_000, max_bbox_mm=260, is_valid=True, rotational=True, rot_axis_len_mm=260,
                         rot_cross_dia_mm=20, print_features=f, print_mesh=mesh)
    for _ in range(20):  # quantities, as the crossover asks
        for process, envelope in (("fdm", (300, 300, 250)), ("sla", (300, 300, 200))):
            est, placement = print_model.plan(process, drivers, envelope, 4.0, 0.5)
            assert "doesn't fit" in placement and "20 mm tall" in placement
    assert decimated == [400_000]  # once, for the part as checked; never per turned copy
    ways = print_model.alternates(mesh)  # every way down, measured in full: still the one decimation
    assert decimated == [400_000]
    assert all(g.volume_cm3 == f.volume_cm3 for _, g in ways)
    assert ways[0][1].height_mm == pytest.approx(20, abs=0.01)
    assert ways[-1][1].height_mm == pytest.approx(260)  # upside down
    # Support and sections read on the bounded copy, the same part turned: the support under a
    # cylinder lying down is its lower half, the same along its length.
    lying = ways[0][1]
    assert lying.fdm_need_cm2 > 0 and lying.layer_area_mm2


# ── The resin pad reads the same whichever way up the part lies ─────────────────────────────
_DOWN = {"-Z": (0, 0, -1), "+Z": (0, 0, 1), "+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0)}
_PAIRS = (("-Z", "+Z"), ("+X", "-X"), ("+Y", "-Y"))  # each the other upside down: the same shadow


def _laid(mesh, side):
    from src.analysis.orientation import Orientation, rotation_down

    return Orientation.of(rotation_down(_DOWN[side])).apply(mesh)


def _exact_pad_cm2(mesh, margin=2.0):
    """The union of every face's top-down triangle, grown with square corners (slow, exact)."""
    import shapely

    tri = np.asarray(mesh.vertices)[mesh.faces][:, :, :2]
    polys = shapely.polygons(np.concatenate([tri, tri[:, :1]], axis=1))
    shadow = shapely.union_all(polys[shapely.area(polys) > 0])
    return float(shapely.buffer(shadow, margin, join_style="mitre").area) / 100.0


def _corpus(name):
    from pathlib import Path as _P

    here = _P(__file__).resolve().parent
    if name.startswith("cv_cal_"):
        from src.costing.calibration_fixtures import ensure_calibration_fixtures

        path = ensure_calibration_fixtures(here.parents[1] / ".pytest_cache") / name
    else:
        path = here / "trap-corpus" / name
    m = trimesh.load(path, force="mesh")
    m.apply_translation(-m.bounds[0])
    return m


@pytest.mark.parametrize("name, sides", [
    # trimesh's projection dropped part of the shadow: -28.9% and -28.8% of the exact pad.
    ("trap-nonmanifold-missing-face.stl", ("-Z", "+Z")),
    ("cv_cal_invalid_open_shell.stl", ("+X", "-X")),
    # ... or square corners turned a sliver in its outline into a spike, one way up: +10.3%.
    ("trap-assembly-adjacent-dumbbell-0.6neck.stl", ("-Z", "+Z")),
])
def test_the_pad_of_a_corpus_part_is_the_same_upside_down(name, sides):
    mesh = _corpus(name)
    pads = [print_model.pad_area_cm2(_laid(mesh, s)) for s in sides]
    exact = _exact_pad_cm2(_laid(mesh, sides[0]))
    assert pads[0] == pytest.approx(pads[1], rel=0.005)
    assert pads == pytest.approx([exact, exact], rel=0.02)


@pytest.mark.parametrize("name", ["control-cube-10mm.stl", "control-organic-goblet.stl", "trap-small-rib-0.39mm.stl",
                                  "cv_cal_medium_rotational_bracket.stl", "cv_cal_tiny_rotational_ring.stl"])
def test_a_part_whose_outline_reads_cleanly_keeps_its_pad(name):
    """Where trimesh's outline agrees with the sampled shadow, the pad is that outline grown, as before."""
    from trimesh.path.polygons import projected

    mesh = _corpus(name)
    for side in _DOWN:
        placed = _laid(mesh, side)
        before = projected(placed, normal=[0.0, 0.0, 1.0]).buffer(2.0, join_style="mitre").area / 100.0
        assert print_model.pad_area_cm2(placed) == before


def test_the_pad_of_a_400k_triangle_part_is_the_same_every_way_down(monkeypatch):
    """A 420k-triangle torus, decimated for analysis as pricing reads it. Its shadow is known:
    flat, a ring; on its side, a stadium. trimesh's projection read one side 7% low."""
    from src.analysis.context import _maybe_decimate

    R, r, w = 40.0, 12.0, 2.0
    torus = trimesh.creation.torus(major_radius=R, minor_radius=r, major_sections=1000, minor_sections=210)
    assert len(torus.faces) == 420_000
    bounded, info = _maybe_decimate(torus)
    assert info and info["succeeded"]
    flat = math.pi * ((R + r + w) ** 2 - (R - r - w) ** 2) / 100.0
    side = (4 * R * (r + w) + math.pi * (r + w) ** 2) / 100.0
    pads = {s: print_model.pad_area_cm2(_laid(bounded, s)) for s in _DOWN}
    for a, b in _PAIRS:
        assert pads[a] == pytest.approx(pads[b], rel=0.005), (a, b, pads)
    assert [pads["-Z"], pads["+Z"]] == pytest.approx([flat, flat], rel=0.005)
    assert [pads[s] for s in ("+X", "-X", "+Y", "-Y")] == pytest.approx([side] * 4, rel=0.005)


def test_the_sampled_shadow_is_the_same_upside_down_and_matches_the_outline():
    mesh = _corpus("control-organic-goblet.stl")
    a, b = (print_model.shadow_grid(_laid(mesh, s)) for s in ("+X", "-X"))
    assert a.area_mm2() == pytest.approx(b.area_mm2(), rel=1e-3)
    assert a.area_mm2() == pytest.approx(np.count_nonzero(a.covered()) * a.pitch ** 2)
    box = print_model.shadow_grid(_box((20, 15, 10), (10, 7.5, 5)))
    assert box.area_mm2() == pytest.approx(300.0, rel=0.002)
    assert box.grown_area_mm2(2.0) == pytest.approx(24 * 19 - (4 - math.pi) * 4, rel=0.005)  # round corners
