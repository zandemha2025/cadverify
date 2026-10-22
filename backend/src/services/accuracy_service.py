"""Checked against your real numbers: ScaleCAD's estimate vs the customer's actuals.

For every imported actual that matched a checked part, this compares the
actual machine hours per part and cost per part with what ScaleCAD estimated
for that part, method and quantity on the part's newest record:

* error % = estimate / actual - 1 (the same sign as the ground-truth residual:
  "+7%" means ScaleCAD said 7% more than the job really took);
* whether the actual fell inside the range ScaleCAD stated (hours: the cycle
  time's stated band; cost: the record's confidence range);
* per method and overall: how many parts, the median error (by size) and the
  worst one, and how many actuals fell inside the range.

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


def _interp(qa: float, va: float, qb: float, vb: float, q: float) -> float:
    """Log-log between two priced quantities, as the part page's Other quantity does."""
    t = (math.log(q) - math.log(qa)) / (math.log(qb) - math.log(qa))
    return math.exp(math.log(va) * (1 - t) + math.log(vb) * t)


@dataclass
class EstimateAt:
    hours: Optional[float]
    hours_low: Optional[float]
    hours_high: Optional[float]
    machine_cost: Optional[float]
    cost: Optional[float]
    cost_low: Optional[float]
    cost_high: Optional[float]
    cost_basis: Optional[str]          # exact | between | None
    cost_note: Optional[str]
    priced: list[int]
    calibrated: bool
    material: Optional[str]


def estimate_at(result_json: dict, process: str, quantity: int) -> Optional[EstimateAt]:
    """ScaleCAD's estimate for ``process`` at ``quantity`` on one record, or None if not priced.

    Hours per part come from the estimate at that quantity, else the nearest
    priced quantity (machine time per part doesn't depend on the order size).
    Cost per part depends on it: exact when that quantity was priced, between
    two priced quantities when it falls inside them, and not compared outside.
    """
    ests = [e for e in (result_json or {}).get("estimates") or [] if e.get("process") == process]
    views = sorted((raw_view(e) for e in ests if isinstance(e.get("quantity"), (int, float))),
                   key=lambda v: v["quantity"])
    if not views:
        return None
    q = max(1, int(quantity))
    exact = next((v for v in views if v["quantity"] == q), None)
    near = exact or min(views, key=lambda v: abs(math.log(max(1, v["quantity"])) - math.log(q)))
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
        lo = [v for v in views if v["quantity"] < q and (v["cost"] or 0) > 0]
        hi = [v for v in views if v["quantity"] > q and (v["cost"] or 0) > 0]
        if lo and hi:
            a, b = lo[-1], hi[0]
            cost = _interp(a["quantity"], a["cost"], b["quantity"], b["cost"], q)
            if a["cost_low"] and b["cost_low"] and a["cost_high"] and b["cost_high"]:
                c_lo = _interp(a["quantity"], a["cost_low"], b["quantity"], b["cost_low"], q)
                c_hi = _interp(a["quantity"], a["cost_high"], b["quantity"], b["cost_high"], q)
            basis = "between"
            note = f"between the {int(a['quantity']):,} and {int(b['quantity']):,} prices"
        else:
            note = f"ScaleCAD priced {priced[0]:,} to {priced[-1]:,}; this order was {q:,}"
    return EstimateAt(hours=hours, hours_low=h_lo, hours_high=h_hi, machine_cost=near["machine_cost"],
                      cost=cost, cost_low=c_lo, cost_high=c_hi, cost_basis=basis, cost_note=note,
                      priced=priced, calibrated=near["calibrated"], material=near["material"])


def _metric(actual: Optional[float], est: Optional[float], low: Optional[float], high: Optional[float]) -> Optional[dict]:
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
    }


def compare(actual: dict, record: Optional[dict]) -> dict:
    """One actual against its part's newest record. ``actual`` is a ground-truth public row
    (plus ``part_key``); ``record`` is ``{id, filename, label, created_at, result_json}``."""
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
    }
    if record is None:
        base["note"] = "The part this actual matched is no longer in ScaleCAD"
        return base
    est = estimate_at(record.get("result_json") or {}, actual.get("process"), int(actual.get("quantity") or 1))
    if est is None:
        base["note"] = "ScaleCAD didn't price this method for this part"
        return base
    base["calibrated_record"] = est.calibrated
    base["hours"] = _metric(_num(actual.get("actual_machine_hours")), est.hours, est.hours_low, est.hours_high)
    cost = _metric(_num(actual.get("actual_unit_cost_usd")), est.cost, est.cost_low, est.cost_high)
    if cost is not None:
        cost["basis"] = est.cost_basis
    base["cost"] = cost
    base["machine_cost_each"] = est.machine_cost
    notes = []
    if _num(actual.get("actual_unit_cost_usd")) and cost is None and est.cost_note:
        notes.append(f"Cost not compared: {est.cost_note}")
    if _num(actual.get("actual_machine_hours")) and base["hours"] is None:
        notes.append("Hours not compared: ScaleCAD has no machine time for this method")
    if cost is not None and est.cost_basis == "between":
        notes.append(f"Cost estimate {est.cost_note}")
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
    """Overall and per method, for hours and for cost. Test rows never count."""
    real = [r for r in rows if not r.get("test")]
    procs = sorted({r.get("process") for r in real if r.get("process")})
    per = []
    for p in procs:
        sel = [r for r in real if r.get("process") == p]
        h, c = _stats(sel, "hours"), _stats(sel, "cost")
        h["enough"] = h["n"] >= MIN_PER_METHOD
        c["enough"] = c["n"] >= MIN_PER_METHOD
        per.append({"process": p, "hours": h, "cost": c})
    compared = [r for r in real if r.get("hours") or r.get("cost")]
    return {
        "parts": len({r.get("part_key") for r in compared}),
        "actuals": len(real),
        "compared": len(compared),
        "not_compared": len(real) - len(compared),
        "test": len(rows) - len(real),
        "min_parts": MIN_PARTS,
        "min_per_method": MIN_PER_METHOD,
        "enough": len({r.get("part_key") for r in compared}) >= MIN_PARTS,
        "hours": _stats(real, "hours"),
        "cost": _stats(real, "cost"),
        "per_process": per,
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
    each would do to the error, held out part by part. Real rows only."""
    real = [r for r in rows if not r.get("test")]
    total_parts = len({r.get("part_key") for r in real if r.get("hours") or r.get("cost")})
    allowed = total_parts >= MIN_PARTS
    out = []
    for p in sorted({r.get("process") for r in real if r.get("process")}):
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
    return {"parts": total_parts, "min_parts": MIN_PARTS, "min_per_method": MIN_PER_METHOD,
            "enough": allowed, "processes": out}


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
    """Newest record per part (file hash) in the org, optionally only for ``keys``."""
    from src.db.models import CostDecision

    stmt = (
        select(CostDecision.mesh_hash, CostDecision.ulid, CostDecision.filename, CostDecision.label,
               CostDecision.created_at, CostDecision.result_json)
        .where(CostDecision.org_id == org_id)
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
    return [compare(a, records.get(a["evidence_sha256"])) for a in actuals]


async def accuracy(session: AsyncSession, org_id: str, scope: Scope) -> dict:
    rows = await comparisons(session, org_id, scope)
    # The proposal is always fitted on ALL of the org's actuals, whatever the scope shows.
    return {"rows": rows, "summary": summarize(rows)}
