"""Checked against your real numbers: ScaleCAD's estimate vs the customer's actuals.

For every imported actual that matched a checked part, this compares the
actual machine hours per part and cost per part with what ScaleCAD estimated
for that part, method and quantity on the part's newest record:

* error % = estimate / actual - 1 (the same sign as the ground-truth residual:
  "+7%" means ScaleCAD said 7% more than the job really took); each row carries
  the arithmetic on the numbers it shows (``shown``), so a reader can redo it;
* the cost at the actual's own quantity: the record's price when that quantity
  was priced, else the record's own quantity model (``quantity_model``: what the
  order pays once over the quantity, plus what each part adds, with the same
  learning), never a line drawn between two priced quantities (ce-15). A record
  without the model isn't compared at an unpriced quantity, and says so;
* the rate card: a record priced at an older card than the org's published one
  (``rate_card_basis``) isn't graded on cost; the row says which cards, so v0
  and v1 prices never mix in one median (ce-11);
* the setup, labor and inspection hours entered with an actual, next to the
  hours each line of the record states (ce-11);
* whether the actual fell inside the range ScaleCAD stated (hours: the cycle
  time's stated band; cost: the record's confidence range);
* per method and overall: how many parts, the median error (by size) and the
  worst one, and how many actuals fell inside the range.

Who made the part decides what an actual is compared with (op-18). What it
cost the org to make (``source_type`` actual / pilot: a job's hours and cost)
is compared with ScaleCAD's estimate for that method, as above (``kind:
"made"``). What the org paid a supplier (invoice, a supplier quote: ``kind:
"bought"``) is compared with ScaleCAD's buy price: the record's outside side
at exactly that quantity (the cheapest outside route, your own process at a
job shop included), never with the cost of making it on your machine, and its
hours are never compared. Each row says what it was compared with
(``compared_with``); the summary's figures cover made rows, and bought rows
have their own block (``bought``). A calibration is fitted on made rows only.

The comparison always uses ScaleCAD's own estimate. When a calibration was
applied to a record, the estimate it is compared with is the one from before the
calibration (kept on the record), so the figures never grade a calibration on
the numbers it was fitted to. What the calibration does is measured separately,
held out part by part (``proposal``).

Honest thresholds: fewer than ``MIN_PARTS`` parts with actuals is "not enough to
say"; a method needs ``MIN_PER_METHOD`` actuals before ScaleCAD states its
accuracy for that method or proposes a change to it. Stand-in (test) rows are
shown, labelled, and never count.

Pure functions take plain dicts; the async loaders are org-scoped.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.costing.groundtruth import MIN_RESIDUALS
from src.services.groundtruth_service import MIN_REAL_RECORDS

MIN_PARTS = MIN_REAL_RECORDS          # 8 parts give a fair picture
MIN_PER_METHOD = MIN_RESIDUALS        # 3 actuals per method before a per-method claim
# A factor this close to 1 changes nothing worth applying.
NO_CHANGE = 0.03
# Factors outside this range say the data doesn't line up (hours for the whole
# order in a per-part column, minutes read as hours), not that the shop is 5x faster.
FACTOR_RANGE = (0.25, 4.0)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _driver(est: dict, name: str) -> Optional[dict]:
    for d in est.get("drivers") or []:
        if d.get("name") == name:
            return d
    return None


def raw_view(est: dict) -> dict:
    """The engine's own numbers for one estimate, before any calibration overlay."""
    before = (est.get("calibration") or {}).get("before") or {}
    cycle = _driver(est, "cycle_time")
    machine = _driver(est, "machine_cost")
    conf = est.get("confidence") or {}
    hours = _num(before.get("cycle_time_hr")) if "cycle_time_hr" in before else _num((cycle or {}).get("value"))
    band = _num((cycle or {}).get("error_band_pct"))
    if band is None:
        band = _num(est.get("est_error_band_pct"))
    return {
        "quantity": est.get("quantity"),
        "hours": hours,
        "hours_band_pct": band,
        "machine_cost": _num(before.get("machine_cost_usd")) if "machine_cost_usd" in before else _num((machine or {}).get("value")),
        "cost": _num(before.get("unit_cost_usd")) if "unit_cost_usd" in before else _num(est.get("unit_cost_usd")),
        "cost_low": _num(before.get("low_usd")) if "low_usd" in before else _num(conf.get("low_usd")),
        "cost_high": _num(before.get("high_usd")) if "high_usd" in before else _num(conf.get("high_usd")),
        "calibrated": bool(est.get("calibration")),
        "material": est.get("material"),
    }


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _pct(x: float) -> str:
    return f"{'−' if x < 0 else '+'}{abs(x):.1f}%"


