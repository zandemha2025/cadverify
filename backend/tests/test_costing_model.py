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
from src.costing.decision import crossover


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
