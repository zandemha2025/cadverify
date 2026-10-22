"""A cost engineer's hand arithmetic on pocket-block.step (round 11, C1).

Priyanka Shah rebuilt every line of the 60 × 40 × 20 mm steel pocket block with a
calculator. These tests put her arithmetic next to the engine's. The block is priced
from the same figures the engine measured on her file (CAD volume 37.9 cm³, area
106.92 cm², a 20 × 40 × 60 mm billet, Mild Steel at $1.2/kg) and the 0.2092 h
(0.209245 h unrounded) cycle the engine computed for it, at the v0 rate card
($35/h labor, $75/h 3-axis).
"""

from __future__ import annotations

import pytest

from src.analysis.models import ProcessType as PT
from src.costing import cost_model
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.learning import lot_average_factor
from src.costing.rates import build_rate_card
from src.costing.routing import select_material

CYCLE_HR = 0.209245      # her CSV: machine = 15.6934 = 0.209245 h × $75


def _pocket_block():
    return GeoDrivers(
        volume_cm3=37.9, surface_area_cm2=106.92, bbox_mm=(20.0, 40.0, 60.0),
        bbox_volume_cm3=48.0, hull_volume_cm3=48.0, nominal_wall_mm=7.09, face_count=179296,
        max_bbox_mm=60.0, is_valid=True, rotational=False, rot_axis_len_mm=60.0,
        rot_cross_dia_mm=44.7, billet_bbox_mm=(20.0, 40.0, 60.0), billet_basis="oriented candidate")


@pytest.fixture()
def block(monkeypatch):
    monkeypatch.setattr(cost_model, "_cnc_cycle",
                        lambda process, drivers, cls, rates: (CYCLE_HR, 0.1782, "her cycle"))
    rates = build_rate_card()
    mat = select_material(PT.CNC_3AXIS, "steel", rates)
    assert mat.name == "Mild Steel" and mat.cost_per_kg == pytest.approx(1.2)

    def at(qty, rates=rates):
        return cost_breakdown(PT.CNC_3AXIS, _pocket_block(), mat, "steel", qty, rates, "US")
    return at


def _driver(est, name):
    return next((d for d in est.drivers if d.name == name), None)


# ── ce-03: the learning curve ──────────────────────────────────────────────────

def test_lot_average_factor_is_her_formula():
    # ce-03: "the lot average for 1,000 parts is (100 + 100×(10^0.848−1)/0.848)/1000 = 0.81"
    assert lot_average_factor(0.9, 100, 0.25, 1000) == pytest.approx(0.813, abs=5e-4)
    # 10,000: (100 + 100 × (100^0.848 − 1) / 0.848) / 10,000 = 0.584 (the last part's factor is 0.497)
    assert lot_average_factor(0.9, 100, 0.25, 10000) == pytest.approx(0.5838, abs=5e-4)
    # nothing learns at or below the first lot
    assert lot_average_factor(0.9, 100, 0.25, 100) == 1.0
    assert lot_average_factor(0.9, 100, 0.25, 25) == 1.0
    # the integral of the unit curve agrees with summing the units one by one
    import math
    b = math.log2(0.9)
    units = sum(1.0 if x <= 100 else (x / 100) ** b for x in range(1, 10001)) / 10000
    assert lot_average_factor(0.9, 100, 0.25, 10000) == pytest.approx(units, abs=1e-4)


def test_machine_time_does_not_learn_at_10000(block):
    """ce-03: "Machine at 10,000 should stay 0.2092 h × $75 = $15.69 (+ tools $0.78)"."""
    e = block(10000)
    assert round(e.line_items["machine"], 2) == 15.69          # was $7.79 (× 0.497)
    assert round(e.line_items["consumables"], 2) == 0.78       # was $0.39
    assert "learning" not in _driver(e, "machine_cost").source


def test_touch_labor_pays_the_lot_average_at_1000_and_10000(block):
    """Labor and in-process inspection pay the order's average part, not its last part."""
    a1k = (100 + 100 * ((1000 / 100) ** 0.848 - 1) / 0.848) / 1000      # 0.813
    a10k = (100 + 100 * ((10000 / 100) ** 0.848 - 1) / 0.848) / 10000   # 0.584
    e1k, e10k = block(1000), block(10000)
    assert e1k.line_items["labor"] == pytest.approx(0.5 * 35 * a1k, abs=0.01)     # $14.23, was $12.33
    assert e10k.line_items["labor"] == pytest.approx(0.5 * 35 * a10k, abs=0.01)   # $10.22, was $8.69
    # inspection: first article 0.5 h once for the order + 0.03 h a part × the lot average
    assert e10k.line_items["inspection"] == pytest.approx((0.5 / 10000 + 0.03 * a10k) * 35, abs=0.005)
    lc = _driver(e10k, "learning_curve")
    assert lc.value == pytest.approx(a10k, abs=5e-4)
    assert "touch labor" in lc.source and "machine time" in lc.source and "De Jong" in lc.source


def test_unit_cost_at_10000_and_1000(block):
    """Her ce-03 figure, about $26.22 at 10,000, takes the learning off the machine line
    but keeps the 10,000th part's factor (×0.497) on labor (17.50 × 0.497 = 8.69).
    Paying the lot average on labor and inspection instead (×0.584) adds
    17.50 × (0.584 − 0.497) = $1.53 and 1.05 × 0.087 = $0.09: $27.84.

        material 0.52 + machine 15.69 + tools 0.78 + labor 10.22 + inspection 0.61
        + setup 0.75 × 35 ÷ 10,000 + programming 2 × 35 ÷ 10,000 = $27.84
    """
    assert round(block(10000).unit_cost_usd, 2) == 27.84       # was $17.93
    # 1,000: 0.52 + 15.69 + 0.78 + 14.23 + 0.87 + 0.03 + 0.07 = $32.20 (was $25.32)
    assert round(block(1000).unit_cost_usd, 2) == 32.20


def test_no_change_at_or_below_the_first_lot(block):
    """At 100 nothing learns: her $36.69 stands, and 25 is her $40.10."""
    assert round(block(100).unit_cost_usd, 2) == 36.69
    # ce-06: 0.52 + 15.69 + 17.50 + 0.78 + setup 26.25/25 = 1.05 + programming 70/25 = 2.80
    #        + inspection (0.5/25 + 0.03) × 35 = 1.75  →  $40.10
    assert round(block(25).unit_cost_usd, 2) == 40.10