def shown(est: float, actual: float, unit: str) -> dict:
    """What a row prints and its arithmetic on exactly those printed numbers (ce-12):
    cost in cents, hours in minutes to 2 decimals (hours from 2 h up, in hours to
    2 decimals). The % is computed from the printed numbers, so a calculator
    gives the same."""
    if unit == "usd":
        e, a = round(est, 2), round(actual, 2)
        fe, fa = _money(e), _money(a)
    else:
        big = max(est, actual) >= 2.0
        k = 1.0 if big else 60.0
        e, a = round(est * k, 2), round(actual * k, 2)
        u = "h" if big else "min"
        fe, fa = f"{e:,.2f} {u}", f"{a:,.2f} {u}"
    err = (e / a - 1.0) * 100.0 if a > 0 else None
    return {
        "estimate": fe,
        "actual": fa,
        "error": _pct(err) if err is not None else None,
        "formula": f"{fe} ÷ {fa} − 1 = {_pct(err)}" if err is not None else None,
    }


_NUM = r"(\d+(?:\.\d+)?)"


def stated_hours(est: dict) -> dict:
    """The hours each labor line of a record states, read off its own arithmetic:
    setup for the order, programming for the order, labor (post-process) a part
    with its learning, inspection a part. A line that doesn't state them is left out."""
    import re

    out: dict = {}
    by = {d.get("name"): str(d.get("source") or "") for d in est.get("drivers") or [] if isinstance(d, dict)}
    src = by.get("setup_cost", "")
    m = re.search(rf"setup {_NUM}\s?hr .*?= {_NUM} plates", src)
    if m:
        out["setup_order"] = float(m.group(1)) * float(m.group(2))
    else:
        m = re.search(rf"setup {_NUM}\s?hr\b", src)
        if m:
            out["setup_order"] = float(m.group(1))
    m = re.search(rf"NRE {_NUM}\s?hr\b", by.get("nre_cost", ""))
    if m:
        out["programming_order"] = float(m.group(1))
    src = by.get("labor_cost", "")
    m = re.search(rf"≈ {_NUM}\s?hr\b", src) or re.search(rf"post-process {_NUM}\s?hr\b", src)
    if m:
        h = float(m.group(1))
        lm = re.search(rf"× {_NUM} learning", src)
        out["labor_part"] = h * (float(lm.group(1)) if lm else 1.0)
    m = re.search(rf"= {_NUM}\s?hr × \$", by.get("inspection_cost", ""))
    if m:
        out["inspection_part"] = float(m.group(1))
    return out


@dataclass
class EstimateAt:
    hours: Optional[float]
    hours_low: Optional[float]
    hours_high: Optional[float]
    machine_cost: Optional[float]
    cost: Optional[float]
    cost_low: Optional[float]
    cost_high: Optional[float]
    cost_basis: Optional[str]          # exact | model | None
    cost_note: Optional[str]
    priced: list[int]
    calibrated: bool
    material: Optional[str]
    hours_stated: dict = field(default_factory=dict)   # stated_hours of the estimate used


