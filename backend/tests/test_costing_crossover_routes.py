"""A low-volume winner is not necessarily the tooling competitor at volume."""
from types import SimpleNamespace

import pytest

from src.costing.decision import make_vs_buy


@pytest.mark.parametrize("numerical", [False, True])
def test_tooling_must_beat_every_eligible_make_route(numerical):
    curves = {"fdm": (0, 10), "mjf": (100, 3), "injection_molding": (2000, 1)}
    cost = lambda pv, q: curves[pv][0] / q + curves[pv][1]
    quantities = [1, 50, 5000]
    estimates = {(pv, q): SimpleNamespace(
        process=pv, material="test", unit_cost_usd=cost(pv, q),
        fixed_cost_usd=fixed, variable_cost_usd=variable,
        dfm_ready=pv != "injection_molding", dfm_verdict="pass",
        dfm_blockers=["insufficient draft"] if pv == "injection_molding" else [],
    ) for pv, (fixed, variable) in curves.items() for q in quantities}
    options = {"unit_cost_fn": cost} if numerical else {}
    decision = make_vs_buy(estimates, quantities, {}, **options)
    assert decision.make_now_process == "fdm"
    assert decision.recommendation[50]["process"] == "mjf"
    assert decision.crossover_qty == pytest.approx(950, abs=1)
    assert "fdm stays cheapest" not in decision.note
    assert "qty 50: mjf" in decision.note
    assert "requires redesign" in decision.note

    # An environment exclusion or failed DFM removes the cheaper make route.
    excluded = make_vs_buy(estimates, quantities, {}, excluded_pv={"mjf"}, **options)
    assert excluded.crossover_qty == pytest.approx(2000 / 9, abs=1)
    for (pv, q), estimate in estimates.items():
        if pv == "mjf":
            estimate.dfm_ready = False
    failed = make_vs_buy(estimates, quantities, {}, **options)
    assert failed.crossover_qty == excluded.crossover_qty

    curves["mjf"] = (100, 1)  # tooling can never beat this route at any volume
    for (pv, q), estimate in estimates.items():
        if pv == "mjf":
            estimate.dfm_ready = True
            estimate.variable_cost_usd = 1
            estimate.unit_cost_usd = cost(pv, q)
    assert make_vs_buy(estimates, quantities, {}, **options).crossover_qty is None


def test_no_crossover_does_not_claim_one_route_wins_every_quantity():
    cost = lambda pv, q: 10 if pv == "fdm" else 100 / q + 3
    quantities = [1, 50]
    estimates = {(pv, q): SimpleNamespace(
        process=pv, material="test", unit_cost_usd=cost(pv, q),
        fixed_cost_usd=0 if pv == "fdm" else 100,
        variable_cost_usd=10 if pv == "fdm" else 3,
        dfm_ready=True, dfm_verdict="pass", dfm_blockers=[],
    ) for pv in ("fdm", "mjf") for q in quantities}
    decision = make_vs_buy(estimates, quantities, {}, unit_cost_fn=cost)
    assert decision.crossover_qty is None
    assert "cheapest at every quantity" not in decision.note
    assert "qty 1: fdm" in decision.note and "qty 50: mjf" in decision.note


@pytest.mark.parametrize("make_pv,tool_pv", [
    ("wire_edm", "sand_casting"), ("dmls", "investment_casting"),
    ("slm", "forging"), ("ebm", "injection_molding"),
    ("binder_jetting", "die_casting"), ("ded", "sand_casting"),
    ("waam", "forging"),
])
def test_metal_make_and_tooling_routes_participate_in_the_decision(make_pv, tool_pv):
    curves = {"cnc_5axis": (0, 10), make_pv: (0, 5), tool_pv: (2000, 1)}
    cost = lambda pv, q: curves[pv][0] / q + curves[pv][1]
    quantities = [1, 1000]
    estimates = {(pv, q): SimpleNamespace(
        process=pv, material="metal", unit_cost_usd=cost(pv, q),
        fixed_cost_usd=fixed, variable_cost_usd=variable,
        dfm_ready=True, dfm_verdict="pass", dfm_blockers=[],
    ) for pv, (fixed, variable) in curves.items() for q in quantities}

    decision = make_vs_buy(estimates, quantities, {}, unit_cost_fn=cost)
    assert decision.make_now_process == make_pv
    assert decision.recommendation[1]["process"] == make_pv
    assert decision.tooling_process == tool_pv
    assert decision.crossover_qty == 500
    assert decision.if_redesigned[1000]["caveat"] == "invest in tooling"

    excluded = make_vs_buy(estimates, quantities, {}, unit_cost_fn=cost, excluded_pv={make_pv})
    assert excluded.make_now_process == "cnc_5axis"
    assert excluded.crossover_qty == 223
    for (pv, _), estimate in estimates.items():
        if pv == make_pv:
            estimate.dfm_ready = False
    blocked = make_vs_buy(estimates, quantities, {}, unit_cost_fn=cost)
    assert blocked.make_now_process == "cnc_5axis"
    assert blocked.crossover_qty == excluded.crossover_qty
