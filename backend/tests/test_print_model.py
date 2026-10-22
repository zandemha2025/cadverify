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
    b = _features(_bridge(20))
    assert (b.fdm_need_cm2, b.fdm_column_cm3, b.fdm_bridges) == (0.0, 0.0, 1)
    # Resin doesn't bridge: the span is supported (20 × 10 mm, 30 mm up).
    assert b.resin_column_cm3 == pytest.approx(2.0 * 3.0)
    assert fdm_estimate(b, 1).support_cm3 == 0.0
    assert "bridged without support" in fdm_estimate(b, 1).material_source


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
    "bridge span 20": (lambda: _bridge(20), (1587.0, 3.86), None),  # bridged: no support either way
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