def estimate_at(result_json: dict, process: Optional[str], quantity: int) -> Optional[EstimateAt]:
    """ScaleCAD's estimate for ``process`` at ``quantity`` on one record, or None if not priced.

    Hours per part come from the estimate at that quantity, else the nearest
    priced quantity (machine time per part doesn't depend on the order size).
    Cost per part depends on it: exact when that quantity was priced, else the
    record's own quantity model at that quantity (``quantity_model.model_at``,
    before any calibration, like every number here). A record without the model
    isn't compared at an unpriced quantity.
    """
    from src.costing import quantity_model

    ests = [e for e in (result_json or {}).get("estimates") or [] if e.get("process") == process
            and isinstance(e.get("quantity"), (int, float))]
    pairs = sorted(((raw_view(e), e) for e in ests), key=lambda p: p[0]["quantity"])
    views = [v for v, _ in pairs]
    if not views:
        return None
    q = max(1, int(quantity))
    exact = next((v for v in views if v["quantity"] == q), None)
    near = exact or min(views, key=lambda v: abs(math.log(max(1, v["quantity"])) - math.log(q)))
    near_est = next(e for v, e in pairs if v is near)
    hours = near["hours"]
    band = near["hours_band_pct"]
    h_lo = hours * (1 - band / 100.0) if hours is not None and band is not None else None
    h_hi = hours * (1 + band / 100.0) if hours is not None and band is not None else None

    cost = c_lo = c_hi = None
    basis = None
    note = None
    priced = [int(v["quantity"]) for v in views]
    if exact and exact["cost"] and exact["cost"] > 0:
        cost, c_lo, c_hi, basis = exact["cost"], exact["cost_low"], exact["cost_high"], "exact"
    else:
        model = near_est.get("qty_model")
        unit = quantity_model.unit_cost_at({"qty_model": model}, q) if isinstance(model, dict) else None
        if unit is not None and unit > 0:
            cost, basis = unit, "model"
            once, per = quantity_model.fixed_and_variable(model, q)
            note = (f"ScaleCAD's model at {q:,}: {_money(once)} once ÷ {q:,} + {_money(per)} a part "
                    f"= {_money(unit)} (this record priced {', '.join(f'{p:,}' for p in priced)})")
            # The stated range keeps its width: the band of the nearest priced quantity.
            if near["cost"] and near["cost_low"] and near["cost_high"]:
                c_lo = unit * near["cost_low"] / near["cost"]
                c_hi = unit * near["cost_high"] / near["cost"]
        else:
            note = (f"ScaleCAD priced {', '.join(f'{p:,}' for p in priced)}; this order was {q:,}. "
                    f"Price {q:,} on the part to compare it")
    return EstimateAt(hours=hours, hours_low=h_lo, hours_high=h_hi, machine_cost=near["machine_cost"],
                      cost=cost, cost_low=c_lo, cost_high=c_hi, cost_basis=basis, cost_note=note,
                      priced=priced, calibrated=near["calibrated"], material=near["material"],
                      hours_stated=stated_hours(exact and next(e for v, e in pairs if v is exact) or near_est))


def _metric(actual: Optional[float], est: Optional[float], low: Optional[float], high: Optional[float],
            unit: str = "usd") -> Optional[dict]:
    if actual is None or est is None or actual <= 0 or est <= 0:
        return None
    err = est / actual - 1.0
    inside = None if low is None or high is None else bool(low <= actual <= high)
    return {
        "actual": round(actual, 6),
        "estimate": round(est, 6),
        "low": round(low, 6) if low is not None else None,
        "high": round(high, 6) if high is not None else None,
        "error_pct": round(err * 100.0, 2),
        "inside": inside,
        "shown": shown(est, actual, unit),
    }


# The hours an actual can carry beyond machine time, against the line that states them.
HOUR_LINES = (
    ("setup", "actual_setup_hours", "setup_order", "Setup, for the order"),
    ("labor", "actual_labor_hours", "labor_part", "Labor a part"),
    ("inspection", "actual_inspection_hours", "inspection_part", "Inspection a part"),
)


def hour_lines(actual: dict, stated: dict) -> list[dict]:
    """Each of setup, labor and inspection hours the actual carries, next to the
    record's stated hours for that line (or why not compared)."""
    out = []
    for key, field_name, stated_key, label in HOUR_LINES:
        a = _num(actual.get(field_name))
        if a is None:
            continue
        e = stated.get(stated_key)
        row = {"line": key, "label": label, "actual": a, "estimate": e}
        m = _metric(a, e, None, None, unit="hours") if e is not None else None
        if m is not None:
            row.update({"error_pct": m["error_pct"], "shown": m["shown"]})
        else:
            row["note"] = ("ScaleCAD has no hours on this line for this method" if e is None
                           else "Not compared: zero hours")
        out.append(row)
    return out


