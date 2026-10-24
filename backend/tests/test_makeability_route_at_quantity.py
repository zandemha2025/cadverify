"""The Make or buy tab names the machine of yours and prices at the part's quantity (oo-14).

The tab listed rib-plate and bracket.step "On your machines" as "Sheet metal"
(the make-now route, a process the shop doesn't own) and showed most parts at
a flat $30.00 with no quantity (the first estimate, at 1). A row now carries
the route at its own quantity: the yearly volume a catalog run declared, else
the record's smallest quantity above one, with the machine of yours when the
engine keeps it in-house.
"""
from __future__ import annotations

from src.services.catalog_service import route_at_quantity

RESULT = {"decision": {
    "recommendation": {
        "1": {"process": "fdm", "material": "PLA", "unit_cost_usd": 30.0, "in_house": False},
        "40": {"process": "sheet_metal", "material": "Mild Steel", "unit_cost_usd": 5.74, "in_house": False},
        "100": {"process": "cnc_3axis", "material": "Mild Steel", "unit_cost_usd": 20.0, "in_house": True,
                "machine": "Haas VF-2"},
    },
    "options": {
        "40": {"in_house": {"process": "cnc_3axis", "machine": "Haas VF-2", "material": "Mild Steel", "unit_cost_usd": 38.92},
               "pick": "outside"},
        "100": {"in_house": {"process": "cnc_3axis", "machine": "Haas VF-2", "material": "Mild Steel", "unit_cost_usd": 20.0},
                "pick": "in_house"},
    },
}}


def test_the_declared_yearly_volume_sets_the_quantity_and_names_your_machine():
    r = route_at_quantity(RESULT, 40)
    assert (r["qty"], r["basis"], r["process"], r["usd"], r["in_house"]) == (40, "declared", "sheet_metal", 5.74, False)
    assert r["owned"] == {"process": "cnc_3axis", "machine": "Haas VF-2", "material": "Mild Steel", "usd": 38.92}


def test_without_a_volume_the_smallest_quantity_above_one():
    r = route_at_quantity(RESULT, None)
    assert (r["qty"], r["basis"]) == (40, "record")
    r = route_at_quantity(RESULT, 7)  # not a quantity the record priced
    assert r["qty"] == 40
    assert route_at_quantity({}, 40) is None
    inside = route_at_quantity(RESULT, 100)
    assert inside["in_house"] is True and inside["machine"] == "Haas VF-2"


def test_an_in_house_part_without_a_priced_side_still_names_the_machine():
    result = {"decision": {"recommendation": {"10": {"process": "sheet_metal", "unit_cost_usd": 4.0}}},
              "verification": {"resource": {"process": "cnc_3axis", "machine": "Haas VF-2"}}}
    r = route_at_quantity(result, None)
    assert r["owned"] == {"process": "cnc_3axis", "machine": "Haas VF-2", "material": None, "usd": None}


def test_what_you_pay_today_decides_make_or_buy_on_the_tab_too():
    # The engine keeps the part in-house at 100 ($20.00 on your VF-2), but you pay $12.00: buy.
    r = route_at_quantity(RESULT, 100, {"usd_each": 12.0, "source": "parts_list"})
    assert r["in_house"] is False and r["buy_price"] == {"usd_each": 12.0, "source": "parts_list"}
    # You pay $45.00 at 40: the engine would buy sheet metal at $5.74, but against your price, make it.
    r = route_at_quantity(RESULT, 40, {"usd_each": 45.0, "source": "you"})
    assert r["in_house"] is True
