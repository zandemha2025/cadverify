"""Tooling tier on the measured size (M12); one minimum charge per order (M17).

M12: a 300 mm STL cube's enclosing box carries 2 × its coordinate rounding
(300.00005 mm) and its mold read tier XL ($60,000) against tier L ($30,000)
for the same cube as STEP. M17: DED/WAAM charged a $300 minimum per 10-part
lot, so no quantity ever came under $30 a part.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.analysis.models import ProcessType as PT
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import build_rate_card
from src.profiles.models import MaterialProfile


def _drivers(size, precision=0.0, billet=None) -> GeoDrivers:
    v = size ** 3 / 1000
    return GeoDrivers(
        volume_cm3=v, surface_area_cm2=6 * size ** 2 / 100, bbox_mm=(size, size, size),
        bbox_volume_cm3=v, hull_volume_cm3=v, nominal_wall_mm=size / 3, face_count=12,
        max_bbox_mm=size, is_valid=True, rotational=False, rot_axis_len_mm=size,
        rot_cross_dia_mm=size, sheet_gauge_mm=size, planar_aspect=1.0,
        outline_perimeter_mm=4 * size, bend_count=0, sheet_like=False,
        billet_bbox_mm=billet or (size, size, size), billet_basis="oriented candidate",
        bbox_precision_mm=precision)


_PP = MaterialProfile("PP (Molded)", [], 0.5, None, None, None, 0.9, 2.0)
_TI = MaterialProfile("Ti6Al4V", [], 0.4, None, None, None, 4.43, 350.0)


def _tool(drivers):
    est = cost_breakdown(PT.INJECTION_MOLDING, drivers, _PP, "polymer", 1000, build_rate_card(), "US")
    return next(d.value for d in est.drivers if d.name == "tooling_cost")


def test_stl_rounding_allowance_does_not_lift_the_tool_tier():
    error = 2.6428997918226276e-05          # the 300 mm STL cube's coordinate error
    padded = 300.0 + 2 * error
    stl = _drivers(300.0, precision=2 * error, billet=(padded, padded, padded))
    step = _drivers(300.0)
    assert _tool(stl) == _tool(step) == pytest.approx(30000.0)
    # a part that really is longer still moves up
    assert _tool(_drivers(300.1)) == pytest.approx(60000.0)


@pytest.mark.parametrize("process", [PT.DED, PT.WAAM])
def test_deposition_minimum_is_per_order_not_per_ten_part_lot(process):
    rates = build_rate_card()
    small = _drivers(10.0)
    one = cost_breakdown(process, small, _TI, "titanium", 1, rates, "US")
    many = cost_breakdown(process, small, _TI, "titanium", 1000, rates, "US")
    minimum = rates.min_charge(process)
    assert one.unit_cost_usd == pytest.approx(minimum)          # one part still pays the minimum
    assert many.unit_cost_usd < minimum / 10                    # was held at minimum / 10 a part
    assert "min_charge_floor" not in many.line_items
