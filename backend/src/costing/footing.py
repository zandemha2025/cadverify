"""Cost lines that add up to the unit cost to the cent (ce-01).

The engine keeps each line to four decimals and rounds the unit cost once, from
the unrounded sum, so lines rounded to the cent one by one can miss the price by a
cent or two ($0.70 + 17.50 + 15.69 + 0.52 + 1.23 + 0.78 + 0.26 = $36.68 against a
$36.69 unit cost). Every place that prints the lines next to the price (the
breakdown, the part page, the PDF's line table, the CSV) foots them the same way:
each line is rounded to the cent on its own, and the difference is a visible
"Rounding" line, so each line still matches its own formula and the column adds up.

Rounding is half-up on the number as stored (1.225 → 1.23, 0.175 → 0.18), the same
rule the screen's ``toLocaleString`` applies; ``frontend/src/lib/cost-lines.ts`` is
the same helper for the screen.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

ROUNDING_KEY = "rounding"
# A gap rounding can't make (more than half a cent a line, plus the unit's own): the
# lines don't account for the price, and the column says so instead of "Rounding".
UNACCOUNTED_KEY = "not_in_lines"

# The screen's names for the engine's line keys (frontend workbench/words.ts LINE).
LINE_NAMES: dict = {
    "amortized_fixed": "Setup",
    "tooling": "Tooling",
    "material": "Material",
    "machine": "Machine",
    "labor": "Labor",
    "nre": "Programming",
    "inspection": "Inspection",
    "consumables": "Tools and coolant",
    "finishing": "Finishing",
    "tolerance": "Tolerance",
    "finish_machining": "Finish machining",
    "min_charge_floor": "Minimum charge",
    "plate_removal": "Plate removal",
    "sinter": "Sintering",
    "stress_relief": "Stress relief",
    "support_removal": "Support removal",
    "your_actuals": "Your actuals",
    ROUNDING_KEY: "Rounding",
    UNACCOUNTED_KEY: "Not in the lines",
}


# The engine driver that explains each line (its formula, tag and band); the rest are
# "<line>_cost" (frontend lib/cost-lines.ts lineDriver).
LINE_DRIVER: dict = {
    "amortized_fixed": "setup_cost",
    "tooling": "tooling_per_part",
    "tolerance": "tolerance_class",
    "min_charge_floor": "min_charge_floor",
    "finish_machining": "finish_machining",
}


def line_driver(key: str) -> str:
    return LINE_DRIVER.get(key, f"{key}_cost")


def cents(value) -> int:
    """``value`` dollars as whole cents, half-up on its decimal form."""
    d = Decimal(repr(float(value))) * 100
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def usd(c: int) -> float:
    return c / 100.0


def line_name(key: str) -> str:
    if key in LINE_NAMES:
        return LINE_NAMES[key]
    return key.removeprefix("spec_").replace("_", " ").capitalize()


def foot(line_items: dict, unit_cost) -> dict:
    """The lines in cents, the rounding that makes them add up, and the unit cost in cents.

    ``{"lines": [(key, cents), ...], "rounding_cents": int, "unit_cents": int}``. A line
    of exactly $0 is left out (a mold with no setup); Σ lines + rounding == unit.
    """
    lines = [(k, cents(v)) for k, v in (line_items or {}).items()
             if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) != 0.0]
    unit = cents(unit_cost or 0.0)
    gap = unit - sum(c for _k, c in lines)
    return {"lines": lines, "rounding_cents": gap, "unit_cents": unit,
            "is_rounding": abs(gap) <= -(-(len(lines) + 1) // 2)}


def footed_items(line_items: dict, unit_cost) -> dict:
    """``{key: dollars}`` to the cent, with ``rounding`` when it isn't zero: they sum to the price."""
    f = foot(line_items, unit_cost)
    out = {k: usd(c) for k, c in f["lines"]}
    if f["rounding_cents"]:
        out[ROUNDING_KEY if f["is_rounding"] else UNACCOUNTED_KEY] = usd(f["rounding_cents"])
    return out


def keys_in(estimates: Iterable[dict]) -> list:
    """The line keys of a set of estimates, first-seen order, with Rounding last when any row has it."""
    keys: list = []
    tail: list = []
    for e in estimates:
        f = foot(e.get("line_items") or {}, e.get("unit_cost_usd"))
        for k, _c in f["lines"]:
            if k not in keys:
                keys.append(k)
        if f["rounding_cents"]:
            k = ROUNDING_KEY if f["is_rounding"] else UNACCOUNTED_KEY
            if k not in tail:
                tail.append(k)
    return keys + tail
