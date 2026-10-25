"""Regression tests for environment-aware material routing."""

from src.analysis.models import ProcessType as PT
from src.costing.rates import build_rate_card
from src.costing.routing import select_material, select_sheet_material


def test_sour_service_stainless_prefers_nace_material_over_cheap_304():
    rates = build_rate_card()

    base = select_material(PT.CNC_3AXIS, "stainless", rates)
    sour = select_material(
        PT.CNC_3AXIS,
        "stainless",
        rates,
        env={"sour_service": True, "max_temp_c": 120},
    )

    assert base is not None and base.name == "304 Stainless"
    assert sour is not None
    assert sour.name == "API 13Cr"


def test_sour_service_sheet_stainless_prefers_nace_sheet_stock():
    rates = build_rate_card()

    base = select_sheet_material("stainless", rates)
    sour = select_sheet_material(
        "stainless",
        rates,
        env={"sour_service": True, "max_temp_c": 120},
    )

    # Unconstrained: the cheapest stainless sheet blank at its SHEET price
    # (316L's file lists sheet at the same $4/kg as 304; its $5 bar price no
    # longer stands in for sheet).
    assert base is not None and base.name in {"304 SS (Sheet)", "SS316L"}
    assert base.price_form == "sheet" and base.cost_per_kg == 4.0
    assert sour is not None and sour.name == "SS316L"


def test_environment_selector_keeps_invalid_pool_when_no_valid_material_exists():
    rates = build_rate_card()

    # Aluminum has no NACE-qualified candidate in the current profile library.
    # Keeping the pool lets the verification block cite the exclusion instead of
    # silently dropping the route.
    sour = select_material(PT.CNC_3AXIS, "aluminum", rates,
                           env={"sour_service": True})

    assert sour is not None
    assert sour.name == "6061-T6 Aluminum"
