"""A machine the shop owns that clears every check is weighed against outside routes.

Feedback item 15: an account with a Bambu Lab X1C that fits a small plastic
bracket was told to buy the part outside, because the recommendation was the
cheapest route by a margin well inside the estimate's own uncertainty. The
decision now compares the cheapest in-house route with the cheapest outside
route at every quantity (``Decision.options``) and applies ``IN_HOUSE_RULE``.
In-house lead time runs on the shop's own declared machines, with no shipping.
"""
from __future__ import annotations

import trimesh

from src.analysis.models import ProcessType
from src.costing import EstimateOptions, estimate_decision, report_to_dict
from src.costing.decision import IN_HOUSE_RULE, prefer_in_house
from src.costing.leadtime import lead_time
from src.costing.makeability import MachineCap
from src.costing.rates import build_rate_card

from tests.test_costing_model import _analyze

QTYS = [1, 100, 1000]


def _bracket():
    """60×40×30 mm plastic L-bracket with two holes (19.2 cm³)."""
    plate = trimesh.creation.box(extents=[60, 40, 5])
    plate.apply_translation([0, 0, 2.5])
    upright = trimesh.creation.box(extents=[60, 5, 30])
    upright.apply_translation([0, 17.5, 15])
    m = trimesh.boolean.union([plate, upright], engine="manifold")
    for x in (-18, 18):
        hole = trimesh.creation.cylinder(radius=3, height=20, sections=48)
        hole.apply_translation([x, -5, 2.5])
        m = trimesh.boolean.difference([m, hole], engine="manifold")
    return m


def _x1c(count=1, materials=("PLA", "PETG")):
    return MachineCap(process="fdm", name="Bambu Lab X1C", count=count, max_workpiece_kg=None,
                      hourly_rate_usd=None, capital_frac=None, materials=tuple(materials),
                      capabilities={"x": 256, "y": 256, "z": 256})


def _report(inventory=(), owned=frozenset({ProcessType.FDM})):
    result, mesh, feats = _analyze(_bracket())
    opts = EstimateOptions(quantities=list(QTYS), inventory=tuple(inventory),
                           owned_processes=owned if inventory else frozenset())
    return report_to_dict(estimate_decision(result, mesh, feats, opts))


def _side(cost, low=None, lead=(5.0, 9.0), process="x"):
    return {"process": process, "unit_cost_usd": cost, "low_usd": cost * 0.6 if low is None else low,
            "lead_low_days": lead[0], "lead_high_days": lead[1]}


# ── the rule itself ───────────────────────────────────────────────────────────
def test_rule_keeps_the_owned_machine_inside_the_estimate_range():
    inside = _side(15.66, low=9.40, lead=(4.9, 9.1))
    assert prefer_in_house(inside, None) == ("in_house", "in_house_only")
    assert prefer_in_house(inside, _side(20.0)) == ("in_house", "in_house_cheapest")
    assert prefer_in_house(inside, _side(12.16, lead=(5.6, 10.4))) == ("in_house", "in_house_within_range")
    # Below the low end of the in-house range: outside is cheaper beyond doubt.
    assert prefer_in_house(inside, _side(9.39, lead=(5.6, 10.4))) == ("outside", "outside_cheaper")
    # Cheaper and its slowest delivery beats the in-house quickest.
    slow = _side(15.58, low=9.35, lead=(42.7, 79.3))
    assert prefer_in_house(slow, _side(12.07, lead=(7.0, 13.0))) == ("outside", "outside_sooner")
    # Faster outside but dearer: the owned machine stays the pick.
    assert prefer_in_house(slow, _side(16.0, lead=(7.0, 13.0))) == ("in_house", "in_house_cheapest")


def test_rule_is_stated_in_words():
    assert "low end of the in-house" in IN_HOUSE_RULE and "sooner" in IN_HOUSE_RULE


