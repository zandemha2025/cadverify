"""E-now Wave 1 — cost-model credibility structure (coefficients Zoox-gated).

Each of the four changes is proved two ways, per the build contract:
  (a) DIRECTION is correct (the fix moves cost the physically-right way), and
  (b) the OFF-SWITCH recovers the old number byte-identically.

Every new coefficient is DEFAULT-provenance, carries an "[assumption, not
shop-validated]" note, and `validated` stays False (nothing here asserts a
measured magnitude — only structure + direction). These tests use procedural
meshes so they always run in CI (no real-parts corpus dependency).

  #1  Hull→bbox billet stock for CNC milling (material + roughing).
  #2  Region model: scale ONLY the labor share of the machine rate, not capital.
  #3  CAM-programming NRE + FAI/inspection lines (qty-1 was just the min floor).
  #4  Perishable consumables (% of machine) + outsourced secondary finishing.
"""

from __future__ import annotations

import os

import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType as PT
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401  populate registry

from src.costing import estimate_decision, EstimateOptions
from src.costing.cost_model import cost_breakdown
from src.costing.drivers import extract_drivers, bbox_billet_enabled
from src.costing.rates import build_rate_card
from src.costing.routing import select_material


# ── fixtures / helpers ──────────────────────────────────────────────────────
def _analyze(mesh) -> AnalysisResult:
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="enow.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _nonconvex():
    """A thin 80×12×12 bar rotated 45° about Z: its axis-aligned bounding box is
    ~4× the convex hull, so a bbox billet is dramatically larger than a hull one —
    exactly the non-convex understatement E-now #1 targets."""
    m = trimesh.creation.box(extents=[80.0, 12.0, 12.0])
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 4.0, [0, 0, 1]))
    return m


def _bulky_block():
    return trimesh.creation.box(extents=[40.0, 30.0, 25.0])


def _cnc_setup(mesh):
    result, mesh, feats = _analyze(mesh)
    drivers = extract_drivers(result.geometry, mesh, feats)
    rates = build_rate_card()
    mat = select_material(PT.CNC_3AXIS, "aluminum", rates)
    ps = next(p for p in result.process_scores if p.process == PT.CNC_3AXIS)
    return drivers, rates, mat, ps


def _cb(drivers, mat, ps, qty, *, rates, region="US", proc=PT.CNC_3AXIS):
    return cost_breakdown(proc, drivers, mat, "aluminum", qty, rates, region,
                          process_score=ps)


def _li(est, key):
    return est.line_items.get(key, 0.0)


def _driver(est, name):
    return next((d for d in est.drivers if d.name == name), None)


def _clear(*names):
    for n in names:
        os.environ.pop(n, None)


# ── #1  Hull → bbox billet stock (CNC milling) ──────────────────────────────
def test_bbox_billet_direction_and_offswitch():
    drivers, rates, mat, ps = _cnc_setup(_nonconvex())
    # sanity: the part genuinely does not fill its bbox (non-convex/rotated)
    assert drivers.bbox_volume_cm3 > 2.0 * drivers.hull_volume_cm3

    _clear("CADVERIFY_BBOX_BILLET")
    on = _cb(drivers, mat, ps, 100, rates=rates)                 # default ON (bbox)
    os.environ["CADVERIFY_BBOX_BILLET"] = "0"
    off = _cb(drivers, mat, ps, 100, rates=rates)                # legacy hull
    _clear("CADVERIFY_BBOX_BILLET")

    # (a) direction: a bbox billet buys (and mills away) more than a hull billet
    assert _li(on, "material") > _li(off, "material")
    assert _li(on, "machine") > _li(off, "machine")             # more stock roughed away

    # (b) byte-identical off-switch at the exact quantity that changed
    allow = rates.g("stock_allowance")
    assert bbox_billet_enabled() is True                        # default is the fix
    os.environ["CADVERIFY_BBOX_BILLET"] = "0"
    assert bbox_billet_enabled() is False
    assert drivers.billet_volume_cm3(allow) == drivers.hull_volume_cm3 * allow
    assert drivers.billet_mass_kg(mat.density, allow) == drivers.stock_mass_kg(mat.density, allow)
    _clear("CADVERIFY_BBOX_BILLET")

    # provenance + honest caveat on the material driver source (DEFAULT-tagged billet)
    md = _driver(on, "material_cost")
    assert "bounding-box billet" in md.source and "not shop-validated" in md.source


def test_bbox_billet_untouched_for_turning():
    """Turning starts from round bar — E-now #1 must NOT touch it (still hull)."""
    drivers, rates, mat, ps = _cnc_setup(_nonconvex())
    turn_mat = select_material(PT.CNC_TURNING, "aluminum", rates)
    ps_turn = ps  # process_score is only used for DFM pass-through here
    _clear("CADVERIFY_BBOX_BILLET")
    on = cost_breakdown(PT.CNC_TURNING, drivers, turn_mat, "aluminum", 100, rates, "US",
                        process_score=ps_turn)
    os.environ["CADVERIFY_BBOX_BILLET"] = "0"
    off = cost_breakdown(PT.CNC_TURNING, drivers, turn_mat, "aluminum", 100, rates, "US",
                         process_score=ps_turn)
    _clear("CADVERIFY_BBOX_BILLET")
    assert _li(on, "material") == _li(off, "material")          # turning unaffected by the flag


