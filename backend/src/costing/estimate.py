"""Orchestrator (spec §4, §9) — the single public entry: estimate_decision.

Runs the G1 robustness gate first (refuse broken geometry), then drives:
drivers → routing → cost/leadtime → decision → DecisionReport.

It NEVER mutates `result`, the engine, or the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from src.analysis.models import Severity
from src.costing.confidence import confidence_interval
from src.costing.decision import Decision, make_vs_buy
from src.costing.drivers import extract_drivers
from src.costing.cost_model import BuildEnvelopeError, cost_breakdown
from src.costing.leadtime import lead_time
from src.costing.provenance import Driver, Provenance
from src.costing.rates import COSTED_PROCESSES, RateCard, build_rate_card
from src.analysis.process_names import join_labels, process_phrase
from src.costing.routing import eligible_processes, recommend_routing, sheet_stock_gap
from src.costing.shop_profile import resolve_shop


@dataclass
class EstimateOptions:
    quantities: list = field(default_factory=lambda: [50, 5000])
    material_class: str = "polymer"          # DEFAULT, stated
    region: str = "US"
    rate_overrides: dict = field(default_factory=dict)
    strict_dfm: bool = False                 # True = literal spec §5.3 (drop verdict=='fail')
    material_class_is_user: bool = False     # set True when CLI passes --material-class
    # ── material read from the CAD file (no-kernel text scan, spec honesty slice) ──
    # True when the caller left material_class at its DEFAULT and a declared
    # material annotation was found in the uploaded CAD file (src.parsers.
    # step_material) and mapped to a material_class — the CAD's own stated claim,
    # not measured from geometry and not a buyer confirmation for this quote.
    # Mutually exclusive with material_class_is_user by construction: a real user
    # declaration always wins upstream and this stays False in that case.
    # Default False => byte-identical to pre-CAD-material behaviour.
    material_class_from_cad: bool = False
    # The material a parts list names, as written ("4140 steel", "Delrin"). Each
    # route is priced in that grade where the engine has it for the route; a
    # metal route without it is priced in the cheapest grade of the same metal
    # (the estimate names the grade used), a plastic route without it isn't
    # priced (routing.select_material). None (default) => the class rule,
    # byte-identical. Implies material_class_is_user.
    material_name: Optional[str] = None
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
    # ── owned-equipment / in-house marginal costing (make-it-ourselves) ──────
    # The ProcessTypes the org ALREADY OWNS in its own facility (USER-declared).
    # For an owned process the machine is costed at the MARGINAL rate (capital
    # amortization removed — the asset is sunk; see rates.machine_capital_frac),
    # so make-it-ourselves on gear we already have is a first-class, correctly
    # cheaper option than renting an outside shop's fully-loaded time. Empty
    # (default) => nothing owned => byte-identical. The DECLARATION is USER; the
    # capital fraction it removes is a DEFAULT assumption (not shop-validated),
    # and machine_capital_frac=0.0 recovers fully-loaded even when this is set.
    owned_processes: frozenset = frozenset()
    # ── declared tolerance class (Aramco cost gap #4) ────────────────────────
    # The caller STATES how tight the part is; the cost model applies an honest
    # machining multiplier to the tolerance-sensitive conversion terms (CNC
    # finish pass + inspection) and WIDENS the confidence band. There is NO real
    # GD&T/PMI extraction (that needs OCP) — this is a STATED input, never a
    # measurement. "standard" (default/omitted) ⇒ (1.0, +0 band) ⇒ byte-identical.
    # Unknown strings normalize to "standard" (honest fallback, never crash). The
    # DECLARATION is USER; the factor magnitudes are DEFAULT assumptions.
    tolerance_class: str = "standard"
    tolerance_class_is_user: bool = False
    # ── machine-inventory verification (Phase C, spec §7) ────────────────────
    # The org's DECLARED owned machines, hydrated to the pure-matcher capability
    # dataclasses (``makeability.MachineCap``). When non-empty, the decision
    # pipeline computes per-process machine fit (verify_part/fit_machine) and the
    # report carries a machine-grounded §0 verdict; a PASSING owned machine that
    # declares a rate re-costs THAT process at its own MARGINAL rate. Empty
    # (default) => no machine lens => byte-identical to pre-Phase-C. USER-declared.
    inventory: tuple = ()
    # The org's DECLARED shop-level secondary ops (``makeability.ShopCaps``) — the
    # matcher's available-secondary-op set (grinding/HIP/sinter/…). None => none.
    shop_caps: object = None
    # The part's DECLARED service environment (part_context.service_environment):
    # {max_temp_c,min_temp_c,pressure_bar,corrosive,sour_service,medium,standard}.
    # Feeds the environment gate (drops env-invalid materials/routes with a cited
    # exclusion). None (default) => the gate is a no-op => byte-identical.
    service_environment: "dict | None" = None
    # The part's DECLARED specs (part_context.part_specs; costing.part_specs):
    # finishes + Ra, heat treatments, inspection, certifications. Each op adds a
    # cost line and lead time; a route that can't deliver them is flagged
    # spec_excluded. None (default) => no-op => byte-identical.
    part_specs: "dict | None" = None
    # ── declared CAD source units (B5 units landmine) ────────────────────────
    # STL carries NO units; the engine interprets vertex coordinates as MILLIMETRES.
    # An inch-authored STL therefore silently mis-costs by 25.4**3 (~16,387x). The
    # caller may DECLARE the source units (mm|inch); the ACTUAL geometric scaling
    # into mm happens at the parse seam (routes.scale_mesh_to_mm) BEFORE geometry
    # and DFM are extracted, so DFM + machine-fit + cost all read the SAME real
    # part. This field is DECLARATIVE — it records what was declared for the
    # provenance line + the plausibility net; it does NOT itself rescale geometry.
    # "mm" (default/unset) => byte-identical. units_is_user=True when the caller
    # explicitly supplied it => the source_units assumption line is USER-tagged.
    units: str = "mm"
    units_is_user: bool = False

    def __post_init__(self):
        from src.costing.rates import normalize_tolerance_class
        self.tolerance_class = normalize_tolerance_class(self.tolerance_class)


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
    # Machine-inventory verification block (Phase C): the §0 makeability verdict
    # (per-process machine fit + top-level verdict + gap + env exclusions). None
    # (default) => no inventory AND no declared environment => report_to_dict adds
    # NO key => byte-identical to pre-Phase-C output.
    verification: Optional[dict] = None
    # Units safety net (B5): structured out-of-range-volume warnings — the honest
    # flag that the mm-interpreted geometry is implausible for a single part
    # (confirm mm vs inch). EMPTY (default, plausible part) => report_to_dict adds
    # NO key => byte-identical. Populated only when the plausibility net fires;
    # each entry is provenance-honest (MEASURED geometry vs ASSUMED units).
    unit_warnings: list = field(default_factory=list)
    # Declared part specs block (costing.part_specs.SpecSession.block). None =>
    # no specs declared => report_to_dict adds NO key => byte-identical.
    specs: Optional[dict] = None


def _geo_summary(g) -> dict:
    return {
        "volume_cm3": round((g.volume or 0.0) / 1000.0, 2),
        "surface_area_cm2": round((g.surface_area or 0.0) / 100.0, 2),
        "bbox_mm": tuple(round(d, 1) for d in g.bounding_box.dimensions),
        "watertight": bool(g.is_watertight),
        "face_count": int(g.face_count or 0),
    }


def _unit_plausibility_warnings(g, options: "EstimateOptions") -> list:
    """B5 honest safety net: flag when the mm-interpreted geometry is implausible
    for a single manufacturable part under the DECLARED/assumed source units.

    Read on the RAW (unrounded) final costed geometry — the mesh has already been
    scaled into mm at the parse seam — so it fires when an undeclared inch part
    reads as a grain, or a metre-authored part reads as a building. We deliberately
    use the unrounded volume/bbox here (not the 2-decimal _geo_summary) so a
    sub-mm³ part's volume signal is not rounded away before the check. Returns []
    on any plausible part => report_to_dict adds NO key => the default/mm path stays
    byte-identical. This is a WARNING, never a corrected number: the volume/bbox
    are MEASURED, the units are ASSUMED (honesty rules)."""
    from src.costing.units import implausible_volume_warning
    vol_cm3 = (g.volume or 0.0) / 1000.0
    dims = tuple(g.bounding_box.dimensions)
    max_bbox = max(dims) if dims else 0.0
    w = implausible_volume_warning(vol_cm3, max_bbox, assumed_units=options.units)
    return [w] if w is not None else []


_CLASS_WORDS = {"polymer": "plastic", "aluminum": "aluminum", "steel": "steel",
                "stainless": "stainless steel", "titanium": "titanium", "nickel": "nickel alloy",
                "copper": "copper", "cobalt": "cobalt-chrome"}


def _material_class_source(options: "EstimateOptions") -> str:
    """What material the prices assume, and why, in plain words (M19)."""
    cls = options.material_class
    words = _CLASS_WORDS.get(cls, cls)
    if options.material_name:
        return (f"priced in {options.material_name} where a process runs it, as the parts list "
                f"names it; a metal process that doesn't is priced in the nearest {words} grade "
                f"it runs, and says which")
    if options.material_class_is_user:
        return f"priced in {words}, as you set it"
    if options.material_class_from_cad:
        return f"priced in {words}, read from the material named in the CAD file"
    return (f"No material was given, so prices assume {words}. Set the material to "
            f"price it in metal or another plastic.")


def _global_assumptions(rates: RateCard, options: EstimateOptions, region: str) -> list:
    g = rates.data["global"]
    rl, rm, rt = (rates.region_labor(region), rates.region_material(region),
                  rates.region_tooling(region))
    region_prov = rates.region_prov(region)
    shop_note = (f" [shop: {rates.shop_name}]" if rates.shop_name else "")  # outbound cuts this clause
    typical = " (typical value, not confirmed by a shop)"
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
               "markup on cost: price = cost × (1 + margin); 0.25 adds 25%, not a 25% gross margin" + shop_note),
        Driver("overhead", g["overhead"], "frac", rates.prov_tag("overhead"),
               "indirect burden on conversion cost (machine+labor+setup)" + shop_note),
        Driver("utilization", g["utilization"], "frac", rates.prov_tag("utilization"),
               "machine utilization (idle-recovery on machine cost)" + shop_note),
        Driver("stock_allowance", g["stock_allowance"], "×", rates.prov_tag("stock_allowance"),
               "CNC stock volume allowance (milling: on bounding box; turning: on enclosing cylinder)"),
        Driver("machine_labor_frac", g["machine_labor_frac"], "frac",
               rates.prov_tag("machine_labor_frac"),
               "operator-labor share of the machine rate, the part that changes with region "
               "(the machine and building cost the same everywhere)" + typical),
        Driver("perishable_frac", g["perishable_frac"], "frac",
               rates.prov_tag("perishable_frac"),
               "cutting tools and consumables as a share of CNC machine cost" + typical),
        Driver("daily_machine_hours", g["daily_machine_hours"], "hr/day",
               rates.prov_tag("daily_machine_hours"),
               "fallback daily capacity; process-specific machine hours take precedence" + shop_note),
        Driver("n_cavities", float(options.n_cavities), "cav",
               Provenance.USER if options.n_cavities_is_user else Provenance.DEFAULT,
               (f"{options.n_cavities} cavities per mold or die, as you set it"
                if options.n_cavities_is_user
                else "1 cavity per mold or die, the usual starting point for a should-cost; "
                     "set more for high volume")),
        Driver("complexity", 0.0, options.complexity,
               Provenance.USER if options.complexity_is_user else Provenance.DEFAULT,
               (f"tool complexity {options.complexity.replace('_', ' ')}, as you set it"
                if options.complexity_is_user
                else "moderate tool complexity, the usual starting point; raise it for "
                     "slides or side actions")),
        Driver("material_class", 0.0, options.material_class,
               Provenance.USER if options.material_class_is_user
               else (Provenance.CAD if options.material_class_from_cad
                     else Provenance.DEFAULT),
               _material_class_source(options)),
    ]
    # ── owned-equipment assumption (only when a process is declared OWNED and
    # the capital fraction is live) — the DECLARATION is USER (shown per-estimate
    # as the owned_in_house driver); the FRACTION magnitude removed is a DEFAULT
    # assumption. Gated so the default (nothing owned) and the off-switch
    # (machine_capital_frac=0) both stay byte-identical.
    if options.owned_processes and rates.g("machine_capital_frac") > 0:
        owned_names = join_labels(sorted(options.owned_processes, key=lambda p: p.value))
        out.append(Driver(
            "machine_capital_frac", g["machine_capital_frac"], "frac",
            rates.prov_tag("machine_capital_frac"),
            f"share of the machine rate that pays for the machine itself, left out "
            f"for machines the shop has ({owned_names}): that cost is already paid"
            + typical))
    # ── declared CAD source units (B5) — only when the caller EXPLICITLY declared
    # them (units_is_user). STL carries no units; a declaration is USER-tagged and
    # the geometry was scaled into mm before costing. Unset/default mm => no line
    # added => byte-identical (the mm assumption stays the silent, unchanged
    # default it has always been).
    if options.units_is_user:
        from src.costing.units import unit_scale
        scale = unit_scale(options.units)
        # Only DISCLOSE the declaration when it ACTUALLY rescaled the geometry
        # (scale != 1.0). Declaring the canonical unit (mm, scale 1.0) is a no-op
        # that changes no number, so it adds NO line and stays byte-identical to
        # the unset default — honouring the "unspecified OR mm ⇒ identical" invariant.
        if scale != 1.0:
            out.append(Driver(
                "source_units", scale, "×", Provenance.USER,
                f"file units set to {options.units}: the geometry was scaled ×{scale:g} "
                f"into mm before pricing (volume ×{scale**3:g})"))
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

    # All process findings survive material/DFM filtering of cost estimates.
    feas = []
    for ps in result.process_scores:
        feas.append({
            "process": ps.process.value,
            "verdict": ps.verdict,
            "score": round(float(ps.score), 2),
            "costed": False,
            "blockers": [i.message for i in ps.issues if i.severity == Severity.ERROR],
        })

    # ── G1 ROBUSTNESS GATE (must be first) ──────────────────────────────
    has_error = any(i.severity == Severity.ERROR for i in result.universal_issues)
    invalid = (g.volume is None) or (g.volume <= 0.0) or (not g.is_watertight) or has_error
    if invalid:
        geo = _geo_summary(g)
        return DecisionReport(
            filename=result.filename,
            status="GEOMETRY_INVALID",
            reason=("Geometry is not a measurable solid (volume ≤ 0 or non-watertight). "
                    "Cost requires a watertight, positive-volume mesh. Repair required."),
            geometry=geo,
            material_class=options.material_class,
            quantities=list(options.quantities),
            engine_feasibility=feas,
            unit_warnings=_unit_plausibility_warnings(g, options),
        )

    # ── drivers → routing → cost/leadtime → decision ───────────────────
    drivers = extract_drivers(g, mesh, features)
    # Processes the engine's own DFM hard-fails (ERROR-level blocker) on THIS
    # part — routing must never headline a process the panel marks FAIL (F2).
    # dfm_clean is the DFM-clean fallback for the headline, ordered costed-first
    # then by score, so a demoted headline still prefers a costable option.
    dfm_failed = {ps.process for ps in result.process_scores
                  if ps.verdict == "fail" or ps.score <= 0}
    dfm_clean = [
        ps.process.value
        for ps in sorted(
            (ps for ps in result.process_scores if ps.verdict != "fail"),
            key=lambda ps: (ps.process not in COSTED_PROCESSES, -float(ps.score)),
        )
    ]
    elig = eligible_processes(result, drivers, options.material_class, rates,
                              strict_dfm=options.strict_dfm,
                              env=options.service_environment,
                              prefer=options.material_name)

    # ── Phase C: machine-inventory verification (additive; no-op when unused) ──
    # Only engaged when the org DECLARED machines OR a service environment. When
    # neither is present, verification stays None and machine_override_by_pv stays
    # empty, so every cost_breakdown call below gets machine_override=None and the
    # whole report is byte-identical to pre-Phase-C.
    verification = None
    from src.costing.part_specs import session_for as _spec_session
    specs = _spec_session(options, rates, region, drivers)   # None without declared specs
    machine_override_by_pv: dict = {}
    env_excluded: dict = {}
    if options.inventory:
        # A route a machine you own runs is priced in a material that machine
        # is declared for (the part's class), not the class's cheapest row.
        elig = _prefer_owned_materials(elig, options)
    if options.inventory or options.service_environment:
        verification, machine_override_by_pv, env_excluded = _build_verification(
            elig, drivers, options, rates, specs=specs)
    if options.inventory and verification is not None:
        # The inventory decides what is owned: a route a machine of yours clears
        # is priced as owned (capital sunk), declared or not; a declared process
        # cannot grant in-house savings when no machine of yours establishes fit.
        options = replace(options, owned_processes=frozenset(
            item["process"] for item in elig
            if verification["per_route"].get(item["process"].value, {}).get("verdict")
            in {"makeable_in_house", "makeable_with_secondary_op"}
        ))

    # Routes a machine the shop owns clears (§0 per-route in-house verdicts):
    # their lead time runs on the shop's own machines and the decision weighs
    # them against the cheapest outside route. Empty without inventory.
    in_house_by_pv = _in_house_routes(verification, options.inventory)

    estimates_serialized = []
    estimates_by_pq = {}             # (process_value, qty) -> CostEstimate (real per-qty)
    leadtimes_by_key = {}
    elig_by_pv = {}                  # process_value -> eligible item (for arbitrary-qty costing)

    cost_exclusions = {}
    sheet_gap = sheet_stock_gap(options.material_class) if drivers.sheet_like else None
    if sheet_gap and not any(item["process"].value == "sheet_metal" for item in elig):
        cost_exclusions["sheet_metal"] = sheet_gap
    for item in elig:
        process = item["process"]
        material = item["material"]
        ps = item["score"]
        for q in options.quantities:
            try:
                est = cost_breakdown(process, drivers, material, options.material_class,
                                     q, rates, region,
                                     n_cavities=options.n_cavities,
                                     complexity=options.complexity, process_score=ps,
                                     owned=process in options.owned_processes,
                                     tolerance_class=options.tolerance_class,
                                     machine_override=machine_override_by_pv.get(
                                         process.value))
            except BuildEnvelopeError as exc:
                # Fit is independent of quantity; never offer an impossible price
                # or feed it into recommendation/crossover/lead-time calculations.
                cost_exclusions[process.value] = str(exc)
                break
            elig_by_pv[process.value] = item
            # cycle_hr from the estimate keeps lead time consistent with cost
            cycle_hr = next((d.value for d in est.drivers if d.name == "cycle_time"), 0.0)
            lt = lead_time(process, cycle_hr, q, rates,
                           in_house=in_house_by_pv.get(process.value))
            if specs:
                est, lt = specs.price(est, lt, process, material, options.material_class)
            leadtimes_by_key[(process.value, q)] = lt
            estimates_by_pq[(process.value, q)] = est
            estimates_serialized.append(
                _serialize(est, lt, drivers, options.residual_model, options.ci_level,
                           options.calibration))

    costed_processes = {e["process"] for e in estimates_serialized}
    spec_excluded = specs.annotate(estimates_serialized, options.material_class) if specs else set()
    rec = recommend_routing(drivers, options.material_class,
                            dfm_failed=dfm_failed, dfm_clean=dfm_clean,
                            available_processes=costed_processes
                            - set(env_excluded.get("excluded_pv") or ()) - spec_excluded)
    routing_info = {
        "archetype": rec.archetype,
        "recommended_process": rec.process,
        "eval_family": rec.eval_family,
        "material_hint": rec.material_hint,
        "confidence": rec.confidence,
        "reasoning": rec.reasoning,
        "alternatives": rec.alternatives,
        "drivers": {
            **({"sheet_gauge_mm": drivers.sheet_gauge_mm,
                "planar_aspect": drivers.planar_aspect,
                "outline_perimeter_mm": drivers.outline_perimeter_mm,
                "bend_count": drivers.bend_count}
               if drivers.sheet_blank_mm is not None else {}),
            "nominal_wall_mm": round(drivers.nominal_wall_mm, 2),
            "rotational": drivers.rotational,
            "sheet_like": drivers.sheet_like,
        },
    } if rec is not None else None

    for row in feas:
        row["costed"] = row["process"] in costed_processes
        if row["process"] in cost_exclusions:
            row["cost_exclusion_reason"] = cost_exclusions[row["process"]]

    # ── env-excluded cost entries stay in the list, but carry an inline flag +
    # the SAME cited reason the verdict shows (Phase C coherence fix) so the cost
    # list and the make-vs-buy verdict can never be read incoherently. Only ever
    # populated when a service environment is declared; empty otherwise => no key
    # added => byte-identical.
    reason_by_pv = env_excluded.get("reason_by_pv") or {}
    if reason_by_pv:
        for e in estimates_serialized:
            reason = reason_by_pv.get(e["process"])
            if reason is not None:
                e["environment_excluded"] = True
                e["environment_exclusion_reason"] = reason

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
                             complexity=options.complexity, process_score=item["score"],
                             owned=item["process"] in options.owned_processes,
                             tolerance_class=options.tolerance_class,
                             machine_override=machine_override_by_pv.get(
                                 item["process"].value))
        if specs:
            est = specs.price(est, None, item["process"], item["material"],
                              options.material_class)[0]
        return est.unit_cost_usd

    range_by_key = {
        (e["process"], e["quantity"]): (e["confidence"].get("low_usd"),
                                        e["confidence"].get("high_usd"))
        for e in estimates_serialized
        if isinstance(e.get("confidence"), dict)
        and e["confidence"].get("low_usd") is not None
    } if in_house_by_pv else None
    decision = make_vs_buy(estimates_by_pq, options.quantities, leadtimes_by_key,
                           unit_cost_fn=_unit_cost_fn,
                           excluded_pv=(set(env_excluded.get("excluded_pv") or ()) | spec_excluded)
                           or None,
                           env_note="; ".join(n for n in (env_excluded.get("note"),
                                                          specs.note(spec_excluded) if specs else None)
                                              if n) or None,
                           in_house=in_house_by_pv,
                           range_by_key=range_by_key)

    notes = list(cost_exclusions.values())
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
                "Priced, but can't make the part as drawn: " + join_labels(flagged) + ". "
                "Their prices show what the part would cost if it were redesigned for "
                "them; each one's findings say what stops it.")
    # geometric routing recommendation, and reconciliation with the cost pick
    if rec is None:
        notes.append("No eligible process suits this shape and can make it as drawn in the "
                     "declared material. See each process's findings.")
    else:
        notes.append(f"Shape suggests {process_phrase(rec.process)}. {rec.reasoning}")
    if rec is not None and decision is not None and decision.make_now_process != rec.process:
        in_shortlist = any(e["process"] == rec.process for e in estimates_serialized)
        lo_pick = (decision.recommendation.get(min(options.quantities)) or {}) if options.quantities else {}
        if in_shortlist and lo_pick.get("in_house"):
            notes.append(
                f"{OWNED_PICK_NOTE_PREFIX}{process_phrase(decision.make_now_process)} on "
                f"machine '{lo_pick.get('machine')}'; the shape suggests "
                f"{process_phrase(rec.process)}. {_CHOOSE_ON_INTENT}")
        elif in_shortlist:
            notes.append(
                f"At low quantity the cheapest way to make it as drawn is "
                f"{process_phrase(decision.make_now_process)}; the shape suggests "
                f"{process_phrase(rec.process)}. {_CHOOSE_ON_INTENT}")
        else:
            notes.append(
                f"The shape suggests {process_phrase(rec.process)}, which ScaleCAD doesn't "
                f"price; the prices above are the processes it does.")
    notes.append(
        "Prices and crossover quantities are assumption-based and can shift with "
        "cycle times, tooling, batch sizes and shop rates. Validate against actual "
        "quotes before making a sourcing commitment.")
    # If the environment excluded EVERY make-as-is pair, the decision is honestly
    # ABSENT (None) — surface WHY at the report level so the (None) verdict and
    # the cost list (whose surviving entries carry the exclusion flag) can never
    # be read as a silent omission.
    if decision is None and env_excluded.get("note"):
        notes.append(
            "Decision: no environment-valid make-as-is option — "
            + env_excluded["note"] + ".")
    elif decision is None and spec_excluded:
        notes.append("Decision: no route meets the declared specs; "
                     + specs.note(spec_excluded) + ".")

    geo = _geo_summary(g)
    return DecisionReport(
        filename=result.filename,
        status="OK",
        geometry=geo,
        material_class=options.material_class,
        quantities=list(options.quantities),
        estimates=estimates_serialized,
        decision=decision,
        assumptions=_global_assumptions(rates, options, region),
        engine_feasibility=feas,
        notes=notes,
        routing=routing_info,
        verification=verification,
        unit_warnings=_unit_plausibility_warnings(g, options),
        specs=specs.block(estimates_serialized) if specs else None,
    )


_IN_HOUSE_VERDICTS = ("makeable_in_house", "makeable_with_secondary_op")


def _prefer_owned_materials(elig: list, options) -> list:
    """Price a route your machine runs in a material that machine is declared for.

    The shortlist prices each route in the cheapest registry material of the
    part's class (PLA for plastic on a filament printer). When the shop owns
    machines for that route and none is declared for that material, the route is
    re-priced in the cheapest material of the same class that one of them is
    declared for (ABS on a Stratasys F900), so the fit and the price are about
    the material the shop would actually use. No such material: unchanged, and
    the fit says the machine isn't declared for it.
    """
    from src.costing.makeability import material_declared
    from src.costing.rates import MATERIAL_FAMILY
    from src.costing.routing import _env_preferred_materials
    from src.analysis.models import ProcessType as _PT
    from src.profiles.database import get_materials_for_process

    out = []
    cls = options.material_class
    for item in elig:
        process = item["process"]
        machines = [m for m in options.inventory
                    if getattr(m.process, "value", m.process) == process.value and m.materials]
        mat = item["material"]
        named = getattr(options, "material_name", None)
        if named:
            from src.costing.material_grades import same_grade

            if same_grade(mat.name, named):
                # The grade the parts list names stays: a machine not declared for it
                # says so in its fit instead of the route moving to another grade.
                out.append(item)
                continue
        if (not machines or process == _PT.SHEET_METAL
                or any(material_declared(mat.name, MATERIAL_FAMILY.get(mat.name, ""), m.materials)
                       for m in machines)):
            out.append(item)
            continue
        cands = [m for m in get_materials_for_process(process)
                 if MATERIAL_FAMILY.get(m.name) == cls and m.density and m.cost_per_kg
                 and any(material_declared(m.name, cls, mc.materials) for mc in machines)]
        if options.service_environment and cands:
            cands = _env_preferred_materials(process, cands, options.service_environment)
        out.append({**item, "material": min(cands, key=lambda m: m.cost_per_kg)} if cands else item)
    return out
# A note that names the shop's own machine starts with this (public shares drop it).
OWNED_PICK_NOTE_PREFIX = "On a machine you own, the cheapest way to make it as drawn at low quantity is "
_CHOOSE_ON_INTENT = "Both are priced above; choose on what the part is for, not on price alone."


def _in_house_routes(verification, inventory) -> dict:
    """``{process_value: {"machine", "count"}}`` for each route a machine the
    shop owns clears, read off the serialized §0 verdict. ``count`` is the
    fitted machine's declared count (1 when undeclared)."""
    if not verification or not inventory:
        return {}
    out = {}
    for pv, info in (verification.get("per_route") or {}).items():
        if info.get("verdict") not in _IN_HOUSE_VERDICTS:
            continue
        name = info.get("best_machine")
        cap = next((m for m in inventory
                    if getattr(m.process, "value", m.process) == pv and m.name == name), None)
        count = getattr(cap, "count", None)
        out[pv] = {"machine": name or pv,
                   "count": count if isinstance(count, int) and count > 0 else 1}
    return out


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
    d = {
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
    # First-class make-it-ourselves flag: present (True) ONLY when this process
    # was costed as OWNED in-house (marginal machine rate). Absent otherwise, so
    # the default / off-switch paths stay byte-identical.
    if getattr(est, "owned_in_house", False):
        d["owned_in_house"] = True
    if getattr(est, "material_mass", None):
        # Mass and density as fields: readers stop parsing "= X kg × $Y/kg".
        d["material_mass"] = dict(est.material_mass)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Phase C — machine-inventory verification (spec §5, §7)
# ─────────────────────────────────────────────────────────────────────────────


def _jsonable(v):
    """Coerce a FitFailure ``need``/``have`` (which may be a tuple/set/dict) to a
    JSON-serializable value, recursively. Numbers/strings/None/bool pass through."""
    if isinstance(v, tuple):
        return [_jsonable(x) for x in v]
    if isinstance(v, set):
        return sorted((_jsonable(x) for x in v), key=lambda x: str(x))
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


def _ff_to_dict(f) -> dict:
    """One FitFailure → a serializable gate record (why a machine passed/failed)."""
    return {"gate": f.gate, "axis": f.axis, "need": _jsonable(f.need),
            "have": _jsonable(f.have), "human": f.human}


def _env_label(env) -> str:
    """A short human label for the declared environment (for the decision note)."""
    if not env:
        return "declared environment"
    bits = []
    if env.get("sour_service") or env.get("sour"):
        bits.append("sour service")
    if env.get("corrosive"):
        bits.append("corrosive service")
    mt = env.get("max_temp_c")
    if isinstance(mt, (int, float)) and not isinstance(mt, bool):
        bits.append(f"{mt:g}C service")
    return ", ".join(bits) if bits else "declared environment"


def _env_decision_note(env, excluded_materials, excluded_routes=()) -> str:
    """The decision-note clause stating WHY the make-vs-buy shortlist shrank —
    e.g. 'environment (sour service) excludes Mild Steel; decision computed over
    NACE-qualified materials'."""
    parts = list(excluded_materials) + [f"route {r}" for r in excluded_routes]
    excl = ", ".join(parts) if parts else "some options"
    sour = bool(env and (env.get("sour_service") or env.get("sour")))
    over = "NACE-qualified materials" if sour else "the environment-valid materials"
    return (f"environment ({_env_label(env)}) excludes {excl}; "
            f"decision computed over {over}")


def _build_verification(elig, drivers, options, rates, specs=None):
    """Compute the §0 makeability verdict + per-process marginal-rate overrides.

    Returns ``(verification_dict, machine_override_by_pv, env_excluded)`` where
    ``env_excluded`` carries the DECLARED-environment gate's dropped (process,
    material) pairs: ``reason_by_pv`` (route -> the CITED exclusion reason, for the
    inline estimate flag), ``excluded_pv`` (the set the decision drops from its
    shortlist), and ``note`` (the decision-note clause, or None). Empty when no
    environment is declared => byte-identical. Called ONLY when the org declared
    machines or a service environment (the caller guards the no-op). The
    environment gate + machine fit are the PURE ``makeability`` engine; the
    machine override for a PASSING owned machine (its OWN declared rate) is read
    straight from ``verify_part``'s per-route resource hint, so the cost seam and
    the verdict can never disagree.
    """
    from dataclasses import asdict, is_dataclass

    from src.costing.makeability import (
        environment_gate,
        part_req_from_drivers,
        verify_part,
    )
    from src.costing.provenance import Provenance

    env = options.service_environment or None
    inventory = list(options.inventory or ())
    shop_caps = options.shop_caps

    part_req_by_route: dict = {}
    material_props: dict = {}
    for item in elig:
        process = item["process"]
        mat = item["material"]
        # MaterialProfile → the exact nested-compliance dict shape the env gate
        # reads (nace_mr0175/sour_service under 'compliance', max_temperature at
        # top level). asdict is the loader-faithful shape the real-profile
        # integration test pins.
        props = asdict(mat) if is_dataclass(mat) else {
            "name": getattr(mat, "name", str(mat)),
            "density": getattr(mat, "density", None),
        }
        # The route's own DFM score rides along so a design-blocked route can
        # never read makeable on a machine fit alone (same verdict as dfm_ready).
        preq = part_req_from_drivers(process, drivers, mat,
                                     options.tolerance_class,
                                     material_props=props, env=env,
                                     process_score=item.get("score"))
        if process.value == "binder_jetting":
            scale = 1 + rates.p(process, "shrinkage_linear")
            # The green part is printed oversize so it shrinks to size when
            # sintered: that larger part is what has to fit the machine.
            preq = replace(preq, bbox_mm=tuple(d * scale for d in preq.bbox_mm),
                           print_oversize=scale - 1,
                           geometry_precision_mm=preq.geometry_precision_mm * scale,
                           geometry_tolerance_mm=preq.geometry_tolerance_mm * scale,
                           minimum_width_bound_mm=preq.minimum_width_bound_mm * scale,
                           enclosing_cylinder_mm=(tuple(d * scale for d in preq.enclosing_cylinder_mm)
                                                  if preq.enclosing_cylinder_mm else None))
        if specs:
            preq = specs.part_req(preq, process, mat, options.material_class)
        part_req_by_route[process.value] = preq
        if preq.material_name:
            material_props[preq.material_name] = props

    verdict = verify_part(part_req_by_route, inventory, shop_caps=shop_caps,
                          env=env, material_props=material_props)

    # Environment exclusions run independently of inventory: verify_part
    # short-circuits to a bare ``unknown`` when NO machines are declared, so for
    # the env-only case (declared environment, no inventory) we surface the cited
    # exclusions directly. When inventory IS present, verify_part already ran the
    # SAME gate, so verdict.env_exclusions is authoritative and used as-is.
    routes = list(part_req_by_route.keys())
    materials = list({p.material_name for p in part_req_by_route.values()
                      if p.material_name})
    _gate, direct_exclusions = environment_gate(routes, materials, env,
                                                material_props)
    env_exclusions = verdict.env_exclusions or direct_exclusions

    # Per-process marginal-rate override from each PASSING route's fitted machine.
    machine_override_by_pv: dict = {}
    for pv, info in verdict.per_route.items():
        res = info.get("resource")
        if not res:
            continue
        rate = res.get("hourly_rate_usd")
        if res.get("build_env_mm") or (isinstance(rate, (int, float)) and not isinstance(rate, bool)):
            machine_override_by_pv[pv] = {
                "hourly_rate_usd": rate,
                "capital_frac": res.get("capital_frac"),
                "machine_name": res.get("machine"),
                **({"build_env_mm": res["build_env_mm"]} if res.get("build_env_mm") else {}),
                # Persistence does not turn a user declaration into calibration.
                "provenance": Provenance.USER,
            }

    # ── env-excluded (process, material) pairs → decision shortlist + estimate
    # flags. ONLY populated when a service environment is declared (env falsy =>
    # the gate returns empty exclusion sets => everything below stays empty =>
    # byte-identical). Each affected route carries the SAME cited FitFailure.human
    # the verdict shows, so the cost list and the verdict cannot disagree.
    reason_by_axis = {f.axis: f.human for f in env_exclusions}
    excluded_materials = _gate.get("excluded_materials") or set()
    excluded_routes = _gate.get("excluded_routes") or set()
    reason_by_pv: dict = {}
    for pv, preq in part_req_by_route.items():
        mat = preq.material_name
        if mat and mat in excluded_materials:
            reason_by_pv[pv] = reason_by_axis.get(
                mat, f"{mat} excluded by declared service environment")
        elif pv in excluded_routes:
            reason_by_pv[pv] = reason_by_axis.get(
                pv, f"route {pv} excluded by declared service environment")
    env_excluded = {
        "reason_by_pv": reason_by_pv,
        "excluded_pv": set(reason_by_pv.keys()),
        "note": (_env_decision_note(env, sorted(excluded_materials),
                                    sorted(excluded_routes))
                 if reason_by_pv else None),
    }

    verification = _serialize_verification(verdict, options, env_exclusions)
    return verification, machine_override_by_pv, env_excluded


def _serialize_verification(verdict, options, env_exclusions=()) -> dict:
    """Serialize a MakeabilityVerdict into the report's ``verification`` block.

    Honest by construction: negative/unknown verdicts are FIRST-CLASS (``unknown``
    when no inventory is declared, ``makeable_not_on_owned`` with a concrete gap,
    ``makeable_outsource_only``, ``environment_excluded``, ``not_makeable`` — incl.
    a route whose own DFM verdict is fail, with its ``dfm`` blockers); a machine
    fit is a MEASURED-geometry × USER-capability comparison, never a fabricated
    pass.
    """
    per_route: dict = {}
    for pv, info in verdict.per_route.items():
        entry = {
            "verdict": info.get("verdict"),
            "machines_evaluated": info.get("machines_evaluated", 0),
            "best_machine": info.get("best_machine"),
            "failures": [_ff_to_dict(f) for f in info.get("failures", ())],
        }
        res = info.get("resource")
        if res:
            entry["machine_rate_usd"] = res.get("hourly_rate_usd")
            entry["capital_frac"] = res.get("capital_frac")
            entry["secondary_ops"] = list(res.get("secondary_ops", ()))
            if res.get("maker_spec"):
                # The fit used the maker's published values for these fields
                # (a catalog machine kept unedited), not the shop's own.
                entry["maker_spec"] = {"catalog": res["maker_spec"]["catalog"],
                                       "fields": list(res["maker_spec"]["fields"])}
            if res.get("assumed_in_house"):
                # The machine's own post-processing (stress relief, sintering)
                # assumed done in-house: Your shop never said it's sent out.
                entry["assumed_in_house"] = list(res["assumed_in_house"])
            if res.get("sent_out"):
                entry["sent_out"] = list(res["sent_out"])
            if res.get("notes"):
                # What the fit didn't check or assumed, said plainly, e.g. a printer
                # with no plate load: "weight: no plate load published or declared;
                # build volume governs".
                entry["notes"] = list(res["notes"])
        per_route[pv] = entry
    return {
        "verdict": verdict.verdict,
        "best_machine": verdict.best_machine,
        "resource": _jsonable(verdict.resource) if verdict.resource else None,
        "gap": [_ff_to_dict(f) for f in verdict.gap],
        "env_exclusions": [_ff_to_dict(f) for f in env_exclusions],
        "per_route": per_route,
        "inventory_declared": bool(options.inventory),
        "environment_declared": bool(options.service_environment),
        # The machine capabilities + declared environment are USER assertions; a
        # "fits" verdict on the envelope is MEASURED-geometry × USER-capability.
        "provenance": "user",
        "note": (
            "Machine fit compares the part's measured size and features with what was "
            "declared for each machine. It reads \"can't confirm\" when a machine's "
            "capabilities aren't declared or no fitting setup is established. The one "
            "thing it assumes, and says on the fit: a shop that owns a metal printer or "
            "binder jetter does that machine's own stress relief or sintering, unless Your "
            "shop says it's sent out. A process that fails its design checks can't make the part "
            "as drawn, whatever machine fits. Material exclusions cite the property or "
            "standard. Not checked here: whether the part needs 5-axis or undercut access "
            "comes from the process checks, not a new measurement; press force (tonnage, "
            "taper) needs a declared force."
        ),
    }
