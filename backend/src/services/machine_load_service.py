"""Machine load: the hours of work the organization's checked parts put on each machine it owns.

For each part, its newest saved record (the cost decision with its machine
fit) and the newest outcome recorded on any of its records:

* recorded "Make in-house" with a process and quantity: that process's machine
  time per part × that quantity, on the machine of yours that clears the route
  on the newest record (``basis: "decided"``);
* nothing recorded, and the newest record sorts the part onto one of your
  machines: its machine time on that machine at the quantity the part was
  checked for (a catalog run's listed quantity, a declared yearly volume: the
  one quantity the record priced off the standard ladder; ``basis:
  "checked"``), else at ``DEFAULT_QUANTITY`` of the part (``basis:
  "default"``), the pilot report's "every part" quantity;
* recorded another way (outside, acquire, redesign): not counted on a machine,
  only in ``other_decisions``.

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
OTHER_OUTCOMES = ("outside", "acquire", "redesign")


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


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


def part_load(result: Optional[dict], disposition: Optional[str], basis: Optional[dict],
              default_quantity: int = DEFAULT_QUANTITY) -> Optional[dict]:
    """Where one part's machine time lands, and how much. None when it lands on no machine of yours. Pure."""
    result = result if isinstance(result, dict) else {}
    v = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    per_route = v.get("per_route") if isinstance(v.get("per_route"), dict) else {}
    resource = v.get("resource") if isinstance(v.get("resource"), dict) else {}
    if disposition in OTHER_OUTCOMES:
        return {"basis": "other", "disposition": disposition}
    if disposition == "inhouse" and isinstance(basis, dict) and basis.get("process") and basis.get("quantity"):
        process = str(basis["process"])
        try:
            qty = int(basis["quantity"])
        except (TypeError, ValueError):
            qty = 0
        route = per_route.get(process) if isinstance(per_route.get(process), dict) else {}
        machine = route.get("best_machine") if route.get("verdict") in IN_HOUSE else None
        if machine is None and v.get("verdict") in IN_HOUSE and resource.get("process") == process:
            machine = resource.get("machine") or v.get("best_machine")
        hours_each = _hours_each(result, process, qty) if qty > 0 else None
        return {"basis": "decided", "machine": machine, "process": process, "quantity": qty,
                "hours_each": hours_each, "hours": round(hours_each * qty, 4) if hours_each is not None else None}
    if v.get("verdict") in IN_HOUSE and (resource.get("machine") or v.get("best_machine")):
        process = resource.get("process")
        own = checked_quantity(result)
        qty = own or default_quantity
        hours_each = _hours_each(result, process, qty) if process else None
        return {"basis": "checked" if own else "default", "machine": resource.get("machine") or v.get("best_machine"),
                "process": process, "quantity": qty, "hours_each": hours_each,
                "hours": round(hours_each * qty, 4) if hours_each is not None else None}
    return None


def machine_load(parts: Iterable[dict], default_quantity: int = DEFAULT_QUANTITY) -> dict:
    """Per machine of yours: parts and machine hours, decided and not yet decided. Pure.

    ``parts``: ``{part_key, record_id, file_name, label, result, disposition, basis, stale}``.
    """
    machines: dict[str, dict] = {}
    other = 0
    unplaced: list[dict] = []
    n = 0
    for p in parts:
        n += 1
        load = part_load(p.get("result"), p.get("disposition"), p.get("basis"), default_quantity)
        if load is None:
            continue
        if load["basis"] == "other":
            other += 1
            continue
        if not load.get("machine"):
            unplaced.append({"part_key": p.get("part_key"), "record_id": p.get("record_id"),
                             "file_name": p.get("label") or p.get("file_name"),
                             "process": load.get("process"), "quantity": load.get("quantity")})
            continue
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
                         "quantity": load.get("quantity"), "basis": load["basis"], "hours_each": load.get("hours_each"),
                         "hours": h})
    for m in machines.values():
        m["top"].sort(key=lambda t: (-(t["hours"] or 0.0), str(t["file_name"] or "")))
        m["top"] = m["top"][:TOP_PARTS]
    return {
        "quantity": default_quantity,
        "parts": n,
        "machines": sorted(machines.values(), key=lambda m: (-(m["hours"] or 0.0), -m["parts"], m["machine"])),
        "other_decisions": other,
        "decided_unplaced": unplaced[:TOP_PARTS],
        "decided_unplaced_count": len(unplaced),
    }


async def org_machine_load(session: AsyncSession, org_id: str, default_quantity: int = DEFAULT_QUANTITY) -> dict:
    """``machine_load`` over the org's parts: each part's newest record and newest recorded outcome."""
    from src.db.models import CostDecision
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
    now = datetime.now(timezone.utc)

    def stale(at) -> bool:
        if not isinstance(at, datetime):
            return False
        return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) <= now

    parts = []
    for key, ulid, filename, label, stale_at, quantities, result in newest:
        disp, basis = outcomes.get(key, (None, None))
        # The board's slice of the record leaves out its quantities; the column holds the same list.
        result = {**(result or {}), "quantities": quantities if isinstance(quantities, list) else []}
        parts.append({"part_key": key, "record_id": ulid, "file_name": filename, "label": label,
                      "result": result, "disposition": disp, "basis": basis, "stale": stale(stale_at)})
    return machine_load(parts, default_quantity)
