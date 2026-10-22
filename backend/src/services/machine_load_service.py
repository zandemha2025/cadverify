"""Machine load: the hours of work the organization's checked parts put on each
machine it owns, against the hours each machine has.

For each part, its newest saved record (the cost decision with its machine
fit), the newest outcome recorded on any of its records, and its declared
facts (the yearly quantity and what the org pays for it today):

* the quantity is the part's yearly quantity (a catalog run's parts list, or
  declared on the part) when its record priced it (``quantity_basis:
  "yearly"``), else the one quantity the record priced off the standard ladder
  (``"checked"``), else ``DEFAULT_QUANTITY`` (``"default"``). A recorded
  outcome never changes it: a sign-off at another quantity is shown as such
  (``decided_quantity``), and the load stays at the yearly quantity, the same
  one the run and the pilot report count;
* recorded "Make in-house" with a process: that process's machine time per part
  × the quantity, on the machine of yours that clears the route on the newest
  record (``basis: "decided"``);
* nothing recorded, and the newest record sorts the part onto one of your
  machines: when what you pay today beats making it (the run's own rule,
  ``catalog_run_service.make_or_buy_pick``) it is bought, so it adds no hours
  (``bought``); else its machine time on that machine (``basis: "checked"`` or
  ``"default"`` by its quantity);
* recorded another way (outside, keep buying from our supplier, acquire,
  redesign): not counted on a machine, only in ``other_decisions``.

Capacity: each machine (or identical group, × ``count``) has its available
hours a year from its declared ``schedule`` (shifts × hours per shift × days),
else ``DEFAULT_SCHEDULE``, said as the assumption. Per machine: hours needed
against hours available, utilization, and ``overloaded`` when the parts need
more than it has.

Every hour is the engine's own estimate: the route's ``cycle_time`` driver
(machine hours per part) at exactly that quantity, times the quantity. A
quantity the record didn't price leaves the hours unknown (counted in
``hours_parts``), never estimated here. Org-scoped; nothing here leaves the
organization (it isn't part of any record or outbound copy).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_QUANTITY = 100
TOP_PARTS = 10
# The standard quantities every check prices; a part's own quantity takes the place of the nearest inner one.
LADDER = (1, 100, 1000, 2000, 5000, 10000)
IN_HOUSE = ("makeable_in_house", "makeable_with_secondary_op")
OTHER_OUTCOMES = ("outside", "supplier", "acquire", "redesign")
# The hours a machine is available a year when its own aren't set: two 8-hour shifts, 240 working days.
DEFAULT_SCHEDULE = {"shifts": 2, "hours_per_shift": 8.0, "days_per_year": 240}
SCHEDULE_LIMITS = {"shifts": (1, 4), "hours_per_shift": (0.5, 24.0), "days_per_year": (1, 366)}


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

def normalize_schedule(raw: Any) -> Optional[dict]:
    """``{shifts, hours_per_shift, days_per_year}`` as stored, or None for not set.

    Raises ``ValueError`` naming the field for a value out of range (shifts 1–4,
    0.5–24 h a shift, 1–366 days, and at most 24 h a day in all).
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("schedule must be an object with shifts, hours_per_shift and days_per_year")
    unknown = set(raw) - set(DEFAULT_SCHEDULE)
    if unknown:
        raise ValueError(f"unknown schedule field {sorted(unknown)[0]!r}")
    out: dict = {}
    for key, (lo, hi) in SCHEDULE_LIMITS.items():
        v = raw.get(key, DEFAULT_SCHEDULE[key])
        f = _num(v)
        if f is None or not lo <= f <= hi:
            raise ValueError(f"schedule {key.replace('_', ' ')} must be from {lo:g} to {hi:g}")
        out[key] = int(f) if key != "hours_per_shift" else round(f, 2)
    if out["shifts"] * out["hours_per_shift"] > 24:
        raise ValueError("schedule shifts × hours per shift must be at most 24 hours a day")
    return out