# ── in-house lead time ────────────────────────────────────────────────────────
def test_in_house_lead_time_runs_on_the_shops_own_machines_and_ships_nothing():
    rates = build_rate_card()
    outside = lead_time(ProcessType.FDM, 1.31, 100, rates)
    one = lead_time(ProcessType.FDM, 1.31, 100, rates, in_house={"machine": "Bambu Lab X1C", "count": 1})
    three = lead_time(ProcessType.FDM, 1.31, 100, rates, in_house={"machine": "Bambu Lab X1C", "count": 3})
    assert outside.capacity["n_machines"] == 12 and outside.components["ship"] > 0
    assert one.components["ship"] == 0 and one.components["queue"] == 0
    assert one.capacity["n_machines"] == 1 and one.capacity["in_house"] is True
    assert one.components["production"] == 6          # ceil(100 × 1.31 h ÷ (1 × 22 h/day))
    assert three.components["production"] == 2        # three printers share the run
    assert "Bambu Lab X1C" in one.capacity["basis"] and "no shipping" in one.capacity["basis"]


# ── the decision layer, on fixed estimates ────────────────────────────────────
def _est(process, q, unit, band=40.0):
    from src.costing.provenance import CostEstimate
    return CostEstimate(process=process, material="M", quantity=q, unit_cost_usd=unit,
                        fixed_cost_usd=0.0, variable_cost_usd=unit, drivers=[], line_items={"x": unit},
                        est_error_band_pct=band, dfm_ready=True, dfm_verdict="issues")


def _lt(lo, hi):
    from src.costing.leadtime import LeadTime
    return LeadTime(process="x", quantity=1, low_days=lo, high_days=hi, mid_days=(lo + hi) / 2)


def test_make_vs_buy_weighs_the_owned_route_at_each_quantity():
    from src.costing.decision import make_vs_buy

    # fdm on your X1C; mjf outside. Numbers as the engine gave for the bracket.
    ests = {("fdm", 100): _est("fdm", 100, 15.66), ("mjf", 100): _est("mjf", 100, 12.16),
            ("fdm", 1000): _est("fdm", 1000, 15.58), ("mjf", 1000): _est("mjf", 1000, 12.07),
            ("fdm", 5000): _est("fdm", 5000, 25.0), ("mjf", 5000): _est("mjf", 5000, 12.0)}
    lts = {("fdm", 100): _lt(4.9, 9.1), ("mjf", 100): _lt(5.6, 10.4),
           ("fdm", 1000): _lt(42.7, 79.3), ("mjf", 1000): _lt(7.0, 13.0),
           ("fdm", 5000): _lt(5.0, 9.0), ("mjf", 5000): _lt(6.0, 11.0)}
    owned = {"fdm": {"machine": "Bambu Lab X1C", "count": 1}}
    base = make_vs_buy(ests, [100, 1000, 5000], lts)
    assert base.recommendation[100]["process"] == "mjf" and not base.options  # before: cheapest only
    d = make_vs_buy(ests, [100, 1000, 5000], lts, in_house=owned)
    assert (d.options[100]["pick"], d.options[100]["basis"]) == ("in_house", "in_house_within_range")
    rec = d.recommendation[100]
    assert (rec["process"], rec["in_house"], rec["machine"], rec["basis"]) == (
        "fdm", True, "Bambu Lab X1C", "in_house_within_range")
    assert (d.options[1000]["pick"], d.options[1000]["basis"]) == ("outside", "outside_sooner")
    assert d.recommendation[1000]["process"] == "mjf" and d.recommendation[1000]["in_house"] is False
    assert (d.options[5000]["pick"], d.options[5000]["basis"]) == ("outside", "outside_cheaper")
    assert d.options[100]["in_house"]["low_usd"] == round(15.66 * 0.6, 2)
    assert d.options[100]["outside"]["lead_high_days"] == 10.4
    assert d.make_now_process == "fdm" and d.rule == IN_HOUSE_RULE
    assert "Owned machines:" in d.note


