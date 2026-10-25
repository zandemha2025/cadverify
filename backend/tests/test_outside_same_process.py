"""In-house is compared with a job shop running the same process (oo-24).

A flat aluminum plate made on the shop's Haas VF-2 was compared only with
routes the shop doesn't own (5-axis milling outside at twice the price), so the
"saving" was fiction: nobody sends a plate out for 5-axis. The outside side now
also prices each in-house process as an outside shop runs it (its fully loaded
rate), and says so.
"""
from __future__ import annotations

import trimesh

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.makeability import ShopCaps

from tests.test_owned_machine_answers import _catalog_cap
from tests.test_costing_model import _analyze


def _plate_report():
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[120.0, 80.0, 12.0]))
    opts = EstimateOptions(quantities=[1, 50], material_class="aluminum", material_class_is_user=True,
                           inventory=(_catalog_cap("Haas VF-2"),), shop_caps=ShopCaps(ops={}))
    return report_to_dict(estimate_decision(result, mesh, feats, opts))


def test_outside_side_includes_the_same_process_at_a_job_shop():
    rep = _plate_report()
    options = rep["decision"]["options"]
    assert options, "the VF-2 clears the plate"
    for q, o in options.items():
        assert o["in_house"]["process"] == "cnc_3axis"
        outside = o["outside"]
        assert outside is not None
        # The cheapest outside way to mill a plate is a 3-axis mill, not a 5-axis one.
        assert outside["process"] != "cnc_5axis", (q, outside)
        if outside["process"] == "cnc_3axis":
            assert outside.get("same_process") is True
            # A job shop's fully loaded rate costs more than your machine's marginal one.
            assert outside["unit_cost_usd"] > o["in_house"]["unit_cost_usd"]


def test_the_estimates_list_keeps_one_price_per_process_and_quantity():
    rep = _plate_report()
    keys = [(e["process"], e["quantity"]) for e in rep["estimates"]]
    assert len(keys) == len(set(keys))