def available_hours(schedule: Any, count: Any = 1) -> dict:
    """The hours a machine (× ``count``) is available a year, and the schedule they come from.

    ``{hours, count, shifts, hours_per_shift, days_per_year, set}``; ``set`` is
    False when it is ``DEFAULT_SCHEDULE``, the assumption shown with it.
    """
    try:
        s = normalize_schedule(schedule)
    except ValueError:
        s = None
    n = max(1, int(count or 1)) if isinstance(count, (int, float)) and not isinstance(count, bool) else 1
    used = s or DEFAULT_SCHEDULE
    hours = n * used["shifts"] * float(used["hours_per_shift"]) * used["days_per_year"]
    return {"hours": round(hours, 1), "count": n, "shifts": used["shifts"],
            "hours_per_shift": float(used["hours_per_shift"]), "days_per_year": used["days_per_year"],
            "set": s is not None}


def schedule_text(cap: dict) -> str:
    """``3 machines × 2 shifts × 8 h × 240 days = 11,520 h a year`` (``(assumed)`` when not set)."""
    machines = f"{cap['count']} machines × " if cap.get("count", 1) > 1 else ""
    h = cap["hours_per_shift"]
    hours = f"{h:g}"
    text = (f"{machines}{cap['shifts']} {'shift' if cap['shifts'] == 1 else 'shifts'} × {hours} h × "
            f"{cap['days_per_year']} days = {cap['hours']:,.0f} h a year")
    return text if cap.get("set") else f"{text} (assumed; set its hours in Your shop)"


def with_capacity(rows: Iterable[dict], capacity: dict[str, dict]) -> list[dict]:
    """Each ``{machine, hours, ...}`` row with ``available_hours``, ``utilization_pct``,
    ``overloaded`` and ``capacity`` (``available_hours``'s dict plus ``text``), when the
    machine is one of yours (``capacity``: by name)."""
    out = []
    for r in rows:
        cap = capacity.get(r.get("machine") or "")
        r = dict(r)
        if cap is None:
            r.update(available_hours=None, utilization_pct=None, overloaded=None, capacity=None)
        else:
            need = _num(r.get("hours")) or 0.0
            r["available_hours"] = cap["hours"]
            r["utilization_pct"] = round(need / cap["hours"] * 100, 1) if cap["hours"] > 0 else None
            r["overloaded"] = need > cap["hours"]
            r["capacity"] = {**cap, "text": schedule_text(cap)}
        out.append(r)
    return out


def capacity_by_name(machines: Iterable[Any]) -> dict[str, dict]:
    """``{name: available_hours(...)}`` for the org's machines (rows with name, count, schedule).

    Machines that share a name are one group: their counts add, at the first one's schedule.
    """
    groups: dict[str, dict] = {}
    for m in machines:
        name = getattr(m, "name", None) if not isinstance(m, dict) else m.get("name")
        if not name:
            continue
        count = (getattr(m, "count", 1) if not isinstance(m, dict) else m.get("count", 1)) or 1
        schedule = getattr(m, "schedule", None) if not isinstance(m, dict) else m.get("schedule")
        g = groups.setdefault(name, {"count": 0, "schedule": schedule})
        g["count"] += int(count)
    return {name: available_hours(g["schedule"], g["count"]) for name, g in groups.items()}


async def org_capacity(session: AsyncSession, org_id: str) -> dict[str, dict]:
    """``capacity_by_name`` over the org's declared machines."""
    from src.db.models import MachineInstance

    rows = (await session.execute(
        select(MachineInstance.name, MachineInstance.count, MachineInstance.schedule)
        .where(MachineInstance.org_id == org_id).order_by(MachineInstance.id)
    )).all()
    return capacity_by_name({"name": n, "count": c, "schedule": s} for n, c, s in rows)