# ── #2  Region model: labor-only scaling of the machine rate ────────────────
def test_machine_region_split_direction_and_offswitch():
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    _clear("CADVERIFY_MACHINE_CAPITAL_SPLIT")
    us = _cb(drivers, mat, ps, 100, rates=rates, region="US")
    cn_split = _cb(drivers, mat, ps, 100, rates=rates, region="CN")   # default ON
    os.environ["CADVERIFY_MACHINE_CAPITAL_SPLIT"] = "0"
    cn_old = _cb(drivers, mat, ps, 100, rates=rates, region="CN")     # legacy whole-rate
    _clear("CADVERIFY_MACHINE_CAPITAL_SPLIT")

    frac = rates.g("machine_labor_frac")
    rl = rates.region_labor("CN")
    expected = (1.0 - frac) + frac * rl

    # (a) direction: capital is NOT offshored, so the split machine cost is HIGHER
    # than the buggy whole-rate discount, and the multiplier equals the split
    assert _li(cn_split, "machine") > _li(cn_old, "machine")
    # ratios are of 4-decimal-rounded line items, so compare within rounding noise
    assert abs(_li(cn_split, "machine") / _li(us, "machine") - expected) < 2e-3
    # glass-box driver present + DEFAULT + caveat
    d = _driver(cn_split, "machine_region_split")
    assert d is not None and d.provenance.value == "DEFAULT"
    assert "not shop-validated" in d.source

    # (b) byte-identical off-switch: the machine multiplier collapses to raw rl
    os.environ["CADVERIFY_MACHINE_CAPITAL_SPLIT"] = "0"
    assert rates.machine_region_mult("CN") == rates.region_labor("CN")   # exact at the multiplier
    assert abs(_li(cn_old, "machine") / _li(us, "machine") - rl) < 2e-3
    _clear("CADVERIFY_MACHINE_CAPITAL_SPLIT")
    # US is a no-op under the split (capital+labor both ×1) — unchanged
    assert rates.machine_region_mult("US") == 1.0


def test_machine_labor_frac_override_recovers_old_behavior():
    """machine_labor_frac=1.0 is the per-quote off-switch: the whole rate scales
    with region again, byte-identical to the legacy model."""
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    rc1 = build_rate_card({"machine_labor_frac": 1.0})
    us = _cb(drivers, mat, ps, 100, rates=rc1, region="US")
    cn = _cb(drivers, mat, ps, 100, rates=rc1, region="CN")
    assert rc1.machine_region_mult("CN") == rc1.region_labor("CN")       # exact at the multiplier
    assert abs(_li(cn, "machine") / _li(us, "machine") - rc1.region_labor("CN")) < 2e-3


# ── #3  CAM programming / NRE + FAI / inspection (qty-1 honesty) ────────────
def test_nre_inspection_direction_qty1_beats_floor():
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    _clear("CADVERIFY_CNC_NRE")
    on = _cb(drivers, mat, ps, 1, rates=rates)                 # default ON
    os.environ["CADVERIFY_CNC_NRE"] = "0"
    off = _cb(drivers, mat, ps, 1, rates=rates)                # legacy: only the min floor
    _clear("CADVERIFY_CNC_NRE")

    # (a) direction: qty-1 machining is materially higher once NRE + FAI are real
    assert on.unit_cost_usd > off.unit_cost_usd
    assert "nre" in on.line_items and "inspection" in on.line_items
    # the plan's exact framing: the OLD qty-1 number was just the min-charge floor
    assert "min_charge_floor" in off.line_items
    assert "nre" not in off.line_items and "inspection" not in off.line_items
    # DEFAULT + caveats on the new drivers
    for name in ("nre_cost", "inspection_cost"):
        d = _driver(on, name)
        assert d is not None and "not shop-validated" in d.source
        assert d.provenance.value in ("DEFAULT", "USER")


def test_nre_inspection_offswitch_byte_identical():
    """At a qty where the min-charge floor does NOT bite, flipping CNC_NRE off
    removes exactly the nre+inspection lines and leaves every base line byte-
    identical — the old number recovered exactly."""
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    _clear("CADVERIFY_CNC_NRE")
    on = _cb(drivers, mat, ps, 200, rates=rates)
    os.environ["CADVERIFY_CNC_NRE"] = "0"
    off = _cb(drivers, mat, ps, 200, rates=rates)
    _clear("CADVERIFY_CNC_NRE")
    assert "min_charge_floor" not in on.line_items             # floor not biting at qty 200
    for base in ("amortized_fixed", "material", "machine", "labor"):
        assert on.line_items[base] == off.line_items[base]     # base cost untouched
    # off == on minus exactly the two new lines
    removed = _li(on, "nre") + _li(on, "inspection")
    assert abs(off.unit_cost_usd - (on.unit_cost_usd - removed)) < 1e-9


