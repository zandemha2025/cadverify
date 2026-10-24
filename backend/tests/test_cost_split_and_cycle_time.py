"""The cost split adds up, and a tiny part's machine time is never 0 (C11).

At qty 1 a CNC price read "fixed $70 + variable $26.37" against a $139.68 unit
price: the order's first setup and first-article inspection were in neither
figure. And a 2 mm part's deposition time rounded to "0.0 h".
"""

from __future__ import annotations

import pytest

from src.analysis.models import ProcessType as PT
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import COSTED_PROCESSES, build_rate_card
from src.profiles.models import MaterialProfile


def _drivers(size=30.0) -> GeoDrivers:
    v = size ** 3 / 1000
    return GeoDrivers(
        volume_cm3=v, surface_area_cm2=6 * size ** 2 / 100, bbox_mm=(size, size, size),
        bbox_volume_cm3=v, hull_volume_cm3=v, nominal_wall_mm=size / 3,
        face_count=12, max_bbox_mm=size, is_valid=True, rotational=False,
        rot_axis_len_mm=size, rot_cross_dia_mm=size, sheet_gauge_mm=size,
        planar_aspect=1.0, outline_perimeter_mm=4 * size, bend_count=0, sheet_like=False)


_AL = MaterialProfile("6061-T6 Aluminum", [], 0.5, None, None, None, 2.7, 5.0)


def _driver(est, name):
    return next((d for d in est.drivers if d.name == name), None)


@pytest.mark.parametrize("qty", [1, 7, 100, 10000])
def test_cnc_fixed_over_qty_plus_variable_is_the_unit_price(qty):
    rc = build_rate_card()
    est = cost_breakdown(PT.CNC_3AXIS, _drivers(), _AL, "aluminum", qty, rc, "US")
    assert est.fixed_cost_usd / qty + est.variable_cost_usd == pytest.approx(est.unit_cost_usd, abs=2e-4)
    # the one-time part is programming + the order's first setup + first article
    labor = rc.g("labor_rate")
    one_time_hr = rc.pget(PT.CNC_3AXIS, "nre_hr") + rc.p(PT.CNC_3AXIS, "setup_hr") + rc.pget(PT.CNC_3AXIS, "fai_hr")
    assert est.fixed_cost_usd >= one_time_hr * labor * 0.99


@pytest.mark.parametrize("process", sorted(COSTED_PROCESSES, key=lambda p: p.value))
def test_every_process_split_adds_up_at_qty_1_and_100(process):
    rc = build_rate_card()
    for qty in (1, 100):
        est = cost_breakdown(process, _drivers(), _AL, "aluminum", qty, rc, "US")
        assert est.fixed_cost_usd >= 0 and est.variable_cost_usd >= 0, process
        assert est.fixed_cost_usd / qty + est.variable_cost_usd == pytest.approx(est.unit_cost_usd, abs=2e-4)


@pytest.mark.parametrize("process", [PT.DED, PT.WAAM, PT.CNC_3AXIS])
def test_tiny_part_cycle_time_is_never_zero(process):
    est = cost_breakdown(process, _drivers(2.0), _AL, "aluminum", 1, build_rate_card(), "US")
    assert _driver(est, "cycle_time").value > 0