def compare(actual: dict, record: Optional[dict], rates: Optional[dict] = None) -> dict:
    """One actual against its part's newest record. ``actual`` is a ground-truth public row
    (plus ``part_key``); ``record`` is ``{id, filename, label, created_at, result_json}``;
    ``rates`` is the record's ``rate_card_basis.basis`` (which card priced it, which is in
    effect), None when unknown."""
    base = {
        "id": actual.get("id"),
        "part_key": actual.get("evidence_sha256"),
        "file_name": (record or {}).get("filename") or actual.get("part_id"),
        "part_number": actual.get("part_number"),
        "record_id": (record or {}).get("id"),
        "process": actual.get("process"),
        "quantity": actual.get("quantity"),
        "machine": actual.get("machine"),
        "date": actual.get("invoice_date"),
        "reference": actual.get("source"),
        "test": bool(actual.get("stand_in")),
        "hours": None,
        "cost": None,
        "note": None,
        "calibrated_record": False,
        "rates": rates,
        "hour_lines": [],
        "kind": actual_kind(actual),
        "compared_with": None,
    }
    if record is None:
        base["note"] = "The part this actual matched is no longer in ScaleCAD"
        return base
    if base["kind"] == "bought":
        return _compare_bought(actual, record, rates, base)
    est = estimate_at(record.get("result_json") or {}, actual.get("process"), int(actual.get("quantity") or 1))
    if est is None:
        base["note"] = "ScaleCAD didn't price this method for this part"
        return base
    base["calibrated_record"] = est.calibrated
    base["compared_with"] = f"ScaleCAD's estimate for {_proc_words(actual.get('process'))}, at {int(actual.get('quantity') or 1):,}"
    base["hours"] = _metric(_num(actual.get("actual_machine_hours")), est.hours, est.hours_low, est.hours_high,
                            unit="hours")
    base["hour_lines"] = hour_lines(actual, est.hours_stated)
    stale_rates = bool(rates and rates.get("out_of_date"))
    cost = None if stale_rates else _metric(_num(actual.get("actual_unit_cost_usd")), est.cost, est.cost_low,
                                            est.cost_high)
    if cost is not None:
        cost["basis"] = est.cost_basis
        if est.cost_basis == "model":
            cost["basis_note"] = est.cost_note
    base["cost"] = cost
    base["machine_cost_each"] = est.machine_cost
    notes = []
    if _num(actual.get("actual_unit_cost_usd")) and stale_rates and rates is not None:  # stale implies rates
        base["rates_excluded"] = True
        notes.append(f"Cost not compared: {rates['text']} Re-check the part to compare at "
                     f"v{rates['current']}")
    elif _num(actual.get("actual_unit_cost_usd")) and cost is None and est.cost_note:
        notes.append(f"Cost not compared: {est.cost_note}")
    if _num(actual.get("actual_machine_hours")) and base["hours"] is None:
        notes.append("Hours not compared: ScaleCAD has no machine time for this method")
    base["note"] = "; ".join(notes) or None
    return base


BOUGHT_SOURCES = frozenset({"invoice", "quote"})


def actual_kind(actual: dict) -> str:
    """``bought`` for what the org paid (or was quoted by) a supplier, else ``made``."""
    return "bought" if str(actual.get("source_type") or "").lower() in BOUGHT_SOURCES else "made"


def _proc_words(process: Optional[str]) -> str:
    from src.services.catalog_service import process_label

    return process_label(process).lower() if process else "this method"


def buy_price_at(result_json: dict, quantity: int) -> Optional[dict]:
    """ScaleCAD's buy price for the part at exactly ``quantity``: the record's outside side there
    (``decision.options``: the cheapest outside route, your own process at a job shop included);
    on a part no machine of yours makes, its cheapest estimate at that quantity. None when that
    quantity wasn't priced (never drawn between two priced quantities)."""
    q = max(1, int(quantity))
    decision = (result_json or {}).get("decision") or {}
    options = decision.get("options") or {}
    opt = options.get(str(q)) if isinstance(options, dict) else None
    side = (opt or {}).get("outside") if isinstance(opt, dict) else None
    if isinstance(side, dict) and _num(side.get("unit_cost_usd")):
        return {"cost": _num(side["unit_cost_usd"]), "low": _num(side.get("low_usd")), "high": _num(side.get("high_usd")),
                "process": side.get("process"), "job_shop": bool(side.get("same_process")), "quantity": q}
    if options:
        return None  # a part one of your machines makes: only its outside side is a buy price
    best = None
    for e in (result_json or {}).get("estimates") or []:
        if not isinstance(e, dict) or e.get("quantity") != q or e.get("dfm_ready") is False or e.get("spec_excluded"):
            continue
        if _driver(e, "owned_in_house") is not None:
            continue
        v = raw_view(e)
        if v["cost"] and (best is None or v["cost"] < best["cost"]):
            best = {"cost": v["cost"], "low": v["cost_low"], "high": v["cost_high"], "process": e.get("process"),
                    "job_shop": False, "quantity": q}
    return best