# ── on the real cost path ─────────────────────────────────────────────────────
def test_an_owned_x1c_that_fits_puts_both_sides_on_the_answer():
    rep = _report(inventory=[_x1c()])
    dec = rep["decision"]
    assert rep["verification"]["per_route"]["fdm"]["verdict"] == "makeable_in_house"
    for q in QTYS:
        opt = dec["options"][q]
        rec = dec["recommendation"][q]
        assert opt["in_house"]["process"] == "fdm" and opt["in_house"]["machine"] == "Bambu Lab X1C"
        # The pick follows the stated rule applied to the two sides shown.
        assert (opt["pick"], opt["basis"]) == prefer_in_house(opt["in_house"], opt["outside"])
        side = opt["in_house"] if opt["pick"] == "in_house" else opt["outside"]
        assert (rec["process"], rec["unit_cost_usd"]) == (side["process"], side["unit_cost_usd"])
        fdm = next(e for e in rep["estimates"] if e["process"] == "fdm" and e["quantity"] == q)
        assert opt["in_house"]["low_usd"] == fdm["confidence"]["low_usd"]
        assert opt["in_house"]["lead_high_days"] == fdm["lead_time"]["high_days"]
        # made in your building: no shipping, and priced as owned (capital sunk)
        assert fdm["lead_time"]["components"]["ship"] == 0
        assert fdm.get("owned_in_house") is True
    assert dec["rule"] == IN_HOUSE_RULE
    assert dec["make_now_process"] == dec["recommendation"][1]["process"]


def test_an_owned_route_far_dearer_than_outside_goes_outside():
    result, mesh, feats = _analyze(_bracket())
    opts = EstimateOptions(quantities=[100], inventory=(_x1c(),),
                           rate_overrides={"machine_rate.FDM": 400.0})
    dec = report_to_dict(estimate_decision(result, mesh, feats, opts))["decision"]
    opt = dec["options"][100]
    assert opt["pick"] == "outside" and opt["basis"] in ("outside_cheaper", "outside_sooner")
    assert dec["recommendation"][100]["in_house"] is False
    assert dec["recommendation"][100]["process"] == opt["outside"]["process"]


def test_no_owned_machine_that_fits_leaves_the_decision_unchanged():
    base = _report()
    assert "options" not in base["decision"] and "rule" not in base["decision"]
    assert all("basis" not in r for r in base["decision"]["recommendation"].values())
    # A printer declared for other materials doesn't clear the check: same decision.
    other = _report(inventory=[_x1c(materials=("aluminum",))])
    assert other["verification"]["per_route"]["fdm"]["verdict"] != "makeable_in_house"
    assert other["decision"] == base["decision"]


def test_a_public_share_does_not_say_the_sharer_owns_a_machine():
    import json
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from src.services.cost_decision_service import sanitize_for_share

    rep = _report(inventory=[_x1c()])
    assert "Bambu Lab X1C" in rep["decision"]["note"]
    d = SimpleNamespace(filename="bracket.stl", file_type="stl", label=None,
                        created_at=datetime.now(timezone.utc),
                        make_now_process=rep["decision"]["make_now_process"],
                        crossover_qty=rep["decision"]["crossover_qty"],
                        quantities=QTYS, result_json=rep)
    body = sanitize_for_share(d)
    text = json.dumps(body)
    assert "Bambu Lab X1C" not in text and "Owned machines" not in text
    assert "options" not in body["decision"] and "rule" not in body["decision"]
    assert all({"in_house", "basis", "machine"}.isdisjoint(r) for r in body["decision"]["recommendation"].values())
    assert all("in_house" not in (e["lead_time"]["capacity"] or {}) for e in body["estimates"])
    # The printer's route is priced on the sharer's own machine (its rate, its
    # lead time with no shipping): it isn't in the copy. The pick is the engine's
    # own rule over the routes the copy shows, and its price is that route's.
    assert all(e["process"] != "fdm" for e in body["estimates"])
    rec = body["decision"]["recommendation"]
    pick = rec.get(100) or rec.get("100")
    from src.costing.decision import MAKE_NOW_FAMILIES
    from src.costing.rates import process_family

    shown = [e for e in body["estimates"] if e["quantity"] == 100 and e["dfm_ready"]
             and process_family(ProcessType(e["process"])) in MAKE_NOW_FAMILIES]
    cheapest = min(shown, key=lambda e: e["unit_cost_usd"])
    assert pick["process"] == cheapest["process"] and pick["unit_cost_usd"] == cheapest["unit_cost_usd"]
    assert body["make_now_process"] == (rec.get(1) or rec.get("1"))["process"]
    # A crossover computed against the in-house price isn't shown.
    assert body["decision"]["crossover_qty"] is None and body["crossover_qty"] is None