def overloaded_words(rows: Iterable[dict]) -> list[str]:
    """``Haas VF-2: 12,400 h needed of 11,520 h a year (108%)`` for each overloaded machine."""
    return [f"{r['machine']}: {r['hours']:,.0f} h needed of {r['available_hours']:,.0f} h a year "
            f"({r['utilization_pct']:.0f}%)" for r in rows if r.get("overloaded")]


# ---------------------------------------------------------------------------
# One part's load
# ---------------------------------------------------------------------------

def _hours_each(result: dict, process: str, qty: int) -> Optional[float]:
    """Machine hours per part for ``process`` at exactly ``qty``: the cheapest such estimate's cycle_time."""
    best = None
    for e in result.get("estimates") or []:
        if not isinstance(e, dict) or e.get("process") != process or e.get("quantity") != qty:
            continue
        if best is None or (_num(e.get("unit_cost_usd")) or 0) < (_num(best.get("unit_cost_usd")) or 0):
            best = e
    for d in (best or {}).get("drivers") or []:
        if isinstance(d, dict) and d.get("name") == "cycle_time":
            h = _num(d.get("value"))
            return h if h is not None and h >= 0 else None
    return None


def checked_quantity(result: dict) -> Optional[int]:
    """The quantity a part was checked for: the standard ladder with one inner point given way to it.

    Only that shape counts (both the catalog run and the single check build it);
    a record priced at quantities someone chose another way ("10, 100") has none.
    """
    qs = {int(q) for q in result.get("quantities") or [] if isinstance(q, (int, float)) and not isinstance(q, bool) and q > 0}
    extra = sorted(qs - set(LADDER))
    if len(qs) != len(LADDER) or len(extra) != 1 or LADDER[0] not in qs or LADDER[-1] not in qs:
        return None
    return extra[0]


def _priced(result: dict, qty: int) -> bool:
    qs = result.get("quantities")
    if isinstance(qs, list) and qs:
        return qty in qs
    return any(isinstance(e, dict) and e.get("quantity") == qty for e in result.get("estimates") or [])


def load_quantity(result: dict, yearly: Any, default_quantity: int = DEFAULT_QUANTITY) -> tuple[int, str]:
    """``(quantity, basis)``: the yearly quantity when the record priced it, else the checked one, else the default."""
    y = int(yearly) if isinstance(yearly, (int, float)) and not isinstance(yearly, bool) and yearly > 0 else None
    if y is not None and _priced(result, y):
        return y, "yearly"
    own = checked_quantity(result)
    if own is not None:
        return own, "checked"
    return default_quantity, "default"


