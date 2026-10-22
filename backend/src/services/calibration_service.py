"""Calibration with the organization's own actuals: apply, undo, and the overlay
that applies it to future estimates.

A calibration is a per-method pair of factors fitted on the org's matched
actuals (``accuracy_service.proposal``): machine hours for that method are
multiplied by ``hours`` and the cost per part by ``cost``. Applying one records
who applied it and when (``org_calibrations``); Undo marks the newest one undone
(who and when) and the one before it, if any, is in effect again.

The overlay (``apply_org_calibration``) runs on a fresh estimate right after the
engine serializes it, in the live check and in batch / catalog runs:

* the cycle time and the machine line scale by the hours factor (the cost per
  part moves by the machine line's change);
* a "Your actuals" line carries the cost factor's change, so the lines still add
  up to the cost per part;
* the range moves with the cost per part, and the decision's per-quantity costs
  for that method move with it;
* the engine's own numbers are kept on the estimate (``calibration.before``), so
  accuracy is always measured against them and never against the calibration
  fitted on the same actuals.

No calibration applied => the estimate is returned unchanged (same object).
Org-scoped: the overlay only ever reads the caller org's calibration.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import OrgCalibration

logger = logging.getLogger("cadverify.calibration")

CAL_DRIVER = "your_actuals_cost"


async def active_calibration(session: AsyncSession, org_id: str) -> Optional[OrgCalibration]:
    """The calibration in effect for the org: its newest applied one, else None."""
    return (await session.execute(
        select(OrgCalibration)
        .where(OrgCalibration.org_id == org_id, OrgCalibration.status == "applied")
        .order_by(OrgCalibration.applied_at.desc(), OrgCalibration.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def history(session: AsyncSession, org_id: str, limit: int = 20) -> list[OrgCalibration]:
    return list((await session.execute(
        select(OrgCalibration)
        .where(OrgCalibration.org_id == org_id)
        .order_by(OrgCalibration.applied_at.desc(), OrgCalibration.id.desc())
        .limit(limit)
    )).scalars().all())


async def _emails(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    from src.db.models import User

    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.email).where(User.id.in_(ids)))).all()
    return {i: e for i, e in rows}


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


async def public_history(session: AsyncSession, org_id: str) -> list[dict]:
    rows = await history(session, org_id)
    who = await _emails(session, {r.applied_by for r in rows} | {r.undone_by for r in rows})
    active = next((r for r in rows if r.status == "applied"), None)
    return [
        {
            "id": r.ulid,
            "status": r.status,
            "in_effect": active is not None and r.id == active.id,
            "factors": r.factors or {},
            "basis": r.basis or {},
            "applied_at": _iso(r.applied_at),
            "applied_by": who.get(r.applied_by),
            "undone_at": _iso(r.undone_at),
            "undone_by": who.get(r.undone_by),
        }
        for r in rows
    ]


async def apply(session: AsyncSession, org_id: str, user_id: Optional[int],
                processes: Optional[list[str]] = None) -> OrgCalibration:
    """Apply the factors the org's actuals support now (recomputed here, never
    taken from the request) for ``processes`` (default: every one offered).

    Methods calibrated earlier and not named keep their factors. Raises
    ``ValueError`` when nothing can be applied, with the reason in words.
    """
    from src.services import accuracy_service as acc

    rows = await acc.comparisons(session, org_id, acc.Scope())
    prop = acc.proposal(rows)
    if not prop["enough"]:
        raise ValueError(
            f"{prop['parts']} parts with actuals; {prop['min_parts']} or more are needed before a calibration can be applied."
        )
    offered = {}
    for p in prop["processes"]:
        if processes and p["process"] not in processes:
            continue
        h = p["hours"]["factor"] if p["hours"]["offer"] else None
        c = p["cost"]["factor"] if p["cost"]["offer"] else None
        if h is None and c is None:
            continue
        offered[p["process"]] = {
            "hours": h,
            "cost": c,
            "hours_n": p["hours"]["n"],
            "cost_n": p["cost"]["n"],
            "hours_parts": p["hours"]["parts"],
            "cost_parts": p["cost"]["parts"],
            "hours_before_pct": p["hours"].get("before_pct"),
            "hours_after_pct": p["hours"].get("after_pct"),
            "cost_before_pct": p["cost"].get("before_pct"),
            "cost_after_pct": p["cost"].get("after_pct"),
        }
    if not offered:
        raise ValueError("Nothing to apply: no method has a change that makes ScaleCAD more accurate on your parts.")
    current = await active_calibration(session, org_id)
    factors = dict((current.factors or {}) if current else {})
    # A method whose factors are already in effect isn't applied again.
    offered = {p: f for p, f in offered.items() if not same_factors(factors.get(p), f)}
    if not offered:
        raise ValueError("Nothing new to apply: the calibration in effect already has these changes.")
    factors.update(offered)
    row = OrgCalibration(
        org_id=org_id,
        factors=factors,
        basis={"parts": prop["parts"], "applied_processes": sorted(offered), "previous": current.ulid if current else None},
        status="applied",
        applied_by=user_id,
        applied_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


def same_factors(a: Optional[dict], b: Optional[dict], tol: float = 5e-4) -> bool:
    """True when two per-method factor pairs are the same (hours and cost, None == None)."""
    if not a or not b:
        return False
    for k in ("hours", "cost"):
        x, y = a.get(k), b.get(k)
        if (x is None) != (y is None):
            return False
        if x is not None and abs(float(x) - float(y)) > tol:
            return False
    return True


async def undo(session: AsyncSession, org_id: str, user_id: Optional[int]) -> Optional[OrgCalibration]:
    """Undo the calibration in effect; returns it (now undone), or None if none was applied."""
    current = await active_calibration(session, org_id)
    if current is None:
        return None
    current.status = "undone"
    current.undone_by = user_id
    current.undone_at = datetime.now(timezone.utc)
    await session.flush()
    return current


# ---------------------------------------------------------------------------
# The overlay on a fresh estimate
# ---------------------------------------------------------------------------


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _pct(f: float) -> str:
    d = round((f - 1.0) * 100)
    return f"{'+' if d > 0 else ''}{d}%"


def overlay(result: dict, factors: dict, *, calibration_id: str, applied_at: Optional[str]) -> dict:
    """Apply per-method factors to a serialized decision report. Pure; returns a new dict."""
    if not factors or not isinstance(result, dict) or not result.get("estimates"):
        return result
    out = copy.deepcopy(result)
    ratio_by: dict[tuple[str, object], float] = {}
    for est in out.get("estimates") or []:
        f = factors.get(est.get("process"))
        if not f:
            continue
        h = _num(f.get("hours"))
        c = _num(f.get("cost"))
        if (h is None or h <= 0) and (c is None or c <= 0):
            continue
        unit0 = _num(est.get("unit_cost_usd"))
        if unit0 is None:
            continue
        drivers = est.get("drivers") or []
        cycle = next((d for d in drivers if d.get("name") == "cycle_time"), None)
        machine = next((d for d in drivers if d.get("name") == "machine_cost"), None)
        conf = est.get("confidence") or {}
        before = {
            "unit_cost_usd": unit0,
            "cycle_time_hr": _num((cycle or {}).get("value")),
            "machine_cost_usd": _num((machine or {}).get("value")),
            "low_usd": _num(conf.get("low_usd")),
            "high_usd": _num(conf.get("high_usd")),
            "point_usd": _num(conf.get("point_usd")),
        }
        unit = unit0
        n_h = f.get("hours_parts") or f.get("hours_n")
        n_c = f.get("cost_parts") or f.get("cost_n")
        if h and h > 0 and cycle is not None and _num(cycle.get("value")) is not None:
            note = f" × {h:g} from your actuals on {n_h} parts ({_pct(h)} machine time)"
            cycle["value"] = round(cycle["value"] * h, 6)
            cycle["source"] = f"{cycle.get('source') or ''}{note}"
            cycle["provenance"] = "SHOP"
            if machine is not None and _num(machine.get("value")) is not None:
                delta = machine["value"] * (h - 1.0)
                machine["value"] = round(machine["value"] * h, 4)
                machine["source"] = f"{machine.get('source') or ''}{note}"
                machine["provenance"] = "SHOP"
                unit += delta
                items = est.get("line_items")
                if isinstance(items, dict) and _num(items.get("machine")) is not None:
                    items["machine"] = round(items["machine"] * h, 4)
                if _num(est.get("variable_cost_usd")) is not None:
                    est["variable_cost_usd"] = round(est["variable_cost_usd"] + delta, 4)
        if c and c > 0:
            delta = unit * (c - 1.0)
            drivers.append({
                "name": CAL_DRIVER,
                "value": round(delta, 4),
                "unit": "$",
                "provenance": "SHOP",
                "source": f"cost per part × {c:g} from your actuals on {n_c} parts ({_pct(c)})",
                "error_band_pct": None,
            })
            est["drivers"] = drivers
            items = est.get("line_items")
            if isinstance(items, dict):
                items["your_actuals"] = round(delta, 4)
            unit *= c
        if unit <= 0:
            continue
        est["unit_cost_usd"] = round(unit, 2)
        r = unit / unit0 if unit0 else 1.0
        if conf:
            for k in ("low_usd", "high_usd", "point_usd"):
                if _num(conf.get(k)) is not None:
                    conf[k] = round(conf[k] * r, 2)
            conf["basis"] = f"{conf.get('basis') or ''}; moved with your calibration ({_pct(r)})"
        est["calibration"] = {
            "id": calibration_id,
            "applied_at": applied_at,
            "hours_factor": h,
            "cost_factor": c,
            "before": before,
        }
        ratio_by[(est.get("process"), est.get("quantity"))] = r

    decision = out.get("decision")
    if isinstance(decision, dict) and ratio_by:
        for q, rec in (decision.get("recommendation") or {}).items():
            r = _ratio(ratio_by, rec, q)
            if r is not None and _num(rec.get("unit_cost_usd")) is not None:
                rec["unit_cost_usd"] = round(rec["unit_cost_usd"] * r, 2)
        for q, opt in (decision.get("options") or {}).items():
            for side in ("in_house", "outside"):
                s = (opt or {}).get(side)
                r = _ratio(ratio_by, s or {}, q)
                if s and r is not None:
                    for k in ("unit_cost_usd", "low_usd", "high_usd"):
                        if _num(s.get(k)) is not None:
                            s[k] = round(s[k] * r, 2)
        decision["calibration_note"] = (
            "Costs and machine time for calibrated methods include your calibration. "
            "The pick per quantity is the engine's, made before calibration."
        )
    out["calibration"] = {"id": calibration_id, "applied_at": applied_at,
                          "processes": sorted({p for p, _ in ratio_by})}
    return out


def _ratio(ratio_by: dict, rec: dict, q) -> Optional[float]:
    proc = (rec or {}).get("process")
    for key in ((proc, q), (proc, _int(q))):
        if key in ratio_by:
            return ratio_by[key]
    return None


def _int(q):
    try:
        return int(q)
    except (TypeError, ValueError):
        return q


async def apply_org_calibration(session: Optional[AsyncSession], org_id: Optional[str], result: dict) -> dict:
    """The served-path hook: the org's calibration on a fresh estimate, or the estimate unchanged.

    Never fails the estimate: a read or overlay error logs and returns the
    engine's numbers untouched.
    """
    if not isinstance(session, AsyncSession) or not isinstance(org_id, str) or not org_id or not isinstance(result, dict):
        return result
    try:
        # A savepoint, so a failed read never aborts the caller's transaction.
        async with session.begin_nested():
            cal = await active_calibration(session, org_id)
        if not isinstance(cal, OrgCalibration) or not isinstance(cal.factors, dict) or not cal.factors:
            return result
        return overlay(result, cal.factors, calibration_id=cal.ulid, applied_at=_iso(cal.applied_at))
    except Exception:
        logger.warning("calibration overlay failed for org %s; estimate served uncalibrated", org_id, exc_info=True)
        return result
