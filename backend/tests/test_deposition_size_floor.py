"""Wire-arc printing and metal deposition have a size floor (buyer-02).

A 20 x 15 x 10 mm aluminum block with a bore, 250 off, on a shop with a Haas
VF-2, was sent outside as "Wire-arc printing (WAAM) $3.68" (metal deposition
second): 4-8 mm beads and 3-5 mm of machining stock on every face for a 7 g
block. Nobody quotes that. Under each route's size floor the engine now
withholds the price with the reason, and the outside side is a job shop
milling it on a 3-axis mill.
"""
from __future__ import annotations

import trimesh

from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.makeability import ShopCaps

from tests.test_costing_model import _analyze
from tests.test_owned_machine_answers import _catalog_cap

DEPOSITION = ("waam", "ded")


def _bored_block():
    block = trimesh.creation.box(extents=[20.0, 15.0, 10.0])
    bore = trimesh.creation.cylinder(radius=3.0, height=12.0, sections=48)
    return block.difference(bore)


def _report(mesh, quantities=(1, 250, 1000), inventory=True):
    result, m, feats = _analyze(mesh)
    opts = EstimateOptions(quantities=list(quantities), material_class="aluminum", material_class_is_user=True)
    if inventory:
        opts.inventory = (_catalog_cap("Haas VF-2"),)
        opts.shop_caps = ShopCaps(ops={})
    return report_to_dict(estimate_decision(result, m, feats, opts))


def test_a_small_block_gets_no_deposition_price_and_says_why():
    rep = _report(_bored_block())
    priced = {e["process"] for e in rep["estimates"]}
    assert not priced & set(DEPOSITION), priced
    feas = {f["process"]: f for f in rep["engine_feasibility"]}
    for pv in DEPOSITION:
        why = feas[pv].get("cost_exclusion_reason") or ""
        assert "large near-net metal parts" in why, why
        assert "this part: 20 mm" in why, why
        assert "typical value, not confirmed by a shop" in why, why


def test_a_small_block_is_compared_with_a_job_shops_3_axis_mill():
    rep = _report(_bored_block())
    options = rep["decision"]["options"]
    for q in ("250", "1000"):
        side = options.get(q) or options.get(int(q))
        assert side["in_house"]["process"] == "cnc_3axis"
        out = side["outside"]
        assert out["process"] == "cnc_3axis" and out.get("same_process") is True, out
        assert side["pick"] == "in_house"
    for q, rec in rep["decision"]["recommendation"].items():
        assert rec["process"] not in DEPOSITION, (q, rec)
    assert "wire-arc" not in rep["decision"]["note"].lower()


def test_owned_machine_clause_prints_cents():
    note = _report(_bored_block())["decision"]["note"]
    clause = note[note.index("Owned machines: "):]
    import re
    prices = re.findall(r"\$([0-9,]+(?:\.[0-9]+)?) each", clause)
    assert prices and all(re.fullmatch(r"[0-9,]+\.[0-9]{2}", p) for p in prices), clause


def test_a_large_part_still_gets_wire_arc_and_deposition_prices():
    rep = _report(trimesh.creation.box(extents=[300.0, 200.0, 120.0]), quantities=(1, 10), inventory=False)
    priced = {e["process"] for e in rep["estimates"]}
    assert set(DEPOSITION) <= priced, priced