def _buy_words(b: dict) -> str:
    where = " at a job shop" if b.get("job_shop") else ""
    return f"ScaleCAD's outside price for {_proc_words(b.get('process'))}{where}, at {b['quantity']:,}"


def _compare_bought(actual: dict, record: dict, rates: Optional[dict], base: dict) -> dict:
    """A supplier's invoice (or quote) against ScaleCAD's buy price at the same quantity."""
    q = int(actual.get("quantity") or 1)
    notes = []
    if _num(actual.get("actual_machine_hours")):
        notes.append("Hours not compared: a supplier's invoice says nothing about your machine time")
    buy = buy_price_at(record.get("result_json") or {}, q)
    stale_rates = bool(rates and rates.get("out_of_date"))
    if buy is None:
        base["compared_with"] = None
        notes.append(f"Not compared: ScaleCAD's outside price for this part wasn't priced at {q:,}; "
                     f"price {q:,} on the part to compare it")
    elif stale_rates and rates is not None:  # stale implies rates
        base["compared_with"] = _buy_words(buy)
        base["rates_excluded"] = True
        notes.append(f"Cost not compared: {rates['text']} Re-check the part to compare at v{rates['current']}")
    else:
        base["compared_with"] = _buy_words(buy)
        cost = _metric(_num(actual.get("actual_unit_cost_usd")), buy["cost"], buy["low"], buy["high"])
        if cost is not None:
            cost["basis"] = "buy"
        base["cost"] = cost
    base["note"] = "; ".join(notes) or None
    return base


def _stats(rows: list[dict], metric: str) -> dict:
    vals = [r for r in rows if r.get(metric)]
    errs = [r[metric]["error_pct"] for r in vals]
    parts = {r.get("part_key") for r in vals}
    inside = [r[metric]["inside"] for r in vals if r[metric]["inside"] is not None]
    if not errs:
        return {"n": 0, "parts": 0, "median_abs_pct": None, "median_pct": None, "worst_pct": None,
                "worst": None, "inside": 0, "with_range": 0, "enough": False}
    worst = max(vals, key=lambda r: abs(r[metric]["error_pct"]))
    return {
        "n": len(errs),
        "parts": len(parts),
        "median_abs_pct": round(statistics.median(abs(e) for e in errs), 1),
        "median_pct": round(statistics.median(errs), 1),
        "worst_pct": round(worst[metric]["error_pct"], 1),
        "worst": {"file_name": worst.get("file_name"), "part_key": worst.get("part_key"),
                  "part_number": worst.get("part_number"), "process": worst.get("process")},
        "inside": sum(1 for x in inside if x),
        "with_range": len(inside),
        "enough": len(parts) >= MIN_PARTS,
    }


def summarize(rows: list[dict]) -> dict:
    """Overall and per method, for hours and for cost. Test rows never count.

    The figures cover what the org made itself against ScaleCAD's estimate
    (``population``); supplier invoices against ScaleCAD's buy price are their
    own block (``bought``), never mixed into the same median.
    """
    everything = [r for r in rows if not r.get("test")]
    bought = [r for r in everything if r.get("kind") == "bought"]
    real = [r for r in everything if r.get("kind") != "bought"]
    procs = sorted({r["process"] for r in real if r.get("process")})
    per = []
    for p in procs:
        sel = [r for r in real if r.get("process") == p]
        h, c = _stats(sel, "hours"), _stats(sel, "cost")
        h["enough"] = h["n"] >= MIN_PER_METHOD
        c["enough"] = c["n"] >= MIN_PER_METHOD
        per.append({"process": p, "hours": h, "cost": c})
    compared = [r for r in real if r.get("hours") or r.get("cost")]
    excluded = [r for r in real if r.get("rates_excluded")]
    cards = sorted({r["rates"].get("priced") for r in real if r.get("cost") and r.get("rates")} - {None})
    bought_compared = [r for r in bought if r.get("cost")]
    bought_parts = len({r.get("part_key") for r in bought_compared})
    return {
        "population": "Your own job costs and hours against ScaleCAD's estimate for the same part, method and quantity",
        "parts": len({r.get("part_key") for r in compared}),
        "actuals": len(real),
        "compared": len(compared),
        "not_compared": len(real) - len(compared),
        "test": len(rows) - len(everything),
        "bought": {
            "population": "What you paid suppliers against ScaleCAD's outside price at the same quantity",
            "actuals": len(bought),
            "compared": len(bought_compared),
            "not_compared": len(bought) - len(bought_compared),
            "parts": bought_parts,
            "enough": bought_parts >= MIN_PARTS,
            "cost": _stats(bought, "cost"),
        },
        "min_parts": MIN_PARTS,
        "min_per_method": MIN_PER_METHOD,
        "enough": len({r.get("part_key") for r in compared}) >= MIN_PARTS,
        "hours": _stats(real, "hours"),
        "cost": _stats(real, "cost"),
        "per_process": per,
        # Cost rows left out because their record predates the org's published rates (ce-11),
        # and the rate cards the compared costs were priced at (one, unless a record is unknown).
        "rates_excluded": len(excluded),
        "rates_priced": cards,
    }