def part_load(result: Optional[dict], disposition: Optional[str], basis: Optional[dict],
              default_quantity: int = DEFAULT_QUANTITY, *, yearly: Any = None,
              buy_price: Optional[dict] = None) -> Optional[dict]:
    """Where one part's machine time lands, and how much. None when it lands on no machine of yours. Pure.

    ``basis``: the recorded outcome's basis. ``yearly``: the part's declared yearly
    quantity. ``buy_price``: what the org pays for it today (``{usd_each, ...}``).
    """
    result = result if isinstance(result, dict) else {}
    v = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    per_route = v.get("per_route") if isinstance(v.get("per_route"), dict) else {}
    resource = v.get("resource") if isinstance(v.get("resource"), dict) else {}
    if disposition in OTHER_OUTCOMES:
        return {"basis": "other", "disposition": disposition}
    qty, qty_basis = load_quantity(result, yearly, default_quantity)
    if disposition == "inhouse" and isinstance(basis, dict) and basis.get("process") and basis.get("quantity"):
        process = str(basis["process"])
        try:
            decided_at = int(basis["quantity"])
        except (TypeError, ValueError):
            decided_at = None
        if qty_basis == "default" and decided_at:
            qty, qty_basis = decided_at, "decided"  # no yearly or checked quantity: the one it was decided at
        route = per_route.get(process) if isinstance(per_route.get(process), dict) else {}
        machine = route.get("best_machine") if route.get("verdict") in IN_HOUSE else None
        if machine is None and v.get("verdict") in IN_HOUSE and resource.get("process") == process:
            machine = resource.get("machine") or v.get("best_machine")
        hours_each = _hours_each(result, process, qty) if qty > 0 else None
        return {"basis": "decided", "machine": machine, "process": process, "quantity": qty,
                "quantity_basis": qty_basis, "decided_quantity": decided_at,
                "hours_each": hours_each, "hours": round(hours_each * qty, 4) if hours_each is not None else None}
    if v.get("verdict") in IN_HOUSE and (resource.get("machine") or v.get("best_machine")):
        process = resource.get("process")
        machine = resource.get("machine") or v.get("best_machine")
        options = (result.get("decision") or {}).get("options") or {}
        opt = options.get(str(qty)) if isinstance(options, dict) else None
        inside = (opt or {}).get("in_house") if isinstance(opt, dict) else None
        if isinstance(inside, dict) and inside.get("process"):
            # The cheapest route on a machine of yours at this quantity, as the run sorts it.
            process, machine = inside["process"], inside.get("machine") or machine
        price = _num((buy_price or {}).get("usd_each")) if isinstance(buy_price, dict) else None
        make = _num((inside or {}).get("unit_cost_usd")) if isinstance(inside, dict) else None
        if price is not None and price > 0 and make is not None:
            from src.services.catalog_run_service import make_or_buy_pick

            pick, _ = make_or_buy_pick({"unit_cost_usd": make, "low_usd": _num(inside.get("low_usd"))}, price)
            if pick != "in_house":
                return {"basis": "bought", "machine": machine, "process": process, "quantity": qty,
                        "make_each": make, "buy_each": price}
        hours_each = _hours_each(result, process, qty) if process else None
        return {"basis": "checked" if qty_basis != "default" else "default", "machine": machine,
                "process": process, "quantity": qty, "quantity_basis": qty_basis, "hours_each": hours_each,
                "hours": round(hours_each * qty, 4) if hours_each is not None else None}
    return None


def machine_load(parts: Iterable[dict], default_quantity: int = DEFAULT_QUANTITY,
                 capacity: Optional[dict[str, dict]] = None) -> dict:
    """Per machine of yours: parts and machine hours, decided and not yet decided, against capacity. Pure.

    ``parts``: ``{part_key, record_id, file_name, label, result, disposition, basis, stale,
    yearly, buy_price}``. ``capacity``: ``capacity_by_name`` (None: hours only).
    """
    machines: dict[str, dict] = {}
    other = 0
    bought = 0
    at_decided = 0
    unplaced: list[dict] = []
    n = 0
    for p in parts:
        n += 1
        load = part_load(p.get("result"), p.get("disposition"), p.get("basis"), default_quantity,
                         yearly=p.get("yearly"), buy_price=p.get("buy_price"))
        if load is None:
            continue
        if load["basis"] == "other":
            other += 1
            continue
        if load["basis"] == "bought":
            bought += 1
            continue
        if not load.get("machine"):
            unplaced.append({"part_key": p.get("part_key"), "record_id": p.get("record_id"),
                             "file_name": p.get("label") or p.get("file_name"),
                             "process": load.get("process"), "quantity": load.get("quantity")})
            continue
        if load.get("decided_quantity") and load["decided_quantity"] != load["quantity"]:
            at_decided += 1
        m = machines.setdefault(load["machine"], {
            "machine": load["machine"], "process": load.get("process"), "parts": 0, "hours": None, "hours_parts": 0,
            "decided_parts": 0, "decided_hours": None, "default_parts": 0, "default_hours": None,
            "stale_parts": 0, "top": [],
        })
        m["parts"] += 1
        kind = "decided" if load["basis"] == "decided" else "default"  # not decided yet: at its own or the default quantity
        m[f"{kind}_parts"] += 1
        if p.get("stale"):
            m["stale_parts"] += 1
        h = load.get("hours")
        if h is not None:
            m["hours"] = round((m["hours"] or 0.0) + h, 4)
            m["hours_parts"] += 1
            m[f"{kind}_hours"] = round((m[f"{kind}_hours"] or 0.0) + h, 4)
        m["top"].append({"part_key": p.get("part_key"), "record_id": p.get("record_id"),
                         "file_name": p.get("label") or p.get("file_name"), "process": load.get("process"),
                         "quantity": load.get("quantity"), "quantity_basis": load.get("quantity_basis"),
                         "decided_quantity": load.get("decided_quantity"), "basis": load["basis"],
                         "hours_each": load.get("hours_each"), "hours": h})
    for m in machines.values():
        m["top"].sort(key=lambda t: (-(t["hours"] or 0.0), str(t["file_name"] or "")))
        m["top"] = m["top"][:TOP_PARTS]
    rows = sorted(machines.values(), key=lambda m: (-(m["hours"] or 0.0), -m["parts"], m["machine"]))
    if capacity is not None:
        rows = with_capacity(rows, capacity)
    return {
        "quantity": default_quantity,
        "quantity_rule": ("Each part at its yearly quantity (from a catalog run's parts list, or set on the part); "
                          f"without one, at the quantity it was checked for, else {default_quantity} of it."),
        "parts": n,
        "machines": rows,
        "overloaded": overloaded_words(rows) if capacity is not None else [],
        "default_schedule": dict(DEFAULT_SCHEDULE),
        "other_decisions": other,
        # Undecided parts a machine of yours could make, where what you pay today beats making it.
        "bought": bought,
        # Decided in-house at another quantity than the one counted (shown, never the load basis).
        "decided_at_other_quantity": at_decided,
        "decided_unplaced": unplaced[:TOP_PARTS],
        "decided_unplaced_count": len(unplaced),
    }


