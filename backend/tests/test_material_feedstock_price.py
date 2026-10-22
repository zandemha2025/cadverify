"""Each process is priced at the material form it buys (W11).

A material file lists prices by form: 316L is $5/kg as bar, $100/kg as powder
and $4/kg as sheet. A metal printer buys powder, a mill buys bar, a press brake
buys sheet. Pricing a metal printer at the bar price made aluminum DMLS dearer
than stainless DMLS and stainless deposition dearer than titanium.
"""

from __future__ import annotations

import pytest

from src.analysis.models import ProcessType as PT
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import GeoDrivers
from src.costing.rates import build_rate_card
from src.costing.routing import select_material
from src.profiles.database import get_materials_for_process
from src.profiles.models import MaterialProfile
from src.profiles.pricing import feedstock_price, priced_for


def _row(process, name):
    return next(m for m in get_materials_for_process(process) if m.name == name)


def test_316l_is_priced_at_the_form_each_process_buys():
    assert (_row(PT.DMLS, "SS316L").cost_per_kg, _row(PT.DMLS, "SS316L").price_form) == (100.0, "powder")
    assert (_row(PT.SLM, "SS316L").cost_per_kg, _row(PT.SLM, "SS316L").price_form) == (100.0, "powder")
    assert (_row(PT.BINDER_JET, "SS316L").cost_per_kg, _row(PT.BINDER_JET, "SS316L").price_form) == (100.0, "powder")
    assert (_row(PT.CNC_3AXIS, "SS316L").cost_per_kg, _row(PT.CNC_3AXIS, "SS316L").price_form) == (5.0, "wrought")
    assert (_row(PT.SHEET_METAL, "SS316L").cost_per_kg, _row(PT.SHEET_METAL, "SS316L").price_form) == (4.0, "sheet")


def test_inconel_printing_pays_powder_not_bar():
    assert _row(PT.DMLS, "Inconel 718").cost_per_kg == 400.0
    assert _row(PT.CNC_3AXIS, "Inconel 718").cost_per_kg == 50.0


def test_hardcoded_rows_carry_their_form():
    assert _row(PT.DMLS, "AlSi10Mg").price_form == "powder"
    assert _row(PT.FDM, "PETG").price_form == "filament"
    assert _row(PT.SLA, "Standard Resin").price_form == "resin"
    assert _row(PT.SHEET_METAL, "5052 Aluminum (Sheet)").price_form == "sheet"


def test_deposition_borrowed_pool_is_powder_priced():
    for process in (PT.DED, PT.WAAM):
        mat = select_material(process, "stainless", build_rate_card())
        assert mat is not None
        assert mat.price_form == "powder" and mat.cost_per_kg >= 80.0, (process, mat.name, mat.cost_per_kg)


def test_a_printer_gets_no_price_from_a_file_without_powder():
    bar_only = MaterialProfile("Bar-only alloy", [PT.DMLS, PT.CNC_3AXIS], 0.4, None, None, None, 8.0, 6.0,
                               cost_per_kg_by_form={"wrought": 6.0}, price_form="wrought")
    assert feedstock_price(bar_only, PT.DMLS) == (None, None)
    assert feedstock_price(bar_only, PT.CNC_3AXIS) == (6.0, "wrought")
    # a row without forms keeps its one price everywhere (hand-built materials)
    plain = MaterialProfile("Plain", [PT.DMLS], 0.4, None, None, None, 4.43, 350.0)
    assert priced_for(plain, PT.DMLS) is plain


def _drivers() -> GeoDrivers:
    return GeoDrivers(
        volume_cm3=27.0, surface_area_cm2=54.0, bbox_mm=(30.0, 30.0, 30.0),
        bbox_volume_cm3=27.0, hull_volume_cm3=27.0, nominal_wall_mm=10.0,
        face_count=12, max_bbox_mm=30.0, is_valid=True, rotational=False,
        rot_axis_len_mm=30.0, rot_cross_dia_mm=30.0, sheet_gauge_mm=30.0,
        planar_aspect=1.0, outline_perimeter_mm=120.0, bend_count=0,
        sheet_like=False)


@pytest.mark.parametrize("process", [PT.DMLS, PT.SLM, PT.DED, PT.WAAM])
@pytest.mark.parametrize("qty", [1, 100, 10000])
def test_metal_additive_price_order_titanium_stainless_aluminum(process, qty):
    rates = build_rate_card()
    unit = {}
    for cls in ("aluminum", "stainless", "titanium"):
        mat = select_material(process, cls, rates)
        assert mat is not None, (process, cls)
        unit[cls] = cost_breakdown(process, _drivers(), mat, cls, qty, rates, "US").unit_cost_usd
    assert unit["titanium"] >= unit["stainless"] >= unit["aluminum"], (process, qty, unit)
    if qty >= 100:
        # above the order minimum the feedstock shows: strictly dearer
        assert unit["titanium"] > unit["stainless"] > unit["aluminum"], (process, qty, unit)
