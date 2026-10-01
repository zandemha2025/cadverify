"""Physical rate bounds apply to every path that builds a served rate card."""
import copy

import pytest

from src.costing.rates import RATE_CARD_V0, build_rate_card
from src.services.rate_library_service import validate_rate_table


@pytest.mark.parametrize("key,value", [
    ("labor_rate", -35), ("machine_rate.FDM", -1),
    ("material_price.@polymer", -1), ("margin", -2), ("overhead", -1),
    ("utilization", 0), ("utilization", 1.1), ("stock_allowance", .9),
    ("daily_machine_hours", 0), ("daily_machine_hours", 25),
    ("setup_hr.FDM", -1), ("labor_rate", float("nan")),
    ("machine_rate.FDM", float("inf")),
])
def test_user_and_shop_rates_reject_invalid_values(key, value):
    for kind in ("overrides", "shop_overrides"):
        with pytest.raises(ValueError):
            build_rate_card(**{kind: {key: value}})


@pytest.mark.parametrize("value", [-35, None, True, 10 ** 400])
def test_published_tables_cannot_bypass_rate_validation(value):
    table = copy.deepcopy(RATE_CARD_V0)
    table["global"]["labor_rate"] = value
    with pytest.raises(ValueError, match="labor_rate"):
        validate_rate_table(table)


def test_valid_free_rates_and_physical_boundaries_remain_usable():
    card = build_rate_card({"labor_rate": 0, "machine_rate.FDM": 0,
                           "material_price.@polymer": 0, "margin": 0,
                           "stock_allowance": 1, "utilization": .01,
                           "daily_machine_hours": 24})
    assert card.g("labor_rate") == 0
    assert card.g("utilization") == .01


def test_uncertainty_samples_stay_inside_physical_rate_bounds():
    from src.costing.ensemble import UNCERTAIN_COEFFICIENTS, build_member_overrides

    for overrides in build_member_overrides(UNCERTAIN_COEFFICIENTS, RATE_CARD_V0, 32):
        assert build_rate_card(overrides).g("stock_allowance") >= 1
