"""The price at any quantity, from the model's own structure (ce-06, ce-15).

Every estimate carries ``qty_model``: its cost lines sorted by how they move with
the quantity, read off the same arithmetic ``cost_model.cost_breakdown`` does. A
price at a quantity the record didn't run is then the model's own number, not a
straight line drawn between two priced quantities:

    core(q) = once ÷ q + per part + machine + learning × A(q)
              + Σ lot × max(1, q ÷ parts) ÷ q             (setups paid per plate)
    unit(q) = max(order minimum ÷ q, core(q))
              + Σ max(lot minimum, per part × q) ÷ q       (outside finishes and heat treatments)
              + Σ (once ÷ q + per part)                    (declared inspection hours)

``A(q)`` is the learning curve's lot average (``src.costing.learning``). A
calibration from your actuals scales the machine line by its hours factor and the
whole price by its cost factor, as ``calibration_service`` does.

``tests/test_quantity_model.py`` holds the model to ``cost_breakdown`` at every
quantity for every process.
"""

from __future__ import annotations

import math
from typing import Optional

from src.costing.learning import lot_average_factor

VERSION = 1


def new() -> dict:
    return {
        "v": VERSION,
        "once_usd": 0.0,          # paid once for the order (tooling, programming, first setup, first article)
        "per_part_usd": 0.0,      # each part, the same at any quantity (material, tools, finishing)
        "machine_usd": 0.0,       # each part's machine line (calibration's hours factor scales it)
        "learning_usd": 0.0,      # each part's touch labor at the first lot's hours (× the lot average)
        "learning": None,         # {"rate", "first_lot", "floor"} or None
        "per_plate": [],          # [{"lot_usd", "parts"}]: paid once per plate of ``parts``
        "order_min_usd": 0.0,     # the order minimum on the lines above
        "specs": [],              # [{"min_usd", "per_part_usd"}] or [{"once_usd", "per_part_usd"}]
    }


def _r(x: float) -> float:
    return round(float(x), 6)


def finish(m: dict) -> dict:
    """The model as stored: numbers to 6 decimals."""
    out = dict(m)
    for k in ("once_usd", "per_part_usd", "machine_usd", "learning_usd", "order_min_usd"):
        out[k] = _r(out[k])
    out["per_plate"] = [{"lot_usd": _r(p["lot_usd"]), "parts": float(p["parts"])} for p in out["per_plate"]]
    out["specs"] = [{k: _r(v) for k, v in s.items()} for s in out["specs"]]
    return out


def core_at(m: dict, q: float) -> float:
    q = float(q)
    learn = m.get("learning") or None
    a = lot_average_factor(learn["rate"], learn["first_lot"], learn["floor"], q) if learn else 1.0
    core = (m["once_usd"] / q + m["per_part_usd"] + m["machine_usd"] + m["learning_usd"] * a
            + sum(p["lot_usd"] * max(1.0, q / p["parts"]) / q for p in m.get("per_plate") or []))
    return max(m.get("order_min_usd", 0.0) / q, core)


def specs_at(m: dict, q: float) -> float:
    q = float(q)
    total = 0.0
    for s in m.get("specs") or []:
        if "min_usd" in s:
            total += max(s["min_usd"], s["per_part_usd"] * q) / q
        else:
            total += s.get("once_usd", 0.0) / q + s.get("per_part_usd", 0.0)
    return total


def model_at(m: dict, q: float) -> float:
    """The model's unit cost at ``q`` parts, before any calibration."""
    return core_at(m, q) + specs_at(m, q)


def unit_cost_at(estimate: dict, q: float) -> Optional[float]:
    """The estimate's own model priced at ``q`` parts, or None when the record has no
    model (priced before it was kept) or ``q`` isn't a positive count."""
    m = (estimate or {}).get("qty_model")
    try:
        q = float(q)
    except (TypeError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("v") != VERSION or not (q >= 1) or not math.isfinite(q):
        return None
    unit = model_at(m, q)
    cal = estimate.get("calibration") if isinstance(estimate.get("calibration"), dict) else None
    if cal:
        h = cal.get("hours_factor")
        c = cal.get("cost_factor")
        if isinstance(h, (int, float)) and h > 0:
            unit += m["machine_usd"] * (h - 1.0)
        if isinstance(c, (int, float)) and c > 0:
            unit *= c
    return unit


def fixed_and_variable(m: dict, q: float) -> tuple[float, float]:
    """What the order pays once and what each part adds at ``q`` (for the words)."""
    q = float(q)
    unit = model_at(m, q)
    once = m["once_usd"] + sum(s.get("once_usd", 0.0) for s in m.get("specs") or [])
    return once, unit - once / q
