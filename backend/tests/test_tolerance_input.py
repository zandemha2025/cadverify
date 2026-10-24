"""Declared tolerance-class input surface (Aramco readiness gap #4, cost side).

The caller STATES how tight the part is; the cost model applies an honest
machining multiplier to the tolerance-sensitive conversion terms (CNC finish
pass + inspection) and WIDENS the confidence band. There is NO real GD&T/PMI
extraction here (that needs OCP) — this is a STATED input, never a measurement.

Honesty invariants proved below:
  * "standard" (or omitted / unknown → normalized) is BYTE-IDENTICAL to the
    pre-change output (point + band + line_items).
  * Monotonic: standard < precision < tight in BOTH per-unit cost and absolute
    band width for a CNC part.
  * The factor is a DEFAULT assumption (source string says so); the DECLARATION
    is USER. `validated` is NEVER flipped True by a tolerance declaration.
  * The band only ever WIDENS with tighter tolerance (never narrows).

Pure/procedural mesh — no DB, no real-parts corpus, always runs in CI.
"""

from __future__ import annotations

import numpy as np
import trimesh

from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType as PT
from src.analysis.processes.base import get_analyzer
from src.analysis.processes import base as pbase
from src.matcher.profile_matcher import rank_processes, score_process
import src.analysis.processes  # noqa: F401  populate registry

from src.costing.cost_model import cost_breakdown
from src.costing.confidence import confidence_interval
from src.costing.drivers import extract_drivers
from src.costing.estimate import EstimateOptions
from src.costing.rates import (
    build_rate_card, normalize_tolerance_class, TOLERANCE_CLASSES,
)
from src.costing.routing import select_material


