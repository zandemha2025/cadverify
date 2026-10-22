"""Decision layer (spec §8 + V1 fix-spec §8) — crossover + make-vs-buy.

Coherent semantics (resolves weaknesses #6, #7):

  MAKE-NOW set = polymer/metal additive, CNC, EDM and sheet fabrication
  TOOLING  set = molding, casting and forging (dies/patterns)
  DFM-ready    = engine verdict != "fail"

  make_now      = argmin over DFM-ready MAKE-NOW estimates at q_lo (real unit cost)
                  ≡ recommendation[q_lo].process   (single source — cannot disagree)
  tool_champion = argmin over TOOLING estimates at q_hi (may be DFM-fail)
  crossover     = tool_champion versus the cheapest eligible MAKE-NOW route
                  at each quantity (the winning make route may change)

The headline make process is drawn ONLY from DFM-ready make candidates, so it is
never a process the part currently fails. The tooling route may be DFM-fail; if
so it is presented conditionally ("if redesigned for molding"), never asserted.

Owned machines (``in_house``): when a machine the shop owns clears every fit
gate for a DFM-ready make route, the recommendation at each quantity compares
the cheapest such in-house route with the cheapest outside route and applies
``IN_HOUSE_RULE`` (below). Both sides are kept in ``Decision.options`` so the
answer can show them next to each other. No owned machine fits => no options,
the recommendation is the cheapest route exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.analysis.models import ProcessType
from src.analysis.process_names import process_label, process_phrase
from src.costing.rates import process_family

_PV_TO_PT = {pt.value: pt for pt in ProcessType}

MAKE_NOW_FAMILIES = (
    "additive", "subtractive", "fabrication", "edm",
    "metal_powder_bed", "binder_jet", "ded",
)
TOOLING_FAMILIES = ("formative", "casting", "forging")

# Why the owned machine is preferred inside the estimate's own range: two
# should-cost estimates whose difference is smaller than their stated
# uncertainty can't be told apart by this model, and making it on a machine
# the shop owns keeps the schedule, the shipping and the file in-house.
IN_HOUSE_RULE = (
    "A machine you own that clears every check is recommended unless an outside "
    "route is cheaper and either costs less than the low end of the in-house "
    "estimate's range or arrives sooner beyond doubt (its slowest lead time is "
    "quicker than the in-house quickest). Inside that range the model can't tell "
    "the two prices apart, and your own machine keeps the schedule and the file "
    "in-house."
)


@dataclass
class Decision:
    make_now_process: str                  # headline make (argmin DFM-ready make at q_lo)
    make_now_material: str
    tooling_process: Optional[str]         # production/tooling candidate (may be DFM-fail)
    tooling_dfm_ready: bool
    crossover_qty: Optional[float]         # q*  (None if no meaningful crossover)
    recommendation: dict = field(default_factory=dict)   # q -> tier-1 make-as-is pick
    if_redesigned: dict = field(default_factory=dict)    # q -> tier-2 cheaper-if-redesigned | None
    note: str = ""
    # q -> {"in_house": {...}, "outside": {...} | None, "pick", "basis"}: the
    # cheapest route on a machine the shop owns next to the cheapest outside
    # route. Empty when no owned machine clears a DFM-ready make route (then
    # report_to_dict drops it and ``rule`` so the output is byte-identical).
    options: dict = field(default_factory=dict)
    rule: str = ""


def crossover(fixed_a: float, var_a: float, fixed_b: float, var_b: float) -> Optional[float]:
    """q* where process A and B cost the same per unit. Only meaningful for q>1.

    unit_a(q) = fixed_a/q + var_a ; unit_b(q) = fixed_b/q + var_b
    => q* = (fixed_b - fixed_a) / (var_a - var_b)

    CLOSED FORM — exact only when both variable costs are qty-CONSTANT. Once a
    make process carries a volume/learning curve (S1: machining conversion cost
    falls with qty) its variable cost is qty-dependent and this formula is no
    longer exact; the decision layer then prefers ``_numerical_crossover`` (below),
    which scans the ACTUAL per-qty unit costs. This form is retained for the
    constant-variable case and as a documented fallback.
    """
    if var_a == var_b:
        return None
    q = (fixed_b - fixed_a) / (var_a - var_b)
    return q if q > 1 else None


def _numerical_crossover(unit_cost_fn, make_pv: str | tuple[str, ...], tool_pv: str,
                         q_lo: float, q_cap: int = 10_000_000) -> Optional[float]:
    """Honest crossover for qty-DEPENDENT unit costs (S1 volume/learning).

    Finds an integer crossing where the tooling route's ACTUAL per-unit cost
    drops to/below the cheapest supplied make route's ACTUAL per-unit cost, by
    evaluating both real cost curves (``unit_cost_fn(process_value, q)``) — no
    fixed/variable reconstruction. Bracketing assumes a sustained transition;
    batch steps can produce local recrossings, so the result remains approximate.
    None when tooling does not overtake make in the sampled bracket within
    ``q_cap`` (or is already cheaper at q_lo). Monotone in tooling fixed cost:
    a pricier tool pushes the crossover right, as expected.
    """
    make_pvs = (make_pv,) if isinstance(make_pv, str) else make_pv

    def diff(q: int) -> float:                       # >0 once tooling is the cheaper route
        return min(unit_cost_fn(pv, int(q)) for pv in make_pvs) - unit_cost_fn(tool_pv, int(q))

    lo = max(2, int(q_lo))
    if diff(lo) >= 0:
        return None                                  # tooling already cheaper at low qty
    hi = lo
    while hi < q_cap and diff(hi) < 0:
        hi = min(hi * 2, q_cap)                      # geometric bracket for the sign change
    if diff(hi) < 0:
        return None                                  # tooling never wins within the cap
    while hi - lo > 1:                               # bisect to the crossover integer
        mid = (lo + hi) // 2
        if diff(mid) < 0:
            lo = mid
        else:
            hi = mid
    return float(hi) if hi > 1 else None


def _family(pv: str) -> str:
    pt = _PV_TO_PT.get(pv)
    return process_family(pt) if pt is not None else "additive"


def _caveat(est) -> str:
    """Short tier-2 caveat (why this cheaper option is not the make-as-is pick)."""
    fam = _family(est.process)
    if not est.dfm_ready:
        blocker = (est.dfm_blockers[0].lower() if est.dfm_blockers else "")
        if "undercut" in blocker:
            reason = "remove undercuts"
        elif "draft" in blocker:
            reason = "add draft"
        else:
            reason = "redesign for DFM"
        if fam in TOOLING_FAMILIES:
            reason += ", tooling-dominated"
        return reason
    if fam in TOOLING_FAMILIES:
        return "invest in tooling"
    return ""


def _side(est, lt, rng) -> dict:
    """One side of the in-house / outside comparison, from engine numbers only."""
    lo, hi = rng if rng else (None, None)
    if lo is None:
        band = float(est.est_error_band_pct or 0) / 100.0
        lo, hi = est.unit_cost_usd * (1 - band), est.unit_cost_usd * (1 + band)
    return {
        "process": est.process,
        "material": est.material,
        "unit_cost_usd": round(est.unit_cost_usd, 2),
        "low_usd": round(lo, 2),
        "high_usd": round(hi, 2),
        "lead_low_days": lt.low_days if lt else None,
        "lead_high_days": lt.high_days if lt else None,
        "dfm_verdict": est.dfm_verdict,
    }


def prefer_in_house(inside: dict, outside: Optional[dict]) -> tuple[str, str]:
    """Apply ``IN_HOUSE_RULE`` to the two sides; returns ``(pick, basis)``.

    pick: "in_house" | "outside". basis:
      in_house_only          no outside route is priced
      in_house_cheapest      the owned machine is the cheapest way outright
      in_house_within_range  outside is cheaper, but inside the in-house range
                             and not sooner beyond doubt
      outside_cheaper        outside costs less than the in-house range's low end
      outside_sooner         outside is cheaper and its slowest lead time beats
                             the in-house quickest
    """
    if outside is None:
        return "in_house", "in_house_only"
    if inside["unit_cost_usd"] <= outside["unit_cost_usd"]:
        return "in_house", "in_house_cheapest"
    o_hi, i_lo = outside.get("lead_high_days"), inside.get("lead_low_days")
    if o_hi is not None and i_lo is not None and o_hi < i_lo:
        return "outside", "outside_sooner"
    if outside["unit_cost_usd"] < inside["low_usd"]:
        return "outside", "outside_cheaper"
    return "in_house", "in_house_within_range"


def make_vs_buy(estimates_by_pq: dict, quantities, leadtimes_by_key,
                unit_cost_fn=None, excluded_pv=None, env_note=None,
                in_house=None, range_by_key=None,
                outside_twins=None) -> Optional[Decision]:
    """estimates_by_pq: {(process_value, qty): CostEstimate} for every eligible
    (process, qty). Decision ranks by REAL per-qty unit cost (not a fixed/var
    reconstruction), so the headline make process and the low-qty recommendation
    are computed from the same ranking and can never disagree.

    unit_cost_fn (optional): ``(process_value, qty) -> unit_cost_usd``, a real
    cost evaluator at ARBITRARY qty. When supplied, the make-vs-buy crossover is
    computed NUMERICALLY from the actual per-qty cost curves — the honest method
    once machining variable cost falls with volume (S1). Falls back to the
    closed-form ``crossover`` (single-qty fixed/var split) when absent.

    excluded_pv (optional): the set of process_values whose (process, material)
    pair the DECLARED service-environment gate ruled out (spec §6). Those routes
    are DROPPED from the shortlist the crossover / recommendation / if-redesigned
    tiers range over, so the headline can never recommend an environment-invalid
    material while the verdict cites its exclusion. EMPTY / None (the default, and
    every no-environment path) => nothing is dropped and the whole decision — the
    ranking AND the note — is byte-identical to pre-gate behaviour.
    env_note (optional): a pre-built human clause naming the environment
    constraint; appended to ``note`` ONLY when the exclusion actually changed the
    make-as-is headline (see below).
    in_house (optional): ``{process_value: {"machine": name, "count": n}}`` for
    every route a machine the shop owns clears (the §0 per-route in-house
    verdicts). When one of them is a DFM-ready make route at a quantity, that
    quantity's recommendation follows ``prefer_in_house`` and both sides land in
    ``options``. None / empty => the cheapest route, byte-identical.
    range_by_key (optional): ``{(process_value, qty): (low_usd, high_usd)}``, the
    estimate's served confidence range, so the rule reads the same range the
    answer shows. Absent => the estimate's assumption band.
    outside_twins (optional): ``{(process_value, qty): (estimate, lead_time,
    (low, high))}``, each in-house route priced as an outside shop runs it. They
    join the outside side's candidates (a plate milled on your mill is compared
    with a job shop's 3-axis mill, not only with routes you don't own); that
    side then says ``same_process: True``. None => unchanged.
    """
    if not estimates_by_pq:
        return None

    quantities = list(quantities)
    q_lo, q_hi = min(quantities), max(quantities)
    excluded_pv = set(excluded_pv or ())
    all_pv = sorted({pv for (pv, _q) in estimates_by_pq})
    proc_values = [pv for pv in all_pv if pv not in excluded_pv]

    def est_at(pv, q):
        return estimates_by_pq[(pv, q)]

    def make_ready_ranked(q, pvs=None):
        pvs = proc_values if pvs is None else pvs
        cands = [est_at(pv, q) for pv in pvs
                 if _family(pv) in MAKE_NOW_FAMILIES and est_at(pv, q).dfm_ready]
        return sorted(cands, key=lambda e: e.unit_cost_usd)

    def make_any_ranked(q, pvs=None):  # fallback if no DFM-ready make process exists
        pvs = proc_values if pvs is None else pvs
        cands = [est_at(pv, q) for pv in pvs if _family(pv) in MAKE_NOW_FAMILIES]
        return sorted(cands, key=lambda e: e.unit_cost_usd)

    def tool_ranked(q):
        cands = [est_at(pv, q) for pv in proc_values if _family(pv) in TOOLING_FAMILIES]
        return sorted(cands, key=lambda e: e.unit_cost_usd)

    ready_lo = make_ready_ranked(q_lo) or make_any_ranked(q_lo)
    if not ready_lo:
        # Every make-as-is candidate was environment-excluded (or none existed):
        # honestly ABSENT — no recommendation is fabricated from an excluded pair.
        # Aligns with the absent-decision shape (report_to_dict serializes None,
        # exactly as it does for GEOMETRY_INVALID / no-estimates).
        return None
    cheapest_lo = ready_lo[0]
    in_house = dict(in_house or {})
    range_by_key = range_by_key or {}

    def pick_at(q):
        """(tier-1 pick, cheapest, options entry | None) at one quantity."""
        ranked = make_ready_ranked(q) or make_any_ranked(q)
        cheapest = ranked[0]
        inside = [e for e in make_ready_ranked(q) if e.process in in_house]
        if not inside:
            return cheapest, cheapest, None
        i_est = inside[0]
        outs = [(e, leadtimes_by_key.get((e.process, q)), range_by_key.get((e.process, q)), False)
                for e in make_ready_ranked(q) if e.process not in in_house]
        for (pv, tq), (t_est, t_lt, t_rng) in (outside_twins or {}).items():
            if tq == q and pv not in excluded_pv and _family(pv) in MAKE_NOW_FAMILIES and t_est.dfm_ready:
                outs.append((t_est, t_lt, t_rng, True))
        outs.sort(key=lambda o: o[0].unit_cost_usd)
        o_est = outs[0][0] if outs else None
        i_side = _side(i_est, leadtimes_by_key.get((i_est.process, q)),
                       range_by_key.get((i_est.process, q)))
        i_side["machine"] = in_house[i_est.process].get("machine")
        i_side["machine_count"] = in_house[i_est.process].get("count")
        o_side = None
        if outs:
            o_side = _side(o_est, outs[0][1], outs[0][2])
            if outs[0][3]:
                o_side["same_process"] = True
        pick, basis = prefer_in_house(i_side, o_side)
        entry = {"in_house": i_side, "outside": o_side, "pick": pick, "basis": basis}
        return (i_est if pick == "in_house" else o_est), cheapest, entry

    make_now = pick_at(q_lo)[0]

    tools_hi = tool_ranked(q_hi)
    tool_champion = tools_hi[0] if tools_hi else None

    q_star = None
    if tool_champion is not None and tool_champion.process != make_now.process:
        if unit_cost_fn is not None:
            q_star = _numerical_crossover(unit_cost_fn, tuple(e.process for e in ready_lo),
                                          tool_champion.process, q_lo)
        else:
            # For constant-variable curves, tooling must beat every make route.
            crossings = []
            for make in ready_lo:
                delta_var = make.variable_cost_usd - tool_champion.variable_cost_usd
                delta_fixed = tool_champion.fixed_cost_usd - make.fixed_cost_usd
                if delta_var < 0 or (delta_var == 0 and delta_fixed > 0):
                    break  # this make route remains cheaper at high volume
                crossings.append(delta_fixed / delta_var if delta_var > 0 else 0)
            else:
                candidate = max(crossings)
                q_star = candidate if candidate > max(1, q_lo) else None

    # ---- per-qty tiers --------------------------------------------------
    recommendation: dict = {}
    if_redesigned: dict = {}
    options: dict = {}
    for q in quantities:
        tier1, _cheapest, entry = pick_at(q)
        lt = leadtimes_by_key.get((tier1.process, q))
        lead = (lt.low_days if lt else None, lt.high_days if lt else None)
        twin = (entry is not None and entry["pick"] == "outside"
                and (entry.get("outside") or {}).get("same_process"))
        if twin:
            # Your machine's process, bought from a shop: its lead time, not yours.
            lead = (entry["outside"]["lead_low_days"], entry["outside"]["lead_high_days"])
        recommendation[q] = {
            "process": tier1.process,
            "material": tier1.material,
            "unit_cost_usd": round(tier1.unit_cost_usd, 2),
            "dfm_ready": tier1.dfm_ready,
            "dfm_verdict": tier1.dfm_verdict,
            "lead_low_days": lead[0],
            "lead_high_days": lead[1],
        }
        if twin:
            recommendation[q]["same_process_outside"] = True
        if entry is not None:
            options[q] = entry
            recommendation[q]["in_house"] = entry["pick"] == "in_house"
            recommendation[q]["basis"] = entry["basis"]
            if entry["pick"] == "in_house":
                recommendation[q]["machine"] = entry["in_house"]["machine"]
        # tier-2: cheapest estimate that beats tier-1 but is DFM-fail OR tooling
        cheaper = [
            est_at(pv, q) for pv in proc_values
            if est_at(pv, q).unit_cost_usd < tier1.unit_cost_usd
            and (not est_at(pv, q).dfm_ready or _family(pv) in TOOLING_FAMILIES)
        ]
        if cheaper:
            alt = min(cheaper, key=lambda e: e.unit_cost_usd)
            if_redesigned[q] = {
                "process": alt.process,
                "material": alt.material,
                "unit_cost_usd": round(alt.unit_cost_usd, 2),
                "caveat": _caveat(alt),
            }
        else:
            if_redesigned[q] = None

    note = _build_note(cheapest_lo, tool_champion, q_star, q_lo, q_hi,
                       round(cheapest_lo.unit_cost_usd, 2),
                       round(tool_champion.unit_cost_usd, 2) if tool_champion else None,
                       recommendation)

    # State the environment constraint in the note ONLY when it CHANGED the
    # make-as-is headline: the cheapest make candidate over the FULL (unfiltered)
    # shortlist was environment-excluded, so the surviving pick differs. No
    # exclusion / unchanged headline => the note is byte-identical.
    if excluded_pv and env_note:
        full_ready_lo = (make_ready_ranked(q_lo, pvs=all_pv)
                         or make_any_ranked(q_lo, pvs=all_pv))
        if full_ready_lo and full_ready_lo[0].process != cheapest_lo.process:
            note = note + " " + env_note

    # Last, so a public share can cut it off whole (it names the sharer's machines).
    if options:
        note = note + " " + _in_house_clause(options)

    return Decision(
        make_now_process=make_now.process,
        make_now_material=make_now.material,
        tooling_process=tool_champion.process if tool_champion else None,
        tooling_dfm_ready=bool(tool_champion.dfm_ready) if tool_champion else True,
        crossover_qty=round(q_star, 1) if q_star else None,
        recommendation=recommendation,
        if_redesigned=if_redesigned,
        note=note,
        options=options,
        rule=IN_HOUSE_RULE if options else "",
    )


_BASIS_TEXT = {
    "in_house_only": "no outside route is priced",
    "in_house_cheapest": "it is the cheapest route",
    "in_house_within_range": "the outside route is cheaper but inside the in-house estimate's range",
    "outside_cheaper": "the outside route costs less than the low end of the in-house range",
    "outside_sooner": "the outside route is cheaper and arrives sooner beyond doubt",
}


def _in_house_clause(options: dict) -> str:
    """One sentence per quantity: the in-house side, the outside side, the pick."""
    bits = []
    for q, o in sorted(options.items()):
        i, out = o["in_house"], o["outside"]
        side = (f"at {q:,}: in-house {process_phrase(i['process'])} on {i['machine']} "
                f"${i['unit_cost_usd']} each"
                + (f", outside {process_phrase(out['process'])} ${out['unit_cost_usd']} each"
                   if out else ""))
        pick = ("in-house" if o["pick"] == "in_house" else "outside")
        bits.append(f"{side}; pick {pick} ({_BASIS_TEXT[o['basis']]})")
    return OWNED_CLAUSE_PREFIX + "; ".join(bits) + "."


# The decision note's owned-machine clause starts with this and ends the note.
OWNED_CLAUSE_PREFIX = "Owned machines: "


def _picks_by_quantity(recommendation: dict) -> str:
    """``"1: filament printing (FDM/FFF); 10 to 10,000: nylon powder printing (MJF)"``."""
    runs: list = []
    for q, pick in sorted(recommendation.items()):
        if runs and runs[-1][2] == pick["process"]:
            runs[-1][1] = q
        else:
            runs.append([q, q, pick["process"]])
    return "; ".join((f"{a:,}" if a == b else f"{a:,} to {b:,}") + f": {process_phrase(p)}"
                     for a, b, p in runs)


def _build_note(make_now, tool_champion, q_star, q_lo, q_hi,
                make_unit_lo, tool_unit_hi, recommendation) -> str:
    head = (f"Cheapest without tooling at {q_lo:,}: {process_phrase(make_now.process)} "
            f"in {make_now.material}, ${make_unit_lo} each.")
    head += f" Cheapest way to make it as drawn, by quantity: {_picks_by_quantity(recommendation)}."

    if tool_champion is not None and q_star is not None and q_star > q_lo:
        tool = process_label(tool_champion.process)
        crossover_clause = (
            f" {tool} becomes cheaper than the cheapest route without tooling at about "
            f"{q_star:,.0f} parts. Batch sizes can move that point; compare the prices at "
            f"your quantity. {tool} is ${tool_unit_hi} each at {q_hi:,}.")
    else:
        crossover_clause = " No tooled process becomes cheaper in this comparison."

    tooling_clause = ""
    if tool_champion is not None and not tool_champion.dfm_ready:
        blocker = tool_champion.dfm_blockers[0] if tool_champion.dfm_blockers else "it lacks draft"
        tooling_clause = (
            f" {process_label(tool_champion.process)} needs a redesign to make the part "
            f"({blocker.rstrip('.')}); its price assumes those changes, not the part as drawn.")

    return head + crossover_clause + tooling_clause