async def org_machine_load(session: AsyncSession, org_id: str, default_quantity: int = DEFAULT_QUANTITY) -> dict:
    """``machine_load`` over the org's parts: each part's newest record, newest recorded
    outcome, yearly quantity and current price, against the org's machine capacity."""
    from src.db.models import CostDecision, PartContext
    from src.services.catalog_run_service import _BOARD_DECISION_SQL

    newest = (await session.execute(
        select(CostDecision.mesh_hash, CostDecision.ulid, CostDecision.filename, CostDecision.label,
               CostDecision.stale_at, CostDecision.quantities, literal_column(_BOARD_DECISION_SQL, type_=JSONB))
        .where(CostDecision.org_id == org_id)
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.created_at.desc(), CostDecision.id.desc())
    )).all()
    outcomes = {key: (disp, basis) for key, disp, basis in (await session.execute(
        select(CostDecision.mesh_hash, CostDecision.user_disposition, CostDecision.disposition_basis)
        .where(CostDecision.org_id == org_id, CostDecision.user_disposition.isnot(None))
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.disposition_updated_at.desc().nulls_last(),
                  CostDecision.created_at.desc())
    )).all()}
    facts = {key: (vol, price) for key, vol, price in (await session.execute(
        select(PartContext.mesh_hash, PartContext.annual_volume, PartContext.buy_price)
        .where(PartContext.org_id == org_id)
    )).all()}
    now = datetime.now(timezone.utc)

    def stale(at) -> bool:
        if not isinstance(at, datetime):
            return False
        return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) <= now

    parts = []
    for key, ulid, filename, label, stale_at, quantities, result in newest:
        disp, basis = outcomes.get(key, (None, None))
        yearly, price = facts.get(key, (None, None))
        # The board's slice of the record leaves out its quantities; the column holds the same list.
        result = {**(result or {}), "quantities": quantities if isinstance(quantities, list) else []}
        parts.append({"part_key": key, "record_id": ulid, "file_name": filename, "label": label,
                      "result": result, "disposition": disp, "basis": basis, "stale": stale(stale_at),
                      "yearly": yearly, "buy_price": price if isinstance(price, dict) else None})
    return machine_load(parts, default_quantity, capacity=await org_capacity(session, org_id))