# ---------------------------------------------------------------------------
# What a calibration would change (fitted on the org's own actuals)
# ---------------------------------------------------------------------------


def _loo(items: list[tuple[str, float, float]]) -> tuple[Optional[float], Optional[float], list[float]]:
    """(median |error| before, after, after-errors) with each part held out.

    ``items``: (part_key, estimate, actual). The factor that corrects a part's
    estimate is the median actual/estimate over the OTHER parts, so a part never
    grades the factor fitted on itself.
    """
    if len(items) < 2:
        return None, None, []
    before = [abs(e / a - 1) for _, e, a in items]
    after = []
    for key, e, a in items:
        others = [aa / ee for k, ee, aa in items if k != key]
        if not others:
            continue
        f = statistics.median(others)
        after.append(e * f / a - 1)
    if not after:
        return statistics.median(before), None, []
    return statistics.median(before), statistics.median(abs(x) for x in after), after


def _factor_entry(items: list[tuple[str, float, float]], *, allowed: bool) -> dict:
    n = len(items)
    parts = len({k for k, _, _ in items})
    if n == 0:
        return {"n": 0, "parts": 0, "factor": None, "offer": False, "why": "none"}
    ratios = [a / e for _, e, a in items]
    f = statistics.median(ratios)
    before, after, _ = _loo(items)
    out = {
        "n": n,
        "parts": parts,
        "factor": round(f, 4),
        "before_pct": round(before * 100, 1) if before is not None else None,
        "after_pct": round(after * 100, 1) if after is not None else None,
        "offer": False,
        "why": None,
    }
    if n < MIN_PER_METHOD or parts < MIN_PER_METHOD:
        out["why"] = "few"
    elif not (FACTOR_RANGE[0] <= f <= FACTOR_RANGE[1]):
        out["why"] = "out_of_range"
    elif abs(f - 1) < NO_CHANGE:
        out["why"] = "no_change"
    elif after is None or before is None or after >= before:
        out["why"] = "no_better"
    elif not allowed:
        out["why"] = "org_few"
    else:
        out["offer"] = True
        out["why"] = "offer"
    return out


def proposal(rows: list[dict]) -> dict:
    """Per method: the hours and cost factors the org's actuals support, and what
    each would do to the error, held out part by part. Real rows the org made
    itself only: a supplier's invoice never calibrates your machines (op-18)."""
    real = [r for r in rows if not r.get("test") and r.get("kind") != "bought"]
    total_parts = len({r.get("part_key") for r in real if r.get("hours") or r.get("cost")})
    allowed = total_parts >= MIN_PARTS
    out = []
    for p in sorted({r["process"] for r in real if r.get("process")}):
        sel = [r for r in real if r.get("process") == p]
        h_items = [(r["part_key"], r["hours"]["estimate"], r["hours"]["actual"]) for r in sel if r.get("hours")]
        hours = _factor_entry(h_items, allowed=allowed)
        h = hours["factor"] if hours["offer"] else None
        c_items = []
        for r in sel:
            if not r.get("cost"):
                continue
            est = r["cost"]["estimate"]
            mc = _num(r.get("machine_cost_each"))
            if h is not None and mc is not None:
                est = est + mc * (h - 1.0)
            if est > 0:
                c_items.append((r["part_key"], est, r["cost"]["actual"]))
        cost = _factor_entry(c_items, allowed=allowed)
        cost["after_hours"] = h is not None
        out.append({"process": p, "hours": hours, "cost": cost})
    # Supplier invoices left out of the calibration, so the panel can say why they don't count.
    bought = sum(1 for r in rows if not r.get("test") and r.get("kind") == "bought")
    return {"parts": total_parts, "min_parts": MIN_PARTS, "min_per_method": MIN_PER_METHOD,
            "enough": allowed, "processes": out, "bought_excluded": bought}


