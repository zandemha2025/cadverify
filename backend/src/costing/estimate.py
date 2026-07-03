"""Orchestrator (spec §4, §9) — the single public entry: estimate_decision.

Runs the G1 robustness gate first (refuse broken geometry), then drives:
drivers → routing → cost/leadtime → decision → DecisionReport.

It NEVER mutates `result`, the engine, or the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.analysis.models import Severity
from src.costing.confidence import confidence_interval
from src.costing.decision import Decision, make_vs_buy
from src.costing.drivers import extract_drivers
from src.costing.cost_model import cost_breakdown
from src.costing.leadtime import lead_time
from src.costing.provenance import Driver, Provenance
from src.costing.rates import COSTED_PROCESSES, RateCard, build_rate_card
from src.costing.routing import eligible_processes, recommend_routing
from src.costing.shop_profile import resolve_shop


@dataclass
class EstimateOptions:
    quantities: list = field(default_factory=lambda: [50, 5000])
    material_class: str = "polymer"          # DEFAULT, stated
    region: str = "US"
    rate_overrides: dict = field(default_factory=dict)
    strict_dfm: bool = False                 # True = literal spec §5.3 (drop verdict=='fail')
    material_class_is_user: bool = False     # set True when CLI passes --material-class
    region_is_user: bool = False             # set True when the caller explicitly chose a region
    # Per-shop calibration (bucket #1): a ShopProfile, a stored profile name, a
    # path, a dict, or None. When bound, every default it covers flips to SHOP.
    shop: object = None
    # NEW (weakness #5): formative tooling cavity + complexity
    n_cavities: int = 1                      # DEFAULT 1, single-cavity should-cost
    complexity: str = "moderate"             # simple|moderate|complex|very_complex
    n_cavities_is_user: bool = False
    complexity_is_user: bool = False
    # Per-estimate confidence interval source (bucket #4 measurement). A
    # ground-truth ``ResidualModel`` (or any callable `process -> (residuals,
    # from_real, n)`); when supplied with >= MIN_RESIDUALS for a process the CI
    # is the MEASURED empirical band, else it falls back to the stated
    # assumption band labelled 'assumption-based, not yet validated'. None
    # (default) => assumption-band on every estimate (honest pre-data behaviour).
    residual_model: object = None
    ci_level: float = 0.80
    # Per-process calibration correction (bucket #4). A ground-truth
    # ``Calibration`` (any object with ``factor_for(process) -> float``) that
    # corrects the point estimate to the CORRECTED prediction the residuals were
    # measured on (``corrected = baseline × factor``), so the MEASURED band is
    # centred coherently. Bound ONLY alongside a REAL residual_model; None
    # (default) => point uncorrected => byte-identical pre-data behaviour.
    calibration: object = None
    # W4 governed libraries: a full RATE_CARD_V0-shaped base table resolved from
    # the org's PUBLISHED, effective-dated rate card. When set, it replaces the
    # hardcoded ``RATE_CARD_V0`` as the DEFAULT layer under shop/user overrides.
    # None (default) => the hardcoded default => byte-identical pre-W4 behaviour.
    # A governed card is still a table of DEFAULT assumptions (never validated).
    base_rate_table: dict | None = None


@dataclass
class DecisionReport:
    filename: str
    status: str                              # "OK" | "GEOMETRY_INVALID"
    geometry: dict
    reason: Optional[str] = None
    material_class: Optional[str] = None
    quantities: list = field(default_factory=list)
    estimates: list = field(default_factory=list)   # serialized per (process, qty)
    decision: Optional[Decision] = None
    assumptions: list = field(default_factory=list)  # global DEFAULT/USER rates
    engine_feasibility: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    routing: Optional[dict] = None                   # geometric archetype + reasoning


def _geo_summary(g) -> dict:
    return {
        "volume_cm3": round((g.volume or 0.0) / 1000.0, 2),
        "surface_area_cm2": round((g.surface_area or 0.0) / 100.0, 2),
        "bbox_mm": tuple(round(d, 1) for d in g.bounding_box.dimensions),
        "watertight": bool(g.is_watertight),
        "face_count": int(g.face_count or 0),
    }


def _global_assumptions(rates: RateCard, options: EstimateOptions, region: str) -> list:
    g = rates.data["global"]
    rl, rm, rt = (rates.region_labor(region), rates.region_material(region),
                  rates.region_tooling(region))
    region_prov = rates.region_prov(region)
    shop_note = (f" [shop: {rates.shop_name}]" if rates.shop_name else "")
    out = [
        Driver("labor_rate", g["labor_rate"], "$/hr", rates.prov_tag("labor_rate"),
               "loaded shop-floor labor" + shop_note),
        Driver("region_labor", rl, "×", region_prov,
               f"region {region}: labor/machine/setup ×{rl:g}"),
        Driver("region_material", rm, "×", region_prov,
               f"region {region}: commodity material ×{rm:g} (global feedstock, ~1.0)"),
        Driver("region_tooling", rt, "×", region_prov,
               f"region {region}: tooling ×{rt:g} (offshore toolmaking labor)"),
        Driver("margin", g["margin"], "frac", rates.prov_tag("margin"),
               "target margin (price vs should-cost)" + shop_note),
        Driver("overhead", g["overhead"], "frac", rates.prov_tag("overhead"),
               "indirect burden on conversion cost (machine+labor+setup)" + shop_note),
        Driver("utilization", g["utilization"], "frac", rates.prov_tag("utilization"),
               "machine utilization (idle-recovery on machine cost)" + shop_note),
        Driver("stock_allowance", g["stock_allowance"], "×", rates.prov_tag("stock_allowance"),
               "CNC billet oversize (milling: on bounding box; turning: on hull)"),
        Driver("machine_labor_frac", g["machine_labor_frac"], "frac",
               rates.prov_tag("machine_labor_frac"),
               "operator-labor share of the machine rate that scales with region "
               "(capital/facility stays global) [assumption, not shop-validated]"),
        Driver("perishable_frac", g["perishable_frac"], "frac",
               rates.prov_tag("perishable_frac"),
               "perishable tooling/consumables as a fraction of CNC machine cost "
               "[assumption, not shop-validated]"),
        Driver("daily_machine_hours", g["daily_machine_hours"], "hr/day",
               Provenance.DEFAULT, "for lead-time production days"),
        Driver("n_cavities", float(options.n_cavities), "cav",
               Provenance.USER if options.n_cavities_is_user else Provenance.DEFAULT,
               f"formative tooling cavities = {options.n_cavities} "
               + ("(buyer-supplied)" if options.n_cavities_is_user
                  else "(DEFAULT single-cavity should-cost)")),
        Driver("complexity", 0.0, options.complexity,
               Provenance.USER if options.complexity_is_user else Provenance.DEFAULT,
               f"tooling complexity = {options.complexity} "
               + ("(buyer-supplied)" if options.complexity_is_user
                  else "(DEFAULT moderate; raise for slides/side-actions)")),
        Driver("material_class", 0.0, options.material_class,
               Provenance.USER if options.material_class_is_user else Provenance.DEFAULT,
               f"material class = {options.material_class} "
               + ("(buyer-supplied)" if options.material_class_is_user
                  else "(DEFAULT: these are polymer automotive parts; override for metal)")),
    ]
    return out


def estimate_decision(result, mesh, features, options: EstimateOptions) -> DecisionReport:
    g = result.geometry

    # ── per-shop calibration binding (bucket #1) ────────────────────────
    shop = resolve_shop(options.shop)
    shop_overrides = shop.to_shop_overrides() if shop is not None else None
    shop_region = shop.region if shop is not None else None
    # a bound shop selects its own region unless the caller explicitly chose one
    region = (shop_region if (shop is not None and not options.region_is_user)
              else options.region)
    rates = build_rate_card(options.rate_overrides, shop_overrides=shop_overrides,
                            shop_name=(shop.name if shop is not None else None),
                            shop_region=shop_region,
                            base_rate_table=options.base_rate_table)

    # engine feasibility table (all 21 processes), with costed flag
    feas = []
    for ps in result.process_scores:
        feas.append({
            "process": ps.process.value,
            "verdict": ps.verdict,
            "score": round(float(ps.score), 2),
            "costed": ps.process in COSTED_PROCESSES,
        })

    # ── G1 ROBUSTNESS GATE (must be first) ──────────────────────────────
    has_error = any(i.severity == Severity.ERROR for i in result.universal_issues)
    invalid = (g.volume is None) or (g.volume <= 0.0) or (not g.is_watertight) or has_error
    if invalid:
        return DecisionReport(
            filename=result.filename,
            status="GEOMETRY_INVALID",
            reason=("Geometry is not a measurable solid (volume ≤ 0 or non-watertight). "
                    "Cost requires a watertight, positive-volume mesh. Repair required."),
            geometry=_geo_summary(g),
            material_class=options.material_class,
            quantities=list(options.quantities),
            engine_feasibility=feas,
        )

    # ── drivers → routing → cost/leadtime → decision ───────────────────
    drivers = extract_drivers(g, mesh, features)
    # Processes the engine's own DFM hard-fails (ERROR-level blocker) on THIS
    # part — routing must never headline a process the panel marks FAIL (F2).
    # dfm_clean is the DFM-clean fallback for the headline, ordered costed-first
    # then by score, so a demoted headline still prefers a costable option.
    dfm_failed = {ps.process for ps in result.process_scores if ps.verdict == "fail"}
    dfm_clean = [
        ps.process.value
        for ps in sorted(
            (ps for ps in result.process_scores if ps.verdict != "fail"),
            key=lambda ps: (ps.process not in COSTED_PROCESSES, -float(ps.score)),
        )
    ]
    rec = recommend_routing(drivers, options.material_class,
                            dfm_failed=dfm_failed, dfm_clean=dfm_clean)
    routing_info = {
        "archetype": rec.archetype,
        "recommended_process": rec.process,
        "eval_family": rec.eval_family,
        "material_hint": rec.material_hint,
        "confidence": rec.confidence,
        "reasoning": rec.reasoning,
        "alternatives": rec.alternatives,
        "drivers": {
            "sheet_gauge_mm": drivers.sheet_gauge_mm,
            "planar_aspect": drivers.planar_aspect,
            "bend_count": drivers.bend_count,
            "outline_perimeter_mm": drivers.outline_perimeter_mm,
            "nominal_wall_mm": round(drivers.nominal_wall_mm, 2),
            "rotational": drivers.rotational,
            "sheet_like": drivers.sheet_like,
        },
    }
    elig = eligible_processes(result, drivers, options.material_class, rates,
                              strict_dfm=options.strict_dfm)

    estimates_serialized = []
    estimates_by_pq = {}             # (process_value, qty) -> CostEstimate (real per-qty)
    leadtimes_by_key = {}
    elig_by_pv = {}                  # process_value -> eligible item (for arbitrary-qty costing)

    for item in elig:
        process = item["process"]
        material = item["material"]
        ps = item["score"]
        elig_by_pv[process.value] = item
        for q in options.quantities:
            est = cost_breakdown(process, drivers, material, options.material_class,
                                 q, rates, region,
                                 n_cavities=options.n_cavities,
                                 complexity=options.complexity, process_score=ps)
            # cycle_hr from the estimate keeps lead time consistent with cost
            cycle_hr = next((d.value for d in est.drivers if d.name == "cycle_time"), 0.0)
            lt = lead_time(process, cycle_hr, q, rates)
            leadtimes_by_key[(process.value, q)] = lt
            estimates_by_pq[(process.value, q)] = est
            estimates_serialized.append(
                _serialize(est, lt, drivers, options.residual_model, options.ci_level,
                           options.calibration))

    # Real cost evaluator at ARBITRARY qty — powers the NUMERICAL make-vs-buy
    # crossover (S1: honest crossover once machining variable cost falls with
    # volume, so the single-qty fixed/var closed form is no longer exact).
    def _unit_cost_fn(pv, q):
        item = elig_by_pv.get(pv)
        if item is None:
            return float("inf")
        est = cost_breakdown(item["process"], drivers, item["material"],
                             options.material_class, q, rates, region,
                             n_cavities=options.n_cavities,
                             complexity=options.complexity, process_score=item["score"])
        return est.unit_cost_usd

    decision = make_vs_buy(estimates_by_pq, options.quantities, leadtimes_by_key,
                           unit_cost_fn=_unit_cost_fn)

    notes = []
    if shop is not None:
        bound = sorted({k.split(".", 1)[0] for k in rates.shop_keys})
        notes.append(
            f"Calibrated to shop '{shop.name}' (region {region}): "
            f"{len(rates.shop_keys)} rate(s) bound to this shop's reality and tagged "
            f"SHOP [{', '.join(bound)}]. Every other line stays a generic DEFAULT — "
            "the gaps are visible, not hidden. "
            + (f"Source: {shop.source}. " if shop.source else ""))
    if not options.strict_dfm:
        flagged = sorted({e["process"] for e in estimates_serialized
                          if not e["dfm_ready"]})
        if flagged:
            notes.append(
                "DFM note: processes " + ", ".join(flagged) + " are costed but flagged "
                "NOT DFM-ready as-modeled (the engine reports ERROR-level blockers — "
                "these parts were modeled for 3D printing, so molding/casting lack draft). "
                "Their cost shows the tooling economics *if* the part is redesigned for "
                "that process. Set strict_dfm=True to exclude them entirely.")
    # geometric routing recommendation, and reconciliation with the cost pick
    notes.append(
        f"Geometric routing: this part reads as a '{rec.archetype}' → "
        f"{rec.process}. {rec.reasoning}")
    if decision is not None and decision.make_now_process != rec.process:
        in_shortlist = any(e["process"] == rec.process for e in estimates_serialized)
        if in_shortlist:
            notes.append(
                f"Note: the cost-cheapest make-as-is pick at low qty is "
                f"{decision.make_now_process}, but the geometry-recommended process is "
                f"{rec.process} — both are costed above; pick on intent, "
                f"not just the marginal $.")
        else:
            notes.append(
                f"Note: geometry recommends {rec.process}, which is "
                f"feasibility-only (not in the costed set) — the dollar options above "
                f"are the costable alternatives.")
    notes.append(
        "Absolute cost is ±40–60% (cycle-time/tooling defaults). The crossover "
        "quantity and make-vs-buy direction are robust to it because they depend "
        "on the fixed-vs-variable split, driven by your rates.")

    return DecisionReport(
        filename=result.filename,
        status="OK",
        geometry=_geo_summary(g),
        material_class=options.material_class,
        quantities=list(options.quantities),
        estimates=estimates_serialized,
        decision=decision,
        assumptions=_global_assumptions(rates, options, region),
        engine_feasibility=feas,
        notes=notes,
        routing=routing_info,
    )


def _serialize(est, lt, drivers, residual_model=None, ci_level: float = 0.80,
               calibration=None) -> dict:
    # Every estimate carries a CONFIDENCE INTERVAL (hard global constraint). When
    # a ground-truth residual model is bound it is the MEASURED empirical band;
    # otherwise it falls back to the stated assumption band, clearly labelled.
    #
    # Coherence rail (W5): the measured residuals were fitted on the CORRECTED
    # prediction (corrected = baseline × calibration.factor_for(process); see
    # groundtruth._residuals). So when a REAL calibration is bound we correct the
    # point to that same prediction BEFORE building the band — otherwise the band
    # would be centred on the uncorrected baseline while its residuals assume the
    # correction, and it would systematically EXCLUDE the true cost. With no real
    # calibration (calibration is None) the point is uncorrected and the CI is
    # byte-identical to the pre-W5 assumption band / stand-in spread.
    point_usd = est.unit_cost_usd
    if calibration is not None:
        point_usd = point_usd * calibration.factor_for(est.process)
    ci = confidence_interval(
        point_usd, assumption_band_pct=est.est_error_band_pct,
        residual_provider=residual_model, process=est.process, level=ci_level)
    return {
        "process": est.process,
        "material": est.material,
        "quantity": est.quantity,
        "unit_cost_usd": round(est.unit_cost_usd, 2),
        "fixed_cost_usd": round(est.fixed_cost_usd, 2),
        "variable_cost_usd": round(est.variable_cost_usd, 2),
        "est_error_band_pct": est.est_error_band_pct,
        "confidence": ci.to_dict(),
        "dfm_ready": est.dfm_ready,
        "dfm_verdict": est.dfm_verdict,
        "dfm_score": est.dfm_score,
        "dfm_blockers": est.dfm_blockers,
        # Structured blockers — each a full serialized Issue so the cost view can
        # locate the blocker on the part (faces/region/citation), not just its
        # message. Parallel to dfm_blockers (same order).
        "dfm_blocker_details": getattr(est, "dfm_blocker_details", []),
        "line_items": est.line_items,
        "drivers": [
            {"name": d.name, "value": d.value, "unit": d.unit,
             "provenance": d.provenance.value, "source": d.source,
             "error_band_pct": d.error_band_pct}
            for d in est.drivers
        ],
        "lead_time": {
            "low_days": lt.low_days, "high_days": lt.high_days, "mid_days": lt.mid_days,
            "components": lt.components,
            "capacity": lt.capacity,        # R1: stated, inspectable, overridable
        },
    }
