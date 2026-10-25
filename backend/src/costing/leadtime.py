"""Lead-time model (spec §7) — gate G5.

A range with stated components that scales with quantity. Never a fake precise
date. Every component is a labeled day-count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.analysis.models import ProcessType
from src.costing.rates import RateCard


@dataclass
class LeadTime:
    process: str
    quantity: int
    low_days: float
    high_days: float
    mid_days: float
    components: dict = field(default_factory=dict)   # queue/tooling_lead/production/post_process/ship
    capacity: dict = field(default_factory=dict)     # R1: stated, inspectable, overridable pool assumption


def lead_time(process: ProcessType, drivers_or_cycle_hr, qty: int,
              rates: RateCard, in_house: "dict | None" = None) -> LeadTime:
    """cycle_hr may be passed directly (float) — it is the MEASURED-driven driver
    from the cost model, so production days stay consistent with the cost cycle.

    R1: production days use a finite-capacity PARALLEL machine pool running at a
    process-appropriate daily uptime instead of one machine at one shift. The
    pool assumption (n_machines × machine_hours_per_day) is stated, surfaced as
    an inspectable `capacity` dict, and overridable -> USER. Lead time still grows
    monotonically with qty (qty in the numerator), so G5 holds; unit cost is
    unaffected (R1 touches lead-time only).

    ``in_house`` (``{"machine": name, "count": n}``) is set when the route runs
    on a machine the shop owns that clears every fit gate. Its production then
    runs on the shop's own declared machines, not an outside pool, and nothing
    ships: queue and ship are 0 (the shop's own schedule isn't known and is
    said so in ``capacity.basis``). None (the default) => byte-identical.
    """
    cycle_hr = float(drivers_or_cycle_hr)
    if in_house:
        return _in_house_lead_time(process, cycle_hr, qty, rates, in_house)
    n_machines = rates.machine_pool(process)
    hours = rates.machine_hours_per_day(process)

    production = math.ceil(qty * cycle_hr / (n_machines * hours))
    tooling_lead = rates.tooling_lead_days(process)
    queue = rates.p(process, "queue_days")
    post = rates.p(process, "post_days")
    ship = rates.g("ship_days")

    components = {
        "queue": float(queue),
        "tooling_lead": float(tooling_lead),
        "production": float(production),
        "post_process": float(post),
        "ship": float(ship),
    }
    cap_user = (f"n_machines.{process.name}" in rates.user_keys
                or f"machine_hours_per_day.{process.name}" in rates.user_keys)
    capacity = {
        "n_machines": int(n_machines),
        "machine_hours_per_day": float(hours),
        "provenance": "USER" if cap_user else "DEFAULT",
        "basis": (f"capacity-bound: {int(n_machines)} machines × {hours:g} hr/day "
                  f"parallel pool; production = ceil({qty}·{cycle_hr:.3f}hr ÷ "
                  f"({int(n_machines)}×{hours:g})) = {production} d"),
    }
    mid = sum(components.values())
    return LeadTime(
        process=process.value,
        quantity=int(qty),
        low_days=round(mid * 0.7, 1),
        high_days=round(mid * 1.3, 1),
        mid_days=round(mid, 1),
        components=components,
        capacity=capacity,
    )


def _in_house_lead_time(process: ProcessType, cycle_hr: float, qty: int,
                        rates: RateCard, in_house: dict) -> LeadTime:
    """Lead time on the shop's own machines: production on the declared count
    of the fitted machine at the process's typical daily uptime, the same
    post-processing and tooling lead, no outside queue and no shipping."""
    count = in_house.get("count")
    n_machines = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 1
    name = in_house.get("machine") or process.value
    hours = rates.machine_hours_per_day(process)
    production = math.ceil(qty * cycle_hr / (n_machines * hours))
    components = {
        "queue": 0.0,
        "tooling_lead": float(rates.tooling_lead_days(process)),
        "production": float(production),
        "post_process": float(rates.p(process, "post_days")),
        "ship": 0.0,
    }
    capacity = {
        "n_machines": int(n_machines),
        "machine_hours_per_day": float(hours),
        "provenance": "USER",
        "in_house": True,
        "machine": name,
        "basis": (f"in-house: your {int(n_machines)} × {name} at {hours:g} hr/day "
                  f"(typical uptime, not your schedule); production = ceil({qty}·"
                  f"{cycle_hr:.3f}hr ÷ ({int(n_machines)}×{hours:g})) = {production} d; "
                  f"made in your building, so no shipping; your own queue is not included"),
    }
    mid = sum(components.values())
    return LeadTime(
        process=process.value,
        quantity=int(qty),
        low_days=round(mid * 0.7, 1),
        high_days=round(mid * 1.3, 1),
        mid_days=round(mid, 1),
        components=components,
        capacity=capacity,
    )