# ---------------------------------------------------------------------------
# Loading (org-scoped)
# ---------------------------------------------------------------------------


@dataclass
class Scope:
    """Which parts a comparison covers: all of the org's, one part, or one catalog run's."""

    part_key: Optional[str] = None
    run_id: Optional[str] = None
    keys: Optional[set[str]] = field(default=None)


async def latest_records(session: AsyncSession, org_id: str, keys: Optional[Iterable[str]] = None) -> dict[str, dict]:
    """Newest record per part (file hash) in the org, optionally only for ``keys``.

    A what-if re-cost is never the part's price, so an actual is never graded against one (ce-17)."""
    from src.db.models import CostDecision
    from src.services.cost_decision_service import current_price_clause

    stmt = (
        select(CostDecision.mesh_hash, CostDecision.ulid, CostDecision.filename, CostDecision.label,
               CostDecision.created_at, CostDecision.result_json)
        .where(CostDecision.org_id == org_id, current_price_clause())
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.created_at.desc(), CostDecision.id.desc())
    )
    if keys is not None:
        keys = list(keys)
        if not keys:
            return {}
        stmt = stmt.where(CostDecision.mesh_hash.in_(keys))
    out = {}
    for mesh_hash, ulid, filename, label, created_at, result in (await session.execute(stmt)).all():
        out[mesh_hash] = {"id": ulid, "filename": filename, "label": label,
                          "created_at": created_at.isoformat() if created_at else None,
                          "result_json": result or {}}
    return out


async def run_part_keys(session: AsyncSession, org_id: str, run_id: str) -> Optional[set[str]]:
    """The parts (file hashes) a catalog run or batch checked; None if the run isn't the org's."""
    from src.db.models import Batch, BatchItem, CostDecision

    batch = (await session.execute(
        select(Batch.id).where(Batch.ulid == run_id, Batch.org_id == org_id)
    )).scalar_one_or_none()
    if batch is None:
        return None
    rows = (await session.execute(
        select(CostDecision.mesh_hash)
        .join(BatchItem, BatchItem.cost_decision_id == CostDecision.id)
        .where(BatchItem.batch_id == batch, CostDecision.org_id == org_id)
    )).scalars().all()
    return set(rows)


async def comparisons(session: AsyncSession, org_id: str, scope: Scope) -> list[dict]:
    """Every matched actual in scope, compared with its part's newest record."""
    from src.db.models import GroundTruthRecordRow
    from src.services.groundtruth_service import row_to_public

    stmt = select(GroundTruthRecordRow).where(
        GroundTruthRecordRow.org_id == org_id,
        GroundTruthRecordRow.evidence_sha256.isnot(None),
    )
    keys: Optional[set[str]] = None
    if scope.part_key:
        keys = {scope.part_key}
    elif scope.keys is not None:
        keys = set(scope.keys)
    if keys is not None:
        if not keys:
            return []
        stmt = stmt.where(GroundTruthRecordRow.evidence_sha256.in_(sorted(keys)))
    rows = (await session.execute(stmt.order_by(GroundTruthRecordRow.created_at.desc(),
                                                GroundTruthRecordRow.id.desc()))).scalars().all()
    actuals = [row_to_public(r) for r in rows]
    records = await latest_records(session, org_id, {a["evidence_sha256"] for a in actuals})
    from datetime import datetime as _dt

    from src.services import rate_card_basis
    from src.services.rate_library_service import rate_library_enabled

    card_rows = await rate_card_basis.org_rate_rows(session, org_id) if records else []
    enabled = rate_library_enabled()

    def _rates(rec: Optional[dict]) -> Optional[dict]:
        if rec is None:
            return None
        made = _dt.fromisoformat(rec["created_at"]) if rec.get("created_at") else None
        return rate_card_basis.basis(rec.get("result_json") or {}, made, card_rows, enabled=enabled)

    return [compare(a, records.get(a["evidence_sha256"]), _rates(records.get(a["evidence_sha256"])))
            for a in actuals]


async def accuracy(session: AsyncSession, org_id: str, scope: Scope) -> dict:
    rows = await comparisons(session, org_id, scope)
    # The proposal is always fitted on ALL of the org's actuals, whatever the scope shows.
    return {"rows": rows, "summary": summarize(rows)}
