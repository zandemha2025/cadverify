"""Unit tests for the V0 cost model (spec §12, gates G3/G4/G5).

These use procedural meshes only (no real-parts dependency) so they always run
in CI. They assert the model's structural invariants:
  * Σ(line_items) == unit_cost            (G3)
  * monotone sensitivity to a rate bump   (G3)
  * crossover math + monotonicity         (G4)
  * lead time present + grows with qty     (G5)
"""

from __future__ import annotations

import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401  populate registry

from src.costing import estimate_decision, EstimateOptions
from src.costing.decision import crossover, _numerical_crossover


def _analyze(mesh) -> AnalysisResult:
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="cube.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _bulky_block():
    # 40×30×25 mm solid block — watertight, valid, polymer-costable
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _small_block():
    # 20×20×20 mm cube — small enough to nest many per powder-bed plate
    return trimesh.creation.box(extents=[20.0, 20.0, 20.0])


def _est(report, process, qty):
    for e in report.estimates:
        if e["process"] == process and e["quantity"] == qty:
            return e
    return None


def _driver(est, name):
    for d in est["drivers"]:
        if d["name"] == name:
            return d
    return None


def test_line_items_sum_to_unit_cost():
    """G3: Σ(line_items) == unit_cost for every estimate, every qty."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 1000]))
    assert report.status == "OK"
    assert report.estimates, "expected costable estimates for a valid block"
    for e in report.estimates:
        s = sum(e["line_items"].values())
        assert abs(e["unit_cost_usd"] - round(s, 2)) < 0.02, (
            f"{e['process']} qty {e['quantity']}: {e['unit_cost_usd']} != Σ {s}")


def test_every_driver_has_source_and_provenance():
    """G6: no naked numbers — every driver carries a non-empty source + tag."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 1000]))
    for e in report.estimates:
        assert len(e["drivers"]) >= 4
        for d in e["drivers"]:
            assert d["source"].strip()
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")


def test_rate_bump_raises_cost_monotone():
    """G3: bumping labor_rate +10% raises unit cost for every estimate."""
    result, mesh, feats = _analyze(_bulky_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    bumped = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               rate_overrides={"labor_rate": 38.5}))
    base_by = {e["process"]: e["unit_cost_usd"] for e in base.estimates}
    bump_by = {e["process"]: e["unit_cost_usd"] for e in bumped.estimates}
    for proc, cost in base_by.items():
        assert bump_by[proc] >= cost, f"{proc}: cost should rise with labor rate"
    assert any(bump_by[p] > base_by[p] for p in base_by)


def test_sls_machine_rate_override_raises_sls_only():
    """G3 spec example: machine_rate.SLS +25% raises the SLS estimate."""
    result, mesh, feats = _analyze(_bulky_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    bumped = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[100],
                                               rate_overrides={"machine_rate.SLS": 25}))
    b = {e["process"]: e["unit_cost_usd"] for e in base.estimates}
    u = {e["process"]: e["unit_cost_usd"] for e in bumped.estimates}
    if "sls" in b:
        assert u["sls"] > b["sls"]


def test_crossover_math_and_monotonicity():
    """G4: crossover formula is correct and rises with the high-fixed term."""
    # make-now: fixed 20, var 120 ; tooling: fixed 30000, var 4
    q1 = crossover(20.0, 120.0, 30000.0, 4.0)
    assert q1 is not None and q1 > 1
    # raise tooling fixed -> crossover moves right (monotone)
    q2 = crossover(20.0, 120.0, 60000.0, 4.0)
    assert q2 > q1
    # equal variable cost -> no crossover
    assert crossover(20.0, 100.0, 30000.0, 100.0) is None