# ── fixtures ────────────────────────────────────────────────────────────────
def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    universal = run_universal_checks(mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="tol.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=universal,
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _cnc_setup(proc=PT.CNC_3AXIS):
    m = trimesh.creation.box(extents=[40.0, 30.0, 25.0])
    result, mesh, feats = _analyze(m)
    drivers = extract_drivers(result.geometry, mesh, feats)
    rates = build_rate_card()
    mat = select_material(proc, "aluminum", rates)
    ps = next(p for p in result.process_scores if p.process == proc)
    return drivers, rates, mat, ps


def _cb(drivers, mat, ps, rates, tolerance_class, qty=100, proc=PT.CNC_3AXIS):
    return cost_breakdown(proc, drivers, mat, "aluminum", qty, rates, "US",
                          process_score=ps, tolerance_class=tolerance_class)


def _driver(est, name):
    return next((d for d in est.drivers if d.name == name), None)


# ── 1) standard / omitted ⇒ BYTE-IDENTICAL ──────────────────────────────────
def test_standard_and_omitted_byte_identical():
    drivers, rates, mat, ps = _cnc_setup()
    # explicit standard
    std = _cb(drivers, mat, ps, rates, "standard")
    # omitted (the cost_breakdown default) — same object shape
    omitted = cost_breakdown(PT.CNC_3AXIS, drivers, mat, "aluminum", 100, rates, "US",
                             process_score=ps)

    assert std.unit_cost_usd == omitted.unit_cost_usd
    assert std.est_error_band_pct == omitted.est_error_band_pct
    assert std.line_items == omitted.line_items
    assert std.fixed_cost_usd == omitted.fixed_cost_usd
    assert std.variable_cost_usd == omitted.variable_cost_usd
    # standard adds NO tolerance line item and NO tolerance driver
    assert "tolerance" not in std.line_items
    assert _driver(std, "tolerance_class") is None
    # the reported band equals the untouched family band (no widening)
    assert std.est_error_band_pct == rates.band_pct(PT.CNC_3AXIS)


# ── 2) monotonic in BOTH cost and band width (CNC) ──────────────────────────
def test_monotonic_cost_and_band_cnc():
    drivers, rates, mat, ps = _cnc_setup()
    std = _cb(drivers, mat, ps, rates, "standard")
    prec = _cb(drivers, mat, ps, rates, "precision")
    tight = _cb(drivers, mat, ps, rates, "tight")

    # per-unit cost strictly increases as tolerance tightens
    assert std.unit_cost_usd < prec.unit_cost_usd < tight.unit_cost_usd

    # absolute band width (± point × band%) strictly widens too
    def _band_abs(e):
        return e.unit_cost_usd * e.est_error_band_pct / 100.0
    assert std.est_error_band_pct < prec.est_error_band_pct < tight.est_error_band_pct
    assert _band_abs(std) < _band_abs(prec) < _band_abs(tight)

    # the surcharge shows up as its own line item once non-standard
    assert "tolerance" not in std.line_items
    assert prec.line_items["tolerance"] > 0.0
    assert tight.line_items["tolerance"] > prec.line_items["tolerance"]

    # Σ line_items still == unit_cost (assert_sums already ran inside cost_breakdown)
    assert round(sum(tight.line_items.values()), 4) == tight.unit_cost_usd


# ── 3) provenance + validated-never-fabricated ──────────────────────────────
def test_provenance_and_validated_never_flipped():
    drivers, rates, mat, ps = _cnc_setup()
    tight = _cb(drivers, mat, ps, rates, "tight")

    d = _driver(tight, "tolerance_class")
    assert d is not None
    # the DECLARATION is USER; the factor is a DEFAULT assumption (said so)
    assert d.provenance.value == "USER"
    assert "DEFAULT assumption" in d.source
    assert "not shop-validated" in d.source

    # a tolerance declaration can NEVER flip a confidence interval to validated:
    # with no real residual model the band stays an assumption band.
    ci = confidence_interval(
        tight.unit_cost_usd, assumption_band_pct=tight.est_error_band_pct,
        residual_provider=None, process=tight.process, level=0.80)
    assert ci.validated is False


# ── 4) unknown class → normalized to standard → byte-identical ──────────────
def test_unknown_class_normalized_to_standard():
    assert normalize_tolerance_class("garbage") == "standard"
    assert normalize_tolerance_class(None) == "standard"
    assert normalize_tolerance_class("TIGHT") == "tight"     # case-insensitive
    assert normalize_tolerance_class("  precision ") == "precision"

    drivers, rates, mat, ps = _cnc_setup()
    std = _cb(drivers, mat, ps, rates, "standard")
    junk = _cb(drivers, mat, ps, rates, "not-a-real-class")
    assert junk.unit_cost_usd == std.unit_cost_usd
    assert junk.est_error_band_pct == std.est_error_band_pct
    assert junk.line_items == std.line_items

    # EstimateOptions normalizes on construction (honest fallback, never crash)
    assert EstimateOptions(tolerance_class="bogus").tolerance_class == "standard"
    assert EstimateOptions(tolerance_class="tight").tolerance_class == "tight"


# ── 5) non-machining families: band widens, cost unchanged ──────────────────
def test_non_machining_family_cost_unchanged_band_widens():
    # SLS (additive): tolerance is set by the process, so V0 applies NO honest
    # per-part cost surcharge — but the band still widens (uncertainty grows).
    m = trimesh.creation.box(extents=[40.0, 30.0, 25.0])
    result, mesh, feats = _analyze(m)
    drivers = extract_drivers(result.geometry, mesh, feats)
    rates = build_rate_card()
    mat = select_material(PT.SLS, "polymer", rates)
    ps = next(p for p in result.process_scores if p.process == PT.SLS)

    std = cost_breakdown(PT.SLS, drivers, mat, "polymer", 100, rates, "US",
                         process_score=ps, tolerance_class="standard")
    tight = cost_breakdown(PT.SLS, drivers, mat, "polymer", 100, rates, "US",
                           process_score=ps, tolerance_class="tight")

    # cost is UNCHANGED for a non-machining family
    assert tight.unit_cost_usd == std.unit_cost_usd
    assert "tolerance" not in tight.line_items
    # but the band widened, and a driver documents the (no-cost) declaration
    assert tight.est_error_band_pct > std.est_error_band_pct
    d = _driver(tight, "tolerance_class")
    assert d is not None and d.provenance.value == "USER"
    assert "cost UNCHANGED" in d.source


def test_tolerance_classes_ordered_and_standard_is_noop():
    rates = build_rate_card()
    assert TOLERANCE_CLASSES[0] == "standard"
    # standard is the strict no-op; every other class is a real surcharge + widen
    assert rates.tolerance_factors("standard") == (1.0, 0.0)
    for tc in TOLERANCE_CLASSES[1:]:
        mult, band_add = rates.tolerance_factors(tc)
        assert mult >= 1.0 and band_add >= 0.0
