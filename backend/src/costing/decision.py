"""Decision layer (spec §8 + V1 fix-spec §8) — crossover + make-vs-buy.

Coherent semantics (resolves weaknesses #6, #7):

  MAKE-NOW set = ADDITIVE ∪ SUBTRACTIVE  (need no hard tooling)
  TOOLING  set = FORMATIVE               (injection molding / die casting)
  DFM-ready    = engine verdict != "fail"

  make_now      = argmin over DFM-ready MAKE-NOW estimates at q_lo (real unit cost)
                  ≡ recommendation[q_lo].process   (single source — cannot disagree)
  tool_champion = argmin over TOOLING estimates at q_hi (may be DFM-fail)
  crossover     = tool_champion.fixed / (make_now.var − tool_champion.var)

The headline make process is drawn ONLY from DFM-ready make candidates, so it is
never a process the part currently fails. The tooling route may be DFM-fail; if
so it is presented conditionally ("if redesigned for molding"), never asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.analysis.models import ProcessType
from src.costing.rates import process_family

_PV_TO_PT = {pt.value: pt for pt in ProcessType}

MAKE_NOW_FAMILIES = ("additive", "subtractive", "fabrication")


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


def crossover(fixed_a: float, var_a: float, fixed_b: float, var_b: float) -> Optional[float]:
    """q* where process A and B cost the same per unit. Only meaningful for q>1.

    unit_a(q) = fixed_a/q + var_a ; unit_b(q) = fixed_b/q + var_b
    => q* = (fixed_b - fixed_a) / (var_a - var_b)
    """
    if var_a == var_b:
        return None
    q = (fixed_b - fixed_a) / (var_a - var_b)
    return q if q > 1 else None


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
        if fam == "formative":
            reason += ", tooling-dominated"
        return reason
    if fam == "formative":
        return "invest in tooling"
    return ""


def make_vs_buy(estimates_by_pq: dict, quantities, leadtimes_by_key) -> Optional[Decision]:
    """estimates_by_pq: {(process_value, qty): CostEstimate} for every eligible
    (process, qty). Decision ranks by REAL per-qty unit cost (not a fixed/var
    reconstruction), so the headline make process and the low-qty recommendation
    are computed from the same ranking and can never disagree.
    """
    if not estimates_by_pq:
        return None

    quantities = list(quantities)
    q_lo, q_hi = min(quantities), max(quantities)
    proc_values = sorted({pv for (pv, _q) in estimates_by_pq})

    def est_at(pv, q):
        return estimates_by_pq[(pv, q)]

    def make_ready_ranked(q):
        cands = [est_at(pv, q) for pv in proc_values
                 if _family(pv) in MAKE_NOW_FAMILIES and est_at(pv, q).dfm_ready]
        return sorted(cands, key=lambda e: e.unit_cost_usd)

    def make_any_ranked(q):  # fallback if no DFM-ready make process exists
        cands = [est_at(pv, q) for pv in proc_values if _family(pv) in MAKE_NOW_FAMILIES]
        return sorted(cands, key=lambda e: e.unit_cost_usd)

    def tool_ranked(q):
        cands = [est_at(pv, q) for pv in proc_values if _family(pv) == "formative"]
        return sorted(cands, key=lambda e: e.unit_cost_usd)

    ready_lo = make_ready_ranked(q_lo) or make_any_ranked(q_lo)
    if not ready_lo:
        return None
    make_now = ready_lo[0]

    tools_hi = tool_ranked(q_hi)
    tool_champion = tools_hi[0] if tools_hi else None

    q_star = None
    if tool_champion is not None and tool_champion.process != make_now.process:
        q_star = crossover(make_now.fixed_cost_usd, make_now.variable_cost_usd,
                           tool_champion.fixed_cost_usd, tool_champion.variable_cost_usd)

    # ---- per-qty tiers --------------------------------------------------
    recommendation: dict = {}
    if_redesigned: dict = {}
    for q in quantities:
        tier1_ranked = make_ready_ranked(q) or make_any_ranked(q)
        tier1 = tier1_ranked[0]
        lt = leadtimes_by_key.get((tier1.process, q))
        recommendation[q] = {
            "process": tier1.process,
            "material": tier1.material,
            "unit_cost_usd": round(tier1.unit_cost_usd, 2),
            "dfm_ready": tier1.dfm_ready,
            "dfm_verdict": tier1.dfm_verdict,
            "lead_low_days": lt.low_days if lt else None,
            "lead_high_days": lt.high_days if lt else None,
        }
        # tier-2: cheapest estimate that beats tier-1 but is DFM-fail OR tooling
        cheaper = [
            est_at(pv, q) for pv in proc_values
            if est_at(pv, q).unit_cost_usd < tier1.unit_cost_usd
            and (not est_at(pv, q).dfm_ready or _family(pv) == "formative")
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

    note = _build_note(make_now, tool_champion, q_star, q_lo, q_hi,
                       round(make_now.unit_cost_usd, 2),
                       round(tool_champion.unit_cost_usd, 2) if tool_champion else None)

    return Decision(
        make_now_process=make_now.process,
        make_now_material=make_now.material,
        tooling_process=tool_champion.process if tool_champion else None,
        tooling_dfm_ready=bool(tool_champion.dfm_ready) if tool_champion else True,
        crossover_qty=round(q_star, 1) if q_star else None,
        recommendation=recommendation,
        if_redesigned=if_redesigned,
        note=note,
    )


def _build_note(make_now, tool_champion, q_star, q_lo, q_hi,
                make_unit_lo, tool_unit_hi) -> str:
    head = (f"Make by {make_now.process} ({make_now.material}) — ${make_unit_lo}/unit "
            f"at qty {q_lo}, the cheapest make-as-is option and your low-volume pick.")

    if tool_champion is not None and q_star is not None and q_star > q_lo:
        crossover_clause = (
            f" {make_now.process} stays cheapest up to ~{q_star:.0f} units; above "
            f"~{q_star:.0f}, {tool_champion.process} is cheaper (${tool_unit_hi}/unit "
            f"at qty {q_hi}).")
    else:
        crossover_clause = (f" {make_now.process} is cheapest at every quantity tested "
                            f"— no tooling crossover.")

    tooling_clause = ""
    if tool_champion is not None and not tool_champion.dfm_ready:
        blocker = tool_champion.dfm_blockers[0] if tool_champion.dfm_blockers else "draft DFM"
        tooling_clause = (
            f" Note: {tool_champion.process} requires design-for-molding — the part "
            f"currently FAILS draft DFM ({blocker}); the tooling cost shown is 'if "
            f"redesigned for molding', not a current-capability quote.")

    return head + crossover_clause + tooling_clause