def test_nre_amortizes_over_order():
    """NRE is a one-time cost: its per-unit share falls ~1/qty across the order."""
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    _clear("CADVERIFY_CNC_NRE")
    e10 = _cb(drivers, mat, ps, 10, rates=rates)
    e1000 = _cb(drivers, mat, ps, 1000, rates=rates)
    _clear("CADVERIFY_CNC_NRE")
    # total NRE is (approximately) constant → per-unit scales ~100× down for 100× qty
    assert _li(e10, "nre") > 50 * _li(e1000, "nre")


# ── #4  Perishable consumables (% machine) + outsourced finishing ───────────
def test_perishable_consumables_direction_and_offswitch():
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    _clear("CADVERIFY_PERISHABLE_TOOLING")
    on = _cb(drivers, mat, ps, 100, rates=rates)
    os.environ["CADVERIFY_PERISHABLE_TOOLING"] = "0"
    off = _cb(drivers, mat, ps, 100, rates=rates)
    _clear("CADVERIFY_PERISHABLE_TOOLING")

    # (a) direction: consumables add a positive cost tied to machine time
    assert _li(on, "consumables") > 0.0
    frac = rates.g("perishable_frac")
    assert abs(_li(on, "consumables") - frac * _li(on, "machine")) < 1e-6   # exactly % of machine
    d = _driver(on, "consumables_cost")
    assert d is not None and d.provenance.value == "DEFAULT" and "not shop-validated" in d.source

    # (b) byte-identical off-switch: consumables gone, base lines untouched
    assert "consumables" not in off.line_items
    for base in ("amortized_fixed", "material", "machine", "labor"):
        assert on.line_items[base] == off.line_items[base]
    assert abs(off.unit_cost_usd - (on.unit_cost_usd - _li(on, "consumables"))) < 1e-9

    # perishable_frac=0 is the per-quote off-switch
    rc0 = build_rate_card({"perishable_frac": 0.0})
    z = _cb(drivers, mat, ps, 100, rates=rc0)
    assert "consumables" not in z.line_items


def test_outsourced_finishing_direction_and_offswitch():
    drivers, rates, mat, ps = _cnc_setup(_bulky_block())
    # default: no finish spec → no finishing line (honest as-machined default)
    base = _cb(drivers, mat, ps, 100, rates=rates)
    assert "finishing" not in base.line_items

    # configure an outsourced anodize: lot setup + per-part rate
    rc = build_rate_card({"finish_lot_charge.CNC_3AXIS": 150.0,
                          "finish_per_part.CNC_3AXIS": 4.0})
    _clear("CADVERIFY_OUTSOURCED_FINISHING")
    on = _cb(drivers, mat, ps, 100, rates=rc)
    os.environ["CADVERIFY_OUTSOURCED_FINISHING"] = "0"
    off = _cb(drivers, mat, ps, 100, rates=rc)
    _clear("CADVERIFY_OUTSOURCED_FINISHING")

    # (a) direction: a lot charge + per-part charge shows up as its own line
    assert _li(on, "finishing") > 0.0
    # lot 150/100 + 4/part = 1.5 + 4 = 5.5 (US, margin 0) → structure is a lot + per-part
    assert abs(_li(on, "finishing") - (150.0 / 100 + 4.0)) < 1e-6
    d = _driver(on, "finishing_cost")
    assert d is not None and "not shop-validated" in d.source
    assert d.provenance.value in ("DEFAULT", "USER")

    # (b) byte-identical off-switch: finishing gone, base lines untouched, == default
    assert "finishing" not in off.line_items
    assert abs(off.unit_cost_usd - base.unit_cost_usd) < 1e-9


# ── integration: honesty + Σ invariant across the whole report ──────────────
def test_enow_wave1_sigma_invariant_and_provenance_end_to_end():
    """Through the real estimate_decision path: every estimate still satisfies
    Σ(line_items)==unit_cost, every driver has a DEFAULT/USER/MEASURED tag + a
    non-empty source, and the two new global assumptions surface as DEFAULT with
    the Zoox caveat. Nothing is marked validated."""
    result, mesh, feats = _analyze(_bulky_block())
    report = estimate_decision(result, mesh, feats,
                               EstimateOptions(quantities=[1, 100, 10000],
                                               material_class="aluminum"))
    assert report.status == "OK" and report.estimates
    for e in report.estimates:
        s = sum(e["line_items"].values())
        assert abs(e["unit_cost_usd"] - round(s, 2)) < 0.02
        for d in e["drivers"]:
            assert d["source"].strip()
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")
        # no estimate claims a measured/validated confidence band pre-Zoox
        assert e["confidence"]["validated"] is False
    names = {a.name: a for a in report.assumptions}
    for key in ("machine_labor_frac", "perishable_frac"):
        assert key in names
        assert names[key].provenance.value == "DEFAULT"
        assert "not shop-validated" in names[key].source