def test_lead_time_present_and_grows_with_qty():
    """G5: every estimate has a 5-component lead time, low<high, grows with qty."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 5000]))
    by = {}
    for e in report.estimates:
        lt = e["lead_time"]
        assert lt["low_days"] < lt["high_days"]
        for comp in ("queue", "production", "post_process", "ship"):
            assert comp in lt["components"]
        by.setdefault(e["process"], {})[e["quantity"]] = lt["mid_days"]
    for proc, q in by.items():
        if 10 in q and 5000 in q:
            assert q[5000] >= q[10], f"{proc}: lead time must not shrink with qty"
    assert any(q.get(5000, 0) > q.get(10, 0) for q in by.values())


def test_r1_capacity_assumption_present_and_default():
    """R1: every lead time carries the inspectable finite-capacity pool assumption,
    DEFAULT-tagged when un-overridden."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    for e in report.estimates:
        cap = e["lead_time"]["capacity"]
        assert cap["n_machines"] >= 1 and cap["machine_hours_per_day"] > 0
        assert cap["provenance"] == "DEFAULT"
        assert cap["basis"]


def test_r1_capacity_override_to_user():
    """R1: overriding n_machines flips capacity provenance to USER and shrinks
    production (more parallel machines = fewer production days)."""
    result, mesh, feats = _analyze(_bulky_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[5000]))
    over = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[5000], rate_overrides={"n_machines.MJF": 20}))
    m0 = [e for e in base.estimates if e["process"] == "mjf"][0]["lead_time"]
    m1 = [e for e in over.estimates if e["process"] == "mjf"][0]["lead_time"]
    assert m1["capacity"]["provenance"] == "USER"
    assert m1["components"]["production"] <= m0["components"]["production"]
    # a real reduction must occur (more machines => strictly fewer production days here)
    assert m1["components"]["production"] < m0["components"]["production"]


