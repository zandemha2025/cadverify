"""The price per part never rises with quantity (M14).

Setups were counted per started lot (ceil), so 50 parts on 20-part plates
paid three whole setups and cost more each than 20 parts (FDM $18.00 at 20,
$18.09 at 50; SLA $173.23 at 2, $174.28 at 5).
"""

from __future__ import annotations

import pytest

from src.analysis.models import ProcessType as PT
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import COSTED_PROCESSES, build_rate_card
from src.profiles.models import MaterialProfile

QTY = (1, 2, 5, 10, 20, 50, 100, 150, 200, 500, 1000, 2000, 5000, 10000, 20000)
_MAT = {"polymer": MaterialProfile("PA12 (Nylon 12)", [], 0.7, None, None, None, 1.01, 60.0),
        "aluminum": MaterialProfile("6061-T6 Aluminum", [], 0.5, None, None, None, 2.7, 5.0)}


def _drivers(size=30.0) -> GeoDrivers:
    v = size ** 3 / 1000
    return GeoDrivers(
        volume_cm3=v, surface_area_cm2=6 * size ** 2 / 100, bbox_mm=(size, size, size),
        bbox_volume_cm3=v, hull_volume_cm3=v, nominal_wall_mm=size / 3, face_count=12,
        max_bbox_mm=size, is_valid=True, rotational=False, rot_axis_len_mm=size,
        rot_cross_dia_mm=size, sheet_gauge_mm=size, planar_aspect=1.0,
        outline_perimeter_mm=4 * size, bend_count=0, sheet_like=False)


@pytest.mark.parametrize("process", sorted(COSTED_PROCESSES, key=lambda p: p.value))
def test_unit_cost_is_non_increasing_in_quantity(process):
    rates = build_rate_card()
    cls = "polymer" if process in (PT.FDM, PT.SLA, PT.DLP, PT.SLS, PT.MJF, PT.INJECTION_MOLDING) else "aluminum"
    prices = [cost_breakdown(process, _drivers(), _MAT[cls], cls, q, rates, "US").unit_cost_usd for q in QTY]
    rises = [(a, b, pa, pb) for (a, pa), (b, pb) in zip(zip(QTY, prices), zip(QTY[1:], prices[1:]))
             if pb > pa + 1e-6]
    assert not rises, rises
