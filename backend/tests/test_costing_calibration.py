"""Per-shop calibration tests (bucket #1) — SHOP-profile binding, persistence,
provenance flips, precedence, and the structural invariants that must survive.

Procedural meshes only (no real-parts dependency) so these always run in CI.
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
from src.costing.shop_profile import (
    ShopProfile, save_profile, load_profile, list_profiles, profile_path,
    resolve_shop,
)
from src.costing.rates import build_rate_card
from src.costing.provenance import Provenance


def _analyze(mesh):
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


def _block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


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


def _assumption(report, name):
    for a in report.assumptions:
        if a.name == name:
            return a
    return None


def _shop(**kw):
    base = dict(name="UnitTest Shop", region="US", labor_rate=60.0, margin=0.25,
                machine_rates={"SLS": 40, "CNC_3AXIS": 100},
                material_prices={"@polymer": 9.0},
                region_multipliers={"labor": 1.0, "material": 1.0, "tooling": 1.0})
    base.update(kw)
    return ShopProfile(**base)


# ── persistence ──────────────────────────────────────────────────────────────
def test_save_load_round_trip(tmp_path):
    p = _shop(name="Round Trip Co", notes="x", source="export")
    path = save_profile(p, store_dir=str(tmp_path))
    assert path == profile_path("Round Trip Co", str(tmp_path))
    loaded = load_profile("Round Trip Co", store_dir=str(tmp_path))
    assert loaded.name == p.name
    assert loaded.labor_rate == 60.0
    assert loaded.machine_rates["SLS"] == 40
    assert loaded.material_prices["@polymer"] == 9.0
    # list_profiles returns the slug ids; both the slug and the display name load
    assert "round-trip-co" in list_profiles(str(tmp_path))
    assert load_profile("round-trip-co", store_dir=str(tmp_path)).name == "Round Trip Co"


def test_load_by_explicit_path(tmp_path):
    p = _shop(name="Pathy")
    path = save_profile(p, store_dir=str(tmp_path))
    loaded = load_profile(path)              # absolute json path
    assert loaded.name == "Pathy"


def test_resolve_shop_forms(tmp_path):
    p = _shop(name="Resolvable")
    save_profile(p, store_dir=str(tmp_path))
    assert resolve_shop(None) is None
    assert resolve_shop(p) is p
    assert resolve_shop(p.to_dict()).name == "Resolvable"
    assert resolve_shop(load_profile("Resolvable", str(tmp_path))).name == "Resolvable"


# ── binding flips provenance DEFAULT -> SHOP ─────────────────────────────────
def test_shop_binding_flips_provenance_to_shop():
    result, mesh, feats = _analyze(_block())
    rep = estimate_decision(result, mesh, feats,
                            EstimateOptions(quantities=[100], shop=_shop()))
    sls = _est(rep, "sls", 100)
    assert sls is not None
    # machine rate is shop-bound -> SHOP; material (via @polymer) -> SHOP
    assert _driver(sls, "machine_cost")["provenance"] == "SHOP"
    assert _driver(sls, "material_cost")["provenance"] == "SHOP"
    # labor + margin come from the shop's global levers -> SHOP
    assert _assumption(rep, "labor_rate").provenance == Provenance.SHOP
    assert _assumption(rep, "margin").provenance == Provenance.SHOP


def test_unset_keys_stay_default():
    """A partially-calibrated shop leaves gaps visible: a process it never priced
    keeps a DEFAULT machine rate."""
    result, mesh, feats = _analyze(_block())
    # shop prices SLS only; CNC machine rate left unset
    sp = _shop(machine_rates={"SLS": 40})
    rep = estimate_decision(result, mesh, feats,
                            EstimateOptions(quantities=[100], shop=sp))
    sls = _est(rep, "sls", 100)
    cnc = _est(rep, "cnc_3axis", 100)
    assert _driver(sls, "machine_cost")["provenance"] == "SHOP"
    assert _driver(cnc, "machine_cost")["provenance"] == "DEFAULT"


# ── switching profiles visibly changes cost; Σ invariant holds ───────────────
def test_switching_profiles_changes_cost_and_sums():
    result, mesh, feats = _analyze(_block())
    cheap = _shop(name="Cheap", labor_rate=14, margin=0.05,
                  machine_rates={"SLS": 15})
    pricey = _shop(name="Pricey", labor_rate=80, margin=0.40,
                   machine_rates={"SLS": 60})
    r_default = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    r_cheap = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], shop=cheap))
    r_pricey = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], shop=pricey))
    c = _est(r_cheap, "sls", 100)["unit_cost_usd"]
    p = _est(r_pricey, "sls", 100)["unit_cost_usd"]
    d = _est(r_default, "sls", 100)["unit_cost_usd"]
    assert c < d < p, f"profile must move cost: cheap {c} < default {d} < pricey {p}"
    for rep in (r_default, r_cheap, r_pricey):
        for e in rep.estimates:
            s = round(sum(e["line_items"].values()), 2)
            assert abs(e["unit_cost_usd"] - s) < 0.02


# ── precedence: ad-hoc USER override beats the shop binding ───────────────────
def test_user_override_beats_shop():
    result, mesh, feats = _analyze(_block())
    rep = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100], shop=_shop(labor_rate=60),
        rate_overrides={"labor_rate": 99.0}))
    a = _assumption(rep, "labor_rate")
    assert a.value == 99.0
    assert a.provenance == Provenance.USER   # USER wins over SHOP


# ── material price: exact name wins over @class sentinel ─────────────────────
def test_material_price_exact_name_beats_class():
    rc = build_rate_card(shop_overrides={
        "material_price.@polymer": 5.0,
        "material_price.Delrin (POM)": 12.0,
    }, shop_name="X")
    price, prov, note = rc.material_price("Delrin (POM)", "polymer", 99.0)
    assert price == 12.0 and prov == Provenance.SHOP
    price2, prov2, _ = rc.material_price("PA12 (Nylon 12)", "polymer", 99.0)
    assert price2 == 5.0 and prov2 == Provenance.SHOP        # falls back to @polymer
    price3, prov3, _ = rc.material_price("Unpriced", "aluminum", 7.0)
    assert price3 == 7.0 and prov3 == Provenance.MEASURED    # generic DB fallback


# ── overhead / utilization: default no-op, non-default moves cost ────────────
def test_overhead_utilization_default_noop():
    result, mesh, feats = _analyze(_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    # a profile that only restates the defaults must not change any cost
    noop = _shop(name="Noop", labor_rate=35.0, margin=0.0, overhead=0.0,
                 utilization=1.0, machine_rates={}, material_prices={},
                 region_multipliers={})
    rep = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], shop=noop))
    b = {e["process"]: e["unit_cost_usd"] for e in base.estimates}
    n = {e["process"]: e["unit_cost_usd"] for e in rep.estimates}
    for proc in b:
        assert abs(b[proc] - n[proc]) < 0.02, f"{proc}: no-op profile changed cost"


def test_overhead_raises_conversion_cost():
    result, mesh, feats = _analyze(_block())
    base = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100]))
    over = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100], shop=_shop(name="OH", labor_rate=35.0, margin=0.0,
                                     overhead=0.20, machine_rates={},
                                     material_prices={}, region_multipliers={})))
    b = _est(base, "sls", 100)
    o = _est(over, "sls", 100)
    # machine + labor rise by ~20%; material (commodity) does NOT
    assert o["line_items"]["machine"] > b["line_items"]["machine"] * 1.19
    assert abs(o["line_items"]["material"] - b["line_items"]["material"]) < 0.01
    assert _assumption(over, "overhead").provenance == Provenance.SHOP


# ── region binding ───────────────────────────────────────────────────────────
def test_shop_region_binds_and_user_region_overrides():
    result, mesh, feats = _analyze(_block())
    cn = _shop(name="CN Shop", region="CN",
               region_multipliers={"labor": 1.0, "material": 0.98, "tooling": 0.45})
    rep = estimate_decision(result, mesh, feats, EstimateOptions(quantities=[100], shop=cn))
    assert rep.material_class == "polymer"
    # region selected by the shop -> region drivers tagged SHOP
    assert _assumption(rep, "region_material").provenance == Provenance.SHOP
    # an explicit caller region overrides the shop's region
    rep2 = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100], shop=cn, region="EU", region_is_user=True))
    assert _assumption(rep2, "region_material").provenance == Provenance.USER


def test_to_shop_overrides_only_emits_set_keys():
    sp = ShopProfile(name="Sparse", region="US", labor_rate=50.0)
    ov = sp.to_shop_overrides()
    assert ov == {"labor_rate": 50.0}        # nothing else set => nothing else emitted