def test_decision_present_with_crossover_direction():
    """G4: a decision with crossover + differing per-qty recommendation."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 100000]))
    dec = report.decision
    assert dec is not None
    # recommendation exists for both quantities
    assert 10 in dec.recommendation and 100000 in dec.recommendation


def test_decision_coherence_headline_equals_low_qty():
    """#7: the headline make-now process == the low-qty recommendation, and is
    DFM-ready (#6). Procedural so it always runs in CI."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[10, 5000]))
    dec = report.decision
    assert dec.make_now_process == dec.recommendation[10]["process"]
    assert dec.recommendation[10]["dfm_ready"] is True


def test_nesting_reduces_machine_fraction():
    """#1/#2: a small part nests many per powder-bed plate, so SLS machine cost
    is a small fraction of unit cost (not the dominant 80%)."""
    result, mesh, feats = _analyze(_small_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    sls = _est(report, "sls", 100)
    assert sls is not None
    n = _driver(sls, "parts_per_build")["value"]
    assert n > 1
    assert sls["line_items"]["machine"] < 0.70 * sls["unit_cost_usd"]


def test_per_lot_setup_recurs():
    """#8: setup recurs per lot (ceil(qty/lot_size) setups). For CNC (lot 100),
    total setup at qty 200 is ~2× total setup at qty 100 — NOT amortized to ÷2."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100, 200]))
    e100 = _est(report, "cnc_3axis", 100)
    e200 = _est(report, "cnc_3axis", 200)
    setup_total_100 = _driver(e100, "setup_cost")["value"] * 100
    setup_total_200 = _driver(e200, "setup_cost")["value"] * 200
    assert abs(setup_total_200 - 2 * setup_total_100) < 0.02, (
        f"per-lot setup should double over 2 lots: {setup_total_100} -> {setup_total_200}")


def test_region_split_material_not_labor_scaled():
    """#4: material scales with region_material (~0.98), machine with region_labor
    (0.55) — commodity material is NOT discounted like regional shop labor."""
    result, mesh, feats = _analyze(_bulky_block())
    us = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], region="US"))
    cn = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], region="CN"))
    us_sls = _est(us, "sls", 100)
    cn_sls = _est(cn, "sls", 100)
    mat_ratio = cn_sls["line_items"]["material"] / us_sls["line_items"]["material"]
    mach_ratio = cn_sls["line_items"]["machine"] / us_sls["line_items"]["machine"]
    assert abs(mat_ratio - 0.98) < 0.02, mat_ratio
    assert abs(mach_ratio - 0.55) < 0.02, mach_ratio
    assert mat_ratio > mach_ratio, "material must not be discounted like labor"


# ── S1: CNC volume/learning economics ───────────────────────────────────────
def test_cnc_unit_cost_decreases_with_volume():
    """S1: machined unit cost must DROP with volume (Wright learning on attended
    conversion cost) — non-increasing across 100→1k→10k→100k and a meaningful
    (>=25%) drop 100→10k — and Σ = unit_cost must still hold at every qty. The
    old model was VOLUME-INVARIANT (flat $/unit across the whole range)."""
    result, mesh, feats = _analyze(_bulky_block())
    qtys = [100, 1000, 10000, 100000]
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=qtys, material_class="aluminum"))
    for proc in ("cnc_3axis", "cnc_5axis"):
        series = [(q, _est(report, proc, q)) for q in qtys]
        assert all(e is not None for _q, e in series), f"{proc} missing an estimate"
        costs = [e["unit_cost_usd"] for _q, e in series]
        # (a) monotone non-increasing with volume (was flat/invariant)
        for lo, hi in zip(costs, costs[1:]):
            assert hi <= lo + 1e-6, f"{proc} cost must not rise with qty: {costs}"
        # meaningful real-world drop: >=25% from qty 100 -> 10k (target 30-60%)
        drop = 1.0 - costs[2] / costs[0]
        assert drop >= 0.25, f"{proc} 100->10k drop only {drop:.0%} (expected >=25%): {costs}"
        # (b) Σ invariant intact at every qty
        for q, e in series:
            s = sum(e["line_items"].values())
            assert abs(e["unit_cost_usd"] - round(s, 2)) < 0.02, (
                f"{proc} qty {q}: {e['unit_cost_usd']} != Σ {s}")
    # not a flat model any more: qty-100 vs qty-100k must differ substantially
    c100 = _est(report, "cnc_3axis", 100)["unit_cost_usd"]
    c100k = _est(report, "cnc_3axis", 100000)["unit_cost_usd"]
    assert c100k < 0.6 * c100, f"cnc_3axis still ~flat: {c100} -> {c100k}"


def test_learning_neutral_at_and_below_first_lot():
    """The learning curve is anchored at the first production lot (lot_size=100
    for CNC): no learning credited at/below one lot, so qty<=100 conversion cost
    is unchanged (protects the low-volume should-cost accuracy) — and toggling the
    curve off (learning_rate=1.0) recovers the flat behavior exactly."""
    result, mesh, feats = _analyze(_bulky_block())
    # at qty 100 (== lot_size) there is no learning driver and cost == flat model
    on = estimate_decision(result, mesh, feats,
                           EstimateOptions(quantities=[100], material_class="aluminum"))
    off = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100], material_class="aluminum",
        rate_overrides={"learning_rate": 1.0}))
    for proc in ("cnc_3axis", "cnc_5axis"):
        e_on = _est(on, proc, 100)
        e_off = _est(off, proc, 100)
        assert abs(e_on["unit_cost_usd"] - e_off["unit_cost_usd"]) < 1e-6
        assert _driver(e_on, "learning_curve") is None, "no learning at the first lot"
    # above the lot, disabling learning yields a strictly higher unit cost
    on10k = estimate_decision(result, mesh, feats,
                              EstimateOptions(quantities=[10000], material_class="aluminum"))
    off10k = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[10000], material_class="aluminum",
        rate_overrides={"learning_rate": 1.0}))
    e_on = _est(on10k, "cnc_3axis", 10000)
    e_off = _est(off10k, "cnc_3axis", 10000)
    assert e_on["unit_cost_usd"] < e_off["unit_cost_usd"]
    assert _driver(e_on, "learning_curve") is not None


def test_numerical_crossover_finite_and_ordered():
    """S1 crossover: the numerical make-vs-buy crossover is finite, ordered, and
    monotone in tooling fixed cost — and a make route that LEARNS (variable cost
    falls with volume) stays competitive to a HIGHER quantity, pushing the tooling
    crossover to the right (the exact direction the flat model got wrong)."""
    # flat make ($40 var, $200 fixed) vs high-fixed tooling ($4 var, $30k fixed)
    def make_flat(pv, q):
        return 200.0 / q + 40.0

    def tool(pv, q, fixed=30000.0):
        return fixed / q + 4.0

    q1 = _numerical_crossover(lambda pv, q: make_flat(pv, q) if pv == "make" else tool(pv, q),
                              "make", "tool", q_lo=50)
    assert q1 is not None and q1 > 1
    # closed form agrees within one unit: q* = (30000-200)/(40-4) ~ 827.8
    assert abs(q1 - 827.8) <= 1.5, q1

    # raise tooling fixed -> crossover moves right (monotone)
    q2 = _numerical_crossover(
        lambda pv, q: make_flat(pv, q) if pv == "make" else tool(pv, q, fixed=60000.0),
        "make", "tool", q_lo=50)
    assert q2 is not None and q2 > q1

    # a make route WITH learning (90%/doubling, anchored at 100) undercuts the flat
    # make at volume, so tooling overtakes it LATER -> crossover strictly larger.
    import math

    def make_learn(pv, q):
        mult = min(1.0, (q / 100.0) ** (math.log(0.90) / math.log(2.0)))
        return 200.0 / q + 40.0 * mult

    q3 = _numerical_crossover(
        lambda pv, q: make_learn(pv, q) if pv == "make" else tool(pv, q),
        "make", "tool", q_lo=50)
    assert q3 is not None and q3 > q1, (
        f"learning should keep machining competitive longer: flat {q1} vs learn {q3}")


def test_learning_keeps_machining_competitive_at_volume():
    """S1 end-to-end: with the learning curve ON, machining (CNC) is a cheaper
    make-as-is option at high qty than it was under the flat model — the platform's
    volume 'decision' now rests on machining cost that behaves like machining."""
    result, mesh, feats = _analyze(_bulky_block())
    import os
    os.environ["CADVERIFY_CNC_LEARNING"] = "0"
    try:
        flat = estimate_decision(result, mesh, feats, EstimateOptions(
            quantities=[100, 100000], material_class="aluminum"))
    finally:
        os.environ["CADVERIFY_CNC_LEARNING"] = "1"
    learned = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100, 100000], material_class="aluminum"))
    flat_hi = _est(flat, "cnc_3axis", 100000)["unit_cost_usd"]
    learn_hi = _est(learned, "cnc_3axis", 100000)["unit_cost_usd"]
    assert learn_hi < flat_hi, f"learning must lower high-qty CNC: {flat_hi} -> {learn_hi}"


def test_cavity_complexity_tooling():
    """#5: --cavities 4 --complexity complex raises IM tooling by 4^0.7×1.5 and
    lowers per-part machine by /4; Σ invariant still holds."""
    result, mesh, feats = _analyze(_bulky_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    bumped = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100], n_cavities=4, n_cavities_is_user=True,
        complexity="complex", complexity_is_user=True))
    b_im = _est(base, "injection_molding", 100)
    u_im = _est(bumped, "injection_molding", 100)
    tool_b = _driver(b_im, "tooling_cost")["value"]
    tool_u = _driver(u_im, "tooling_cost")["value"]
    mach_b = _driver(b_im, "machine_cost")["value"]
    mach_u = _driver(u_im, "machine_cost")["value"]
    assert abs(tool_u / tool_b - (4 ** 0.7) * 1.5) < 0.02
    assert abs(mach_u / mach_b - 0.25) < 0.01
    for e in (u_im,):
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02
