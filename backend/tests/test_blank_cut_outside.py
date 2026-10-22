"""A press brake with no cutting machine bends in-house; the blank is cut outside (me-02).

The shop side (D1) passes ``blank_outside`` in the press brake's machine override when
the shop declares no laser, punch, plasma or waterjet. The engine then prices the brake's
bends at the brake's rate and the cut and handling as its own "Blank cut outside" line.
"""

from __future__ import annotations

import pytest

from src.analysis.models import ProcessType as PT
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.footing import foot
from src.costing.quantity_model import model_at
from src.costing.rates import build_rate_card
from src.costing.routing import select_material


def _bracket():
    # 120 × 80 × 2 mm steel blank, 400 mm of outline to cut, two bends
    return GeoDrivers(
        volume_cm3=19.2, surface_area_cm2=197.6, bbox_mm=(2.0, 80.0, 120.0), bbox_volume_cm3=19.2,
        hull_volume_cm3=19.2, nominal_wall_mm=2.0, face_count=12, max_bbox_mm=120.0, is_valid=True,
        rotational=False, rot_axis_len_mm=120.0, rot_cross_dia_mm=80.0, sheet_gauge_mm=2.0,
        planar_aspect=40.0, outline_perimeter_mm=400.0, bend_count=2, sheet_like=True,
        sheet_blank_mm=(2.0, 80.0, 120.0), billet_bbox_mm=(2.0, 80.0, 120.0), billet_basis="oriented candidate")


def _price(override, qty=100):
    rates = build_rate_card()
    mat = select_material(PT.SHEET_METAL, "steel", rates)
    return cost_breakdown(PT.SHEET_METAL, _bracket(), mat, "steel", qty, rates, "US", machine_override=override)


def test_brake_only_shop_has_a_blank_cut_outside_line():
    brake = {"hourly_rate_usd": 60.0, "capital_frac": 0.0, "machine_name": "Amada HG", "blank_outside": True}
    e = _price(brake)
    # cut 400 mm ÷ 4,000 mm/min = 0.1 min + handling 1.2 min = 0.0217 hr × $45/hr (the card's cell rate)
    cut_hr = (400 / 4000) / 60 + 0.020
    assert e.line_items["blank_outside"] == pytest.approx(cut_hr * 45.0, abs=1e-4)
    # the brake runs the bends alone: 2 × 20 s at its own $60/hr
    assert e.line_items["machine"] == pytest.approx(2 * 20 / 3600 * 60.0, abs=1e-4)
    d = next(x for x in e.drivers if x.name == "blank_outside_cost")
    assert "no laser, punch, plasma or waterjet" in d.source
    f = foot(e.line_items, e.unit_cost_usd)
    assert f["is_rounding"]
    assert model_at(e.qty_model, 100) == pytest.approx(e.unit_cost_usd, abs=1e-3)


def test_brake_and_laser_shop_cuts_in_house():
    with_cutter = {"hourly_rate_usd": 60.0, "capital_frac": 0.0, "machine_name": "Amada HG"}
    e = _price(with_cutter)
    assert "blank_outside" not in e.line_items
    assert all(x.name != "blank_outside_cost" for x in e.drivers)
    assert "blank_outside" not in _price(None).line_items


def test_estimate_passes_the_flag_from_the_fitted_machine():
    """The verification's resource carries the shop side's flag into the machine override."""
    import inspect

    from src.costing import estimate

    src = inspect.getsource(estimate._build_verification)
    assert 'res.get("blank_outside")' in src and '"blank_outside": True' in src
