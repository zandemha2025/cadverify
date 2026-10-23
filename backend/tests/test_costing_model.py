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
import pytest

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


def test_feasibility_keeps_uncosted_blockers_and_marks_actual_estimates():
    result, mesh, feats = _analyze(_small_block())
    for strict in (False, True):
        report = estimate_decision(result, mesh, feats,
                                   EstimateOptions(quantities=[50], strict_dfm=strict))
        costed = {e["process"] for e in report.estimates}
        assert {f["process"] for f in report.engine_feasibility if f["costed"]} == costed
        for score, row in zip(result.process_scores, report.engine_feasibility):
            assert row["blockers"] == [i.message for i in score.issues if i.severity == "error"]
        turning = next(f for f in report.engine_feasibility if f["process"] == "cnc_turning")
        assert not turning["costed"] and turning["blockers"]

    result.geometry.is_watertight = False
    refused = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[50]))
    assert refused.status == "GEOMETRY_INVALID"
    assert not any(f["costed"] for f in refused.engine_feasibility)


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


def test_setup_is_once_per_order_on_a_machine():
    """de-19: a machine is set up once and runs the whole order, so its setup is
    shared over the actual quantity (it read "shared over 1,000" at the 100-off
    share, paying a setup every 100 parts)."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100, 200, 1000]))
    totals = {q: _driver(_est(report, "cnc_3axis", q), "setup_cost")["value"] * q for q in (100, 200, 1000)}
    # (each value is rounded to 4 decimals a part, so allow that times the quantity)
    assert abs(totals[200] - totals[100]) < 0.02 and abs(totals[1000] - totals[100]) < 0.1, totals
    assert "once for the order" in _driver(_est(report, "cnc_3axis", 1000), "setup_cost")["source"]


def test_region_split_material_not_labor_scaled():
    """#4 + E-now #2: material scales with region_material (~0.98); the MACHINE
    line scales by the capital/labor SPLIT — only the operator-labor share
    (machine_labor_frac) of the blended machine rate follows region_labor
    (CN 0.55); the capital/facility/energy share stays a global commodity (×1).
    So the machine multiplier is NOT the raw 0.55 (that whole-rate discount was
    the M8 bug), and commodity material is still not discounted like labor."""
    from src.costing.rates import build_rate_card
    rc = build_rate_card()
    frac = rc.g("machine_labor_frac")
    rl_cn = rc.region_labor("CN")
    expected_mach = (1.0 - frac) + frac * rl_cn      # capital global ×1 + labor share ×rl
    result, mesh, feats = _analyze(_bulky_block())
    us = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], region="US"))
    cn = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], region="CN"))
    us_sls = _est(us, "sls", 100)
    cn_sls = _est(cn, "sls", 100)
    mat_ratio = cn_sls["line_items"]["material"] / us_sls["line_items"]["material"]
    mach_ratio = cn_sls["line_items"]["machine"] / us_sls["line_items"]["machine"]
    assert abs(mat_ratio - 0.98) < 0.02, mat_ratio
    assert abs(mach_ratio - expected_mach) < 0.02, mach_ratio
    # the split makes the offshore machine discount LESS aggressive than the raw
    # regional-labor factor (the fixed M8 bug over-discounted it all the way to 0.55)
    assert mach_ratio > rl_cn + 0.02, (mach_ratio, rl_cn)
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


@pytest.mark.parametrize("length,tier", [
    (49.9, "S"), (50, "M"), (149.9, "M"), (150, "L"),
    (300, "L"), (300.0001, "XL"), (300.1, "XL"), (400, "XL"),
])
def test_tooling_size_tiers_follow_the_part_not_file_axes(length, tier):
    from math import pi
    from src.analysis.models import ProcessType as PT
    from src.costing.cost_model import cost_breakdown
    from src.costing.drivers import extract_drivers
    from src.costing.rates import build_rate_card
    from src.costing.routing import select_material

    rates = build_rate_card()
    # The longest side of this solid cuboid is known independently of its pose.
    base = {"S": 6000, "M": 15000, "L": 30000, "XL": 60000}[tier]
    tools_seen = []
    for angle, axis in [(0, (0, 0, 1)), (pi/4, (0, 0, 1)), (.73, (1, 2, 3))]:
        mesh = trimesh.creation.box(extents=(length, 12, 12))
        mesh.apply_transform(trimesh.transformations.rotation_matrix(angle, axis))
        drivers = extract_drivers(analyze_geometry(mesh), mesh)
        for process, material_class, multiplier in [
            (PT.INJECTION_MOLDING, "polymer", 1), (PT.DIE_CASTING, "aluminum", 1.5),
            (PT.SAND_CASTING, "aluminum", .35), (PT.INVESTMENT_CASTING, "aluminum", .9),
            (PT.FORGING, "steel", 2),
        ]:
            material = select_material(process, material_class, rates)
            estimate = cost_breakdown(process, drivers, material, material_class, 100, rates, "US")
            tool = next(d for d in estimate.drivers if d.name == "tooling_cost")
            assert tool.value == pytest.approx(base * multiplier), (length, angle, process, tool)
            tools_seen.append(tool)
            estimate.assert_sums()
    for tool in tools_seen:
        assert f"size tier {tier}" in tool.source and "the smallest box found around the part" in tool.source
        assert f"{float(length)}mm" in tool.source
        assert "typical value, not confirmed by a shop" in tool.source


def test_every_estimate_carries_its_material_mass_as_fields():
    # Round 7 item 7: the part's mass, the mass the price is charged on, the
    # density and the $/kg as fields, the same figures the derivation names.
    import re

    report = estimate_decision(*_analyze(_bulky_block()),
                               EstimateOptions(quantities=[1, 100], material_class="aluminum"))
    assert report.estimates
    for e in report.estimates:
        m = e["material_mass"]
        assert set(m) == {"part_kg", "used_kg", "density_g_cm3", "usd_per_kg"}
        assert m["part_kg"] == pytest.approx(30.0 * m["density_g_cm3"] / 1000.0, rel=1e-3)  # 30 cm³
        src = _driver(e, "material_cost")["source"]
        said = re.search(r"=\s*(\d+(?:\.\d+)?)\s*kg\s*×\s*\$(\d+(?:\.\d+)?)/kg", src)
        assert said, src
        assert m["used_kg"] == pytest.approx(float(said.group(1)), abs=5e-5)
        assert m["usd_per_kg"] == pytest.approx(float(said.group(2)))
    mill = _est(report, "cnc_3axis", 1)["material_mass"]
    assert mill["used_kg"] > mill["part_kg"]  # the billet, not the part


def test_a_tiny_part_never_reads_zero_kg():
    # 2 mm cube: 8 mm³ of plastic is a hundredth of a gram.
    report = estimate_decision(*_analyze(trimesh.creation.box(extents=[2.0, 2.0, 2.0])),
                               EstimateOptions(quantities=[1], material_class="polymer"))
    assert report.estimates
    for e in report.estimates:
        m = e["material_mass"]
        assert m["part_kg"] > 0 and m["used_kg"] > 0, (e["process"], m)
        assert "0.0000 kg" not in _driver(e, "material_cost")["source"], e["process"]
    from src.costing.cost_model import kg_text
    assert (kg_text(0.0136), kg_text(0.0000412), kg_text(0.00085)) == ("0.0136", "0.0000412", "0.000850")


def _small_and_big_at_10000(process):
    small = trimesh.creation.box(extents=[40.0, 30.0, 20.0])
    big = trimesh.creation.box(extents=[80.0, 60.0, 40.0])
    est = {}
    for name, mesh in (("small", small), ("big", big)):
        report = estimate_decision(*_analyze(mesh), EstimateOptions(quantities=[10000], material_class="aluminum"))
        est[name] = _est(report, process, 10000)
        assert est[name] is not None
    mat = [_driver(est[k], "material_cost")["value"] for k in ("small", "big")]
    assert mat[1] / mat[0] == pytest.approx(8.0, rel=0.01)
    assert est["big"]["material_mass"]["used_kg"] / est["small"]["material_mass"]["used_kg"] == pytest.approx(8.0, rel=0.01)
    return est


@pytest.mark.parametrize("process", ["sand_casting", "investment_casting"])
def test_a_casting_twice_the_size_pays_8x_the_metal_more_of_its_mould_and_more_fettling(process):
    # Round 7 item 5 found a 2x casting at 10,000 barely dearer: the pour and 0.6 h of
    # fettling were per piece at any size. Round 14: published cost structure (Boothroyd
    # Dewhurst, Sand / Investment Casting Cost Estimating) spreads a mould or tree over
    # the castings it holds and fettles a small casting for $0.50-2.00, a large one for
    # hours. A mould holds fewer of the bigger casting, and its fettling follows its surface.
    est = _small_and_big_at_10000(process)
    machine = [_driver(est[k], "machine_cost")["value"] for k in ("small", "big")]
    labor = [_driver(est[k], "labor_cost") for k in ("small", "big")]
    assert machine[1] > 2 * machine[0]
    assert labor[1]["value"] > labor[0]["value"]
    assert "it follows the surface, mass to the 2/3 power" in labor[0]["source"]
    assert "castings a " in _driver(est["small"], "cycle_time")["source"]
    assert est["big"]["unit_cost_usd"] > 1.05 * est["small"]["unit_cost_usd"]


def test_a_forging_twice_the_size_pays_8x_the_metal_and_the_same_per_piece_time():
    # A forging is a press stroke and a trim a piece (a 20-120 s cycle set by complexity:
    # Boothroyd Dewhurst, Forging Cost Estimating); its cleanup is per piece too, and the
    # labor line says so in words.
    est = _small_and_big_at_10000("forging")
    labor = [_driver(est[k], "labor_cost") for k in ("small", "big")]
    assert labor[0]["value"] == labor[1]["value"]
    assert "per piece, the same time at any size" in labor[0]["source"]
    assert est["big"]["unit_cost_usd"] > 1.05 * est["small"]["unit_cost_usd"]


def _forging_at_10000(extents, options=None):
    report = estimate_decision(*_analyze(trimesh.creation.box(extents=extents)),
                               options or EstimateOptions(quantities=[10000], material_class="steel"))
    e = _est(report, "forging", 10000)
    assert e is not None
    return e


def test_a_forging_is_priced_on_the_press_it_needs():
    # Press tonnage follows the forging's size, geometry, material and complexity, and
    # the press it needs sets the hourly cost (Boothroyd Dewhurst, Forging Cost
    # Estimating). Steel: a small block needs 214 t, a 100 mm square 1,228 t, a 300 mm
    # square 9,529 t (plan with the flash land × 120 MPa × shape factor 8).
    prices, press_cost = [], []
    for extents, press, rate in (([40.0, 30.0, 20.0], "500 t", 80), ([100.0, 100.0, 40.0], "2,500 t", 220),
                                 ([300.0, 300.0, 60.0], "16,000 t", 730)):
        e = _forging_at_10000(extents)
        mach = _driver(e, "machine_cost")
        assert f"(forging and trim 0.0111 hr × ${rate}/hr on the {press} press + heating " in mach["source"]
        assert f"the {press} press, ${rate}/hr" in _driver(e, "cycle_time")["source"]
        heat_hr = e["material_mass"]["used_kg"] * 2.5 / 60
        assert mach["value"] == pytest.approx(heat_hr * 120 + 40 / 3600 * rate, abs=1e-3)
        prices.append(e["unit_cost_usd"])
        press_cost.append(mach["value"] - heat_hr * 120)
    assert prices[0] < prices[1] < prices[2]
    assert press_cost[0] < press_cost[1] < press_cost[2]


def test_a_rate_table_published_before_the_press_keys_prices_every_forging_on_one_press():
    import copy
    import re

    from src.costing.rates import RATE_CARD_V0
    from src.analysis.models import ProcessType as PT

    table = copy.deepcopy(RATE_CARD_V0)
    forging = table["process"][PT.FORGING]
    new_keys = r"press\d+_(t|rate)|flow_mpa_\w+|flash_land_mm|press_shape_factor"
    for key in [k for k in forging if re.fullmatch(new_keys, k)]:
        forging.pop(key)
    forging.update(press_hr=0.05, trim_hr=0.03)
    for extents in ([40.0, 30.0, 20.0], [300.0, 300.0, 60.0]):
        e = _forging_at_10000(extents, EstimateOptions(quantities=[10000], material_class="steel",
                                                       base_rate_table=table))
        mach = _driver(e, "machine_cost")
        heat_hr = e["material_mass"]["used_kg"] * 2.5 / 60
        assert mach["value"] == pytest.approx((heat_hr + 0.08) * 120, abs=1e-3)
        assert " × $120/hr" in mach["source"] and " t press" not in mach["source"]


def _t_overhang():
    """A 10 × 10 × 20 mm post with a 40 × 10 × 4 mm bar across its top: the bar's
    underside overhangs 15 mm each side (supported as drawn, none upside down)."""
    post = trimesh.creation.box(extents=[10.0, 10.0, 20.0])
    post.apply_translation([0, 0, 10.0])
    bar = trimesh.creation.box(extents=[40.0, 10.0, 4.0])
    bar.apply_translation([0, 0, 22.0])
    return trimesh.boolean.union([post, bar], engine="manifold")


def test_fdm_finishing_follows_the_support_to_remove():
    """de-21: support removal is most of a small FDM part's finishing; with nothing to
    support only the handling is left (it was a flat 0.2 h either way)."""
    rates_mesh = _t_overhang()
    upright = estimate_decision(*_analyze(rates_mesh), EstimateOptions(quantities=[100]))
    flipped_mesh = rates_mesh.copy()
    flipped_mesh.apply_transform(trimesh.transformations.rotation_matrix(3.141592653589793, [1, 0, 0]))
    flipped = estimate_decision(*_analyze(flipped_mesh), EstimateOptions(quantities=[100]))
    up = _driver(_est(upright, "fdm", 100), "labor_cost")
    down = _driver(_est(flipped, "fdm", 100), "labor_cost")
    assert "support removal 0.004hr/cm²" in up["source"]
    assert "no support to remove" in down["source"]
    assert up["value"] > down["value"] * 1.1
    # Handling alone: 0.1 h a part (plus the plate's share), not 0.2 h.
    assert down["value"] < 0.11 * 35 * 1.5


def test_deposited_metal_is_priced_with_its_finish_machining():
    """de-20: WAAM and DED parts are near-net: finished on a 3-axis mill, priced as the
    mill prices it, with its setup and programming once for the order."""
    report = estimate_decision(*_analyze(_bulky_block()), EstimateOptions(quantities=[1, 100], material_class="aluminum"))
    for proc in ("waam", "ded"):
        e = _est(report, proc, 100)
        if e is None:
            continue
        d = _driver(e, "finish_machining")
        assert d is not None and "3-axis mill" in d["source"] and "once for the order" in d["source"]
        assert e["fixed_cost_usd"] >= (0.75 + 2.0) * 35 * 0.99


def test_dmls_and_slm_say_why_they_price_alike():
    """de-20: two makers' names for laser powder-bed fusion, one price, said so."""
    report = estimate_decision(*_analyze(_small_block()), EstimateOptions(quantities=[10], material_class="stainless"))
    for proc in ("dmls", "slm"):
        e = _est(report, proc, 10)
        if e is None:
            continue
        assert "two makers' names for laser powder-bed fusion" in _driver(e, "machine_cost")["source"]
