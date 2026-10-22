"""Make on a tie (op-07): a buy price that is lower is never "Make in-house", and a
true tie (within 2% of what you pay) is "Either: no saving" and adds nothing to
the headline. The 25 x 18.8 x 12.5 mm stainless spacer (RFS-21012) gets no
wire-arc or deposition price, like the 20 mm block (e791c14)."""
from __future__ import annotations

import trimesh

from src.services import catalog_run_service as cr
from tests.test_deposition_size_floor import DEPOSITION, _analyze, _catalog_cap


def _row(price, make=26.17, low=22.0):
    row = {"bucket": "in_house", "reason": "On your Haas VF-2 · SS316L", "route": {"machine": "Haas VF-2"},
           "make": None, "buy": None, "saving": None, "could_make": None, "unit_cost_usd": make,
           "total_cost_usd": make * 500, "hours_each": 0.3, "hours_total": 150.0, "used_kg_total": 1.0,
           "material": {"name": "SS316L"}, "marginal": True, "machine_rate_usd": 55.25}
    opt = {"in_house": {"process": "cnc_3axis", "machine": "Haas VF-2", "unit_cost_usd": make, "low_usd": low,
                        "high_usd": make * 1.2},
           "outside": {"process": "cnc_3axis", "unit_cost_usd": 38.55, "same_process": True},
           "pick": "in_house", "basis": "in_house_cheapest"}
    price_dict = {"usd_each": price, "source": "parts_list", "text": f"${price:.2f} each"} if price else None
    cr.decide_make_or_buy(row, result={}, opt=opt, price=price_dict, qty=500, est=None)
    return row


def test_a_lower_price_paid_today_is_never_made_in_house_even_inside_the_range():
    # RFS-21039 at 100: make $33.92 against $33.05 paid; inside its range, it used to stay in-house.
    row = _row(33.05, make=33.92, low=29.0)
    assert row["bucket"] == "outside" and row["saving"] is None
    assert row["reason"].startswith("Could make in-house at $33.92")


def test_a_true_tie_is_either_way_no_saving_and_stays_bought():
    row = _row(26.50)  # make $26.17: within 2% of $26.50
    assert row["tie"] is True and row["bucket"] == "outside" and row["saving"] is None
    assert row["reason"] == "Either: no saving: making it on your Haas VF-2 costs $26.17, within 2% of what you pay"
    answer = cr.make_or_buy_answer([row, _row(33.05, make=26.17)])
    assert (answer["make"], answer["buy"], answer["ties"], answer["saving_usd"]) == (1, 1, 1, 3440.0)
    # Cheaper to make by more than 2%: made, with its saving.
    made = _row(33.05)
    assert made["bucket"] == "in_house" and made["saving"]["total"] == 3440.0 and not made.get("tie")


def test_the_rule_is_said_on_the_board():
    assert "never made in-house" in cr.BUCKET_RULE and "Within 2% of each other" in cr.BUCKET_RULE
    assert "range" not in cr.BUCKET_RULE


def test_the_25mm_stainless_spacer_gets_no_deposition_price():
    from src.costing import EstimateOptions, estimate_decision, report_to_dict
    from src.costing.makeability import ShopCaps

    result, mesh, feats = _analyze(trimesh.creation.box(extents=[25.0, 18.8, 12.5]))
    opts = EstimateOptions(quantities=[1, 100, 500], material_class="stainless", material_class_is_user=True)
    opts.inventory = (_catalog_cap("Haas VF-2"),)
    opts.shop_caps = ShopCaps(ops={})
    rep = report_to_dict(estimate_decision(result, mesh, feats, opts))
    priced = {e["process"] for e in rep["estimates"]}
    assert not priced & set(DEPOSITION), priced
    feas = {f["process"]: f for f in rep["engine_feasibility"]}
    for pv in DEPOSITION:
        assert "this part: 25 mm" in (feas[pv].get("cost_exclusion_reason") or "")
    for q, rec in rep["decision"]["recommendation"].items():
        assert rec["process"] not in DEPOSITION, (q, rec)
