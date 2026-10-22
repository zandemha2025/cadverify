"""Lengths in the person's unit for exports (mm or in; display only).

The engine always works in millimetres. An export a person downloads (the
cost-report PDF) shows lengths in their chosen unit (``users.preferences.
length_unit``, migration 0056); a supplier's copy (RFQ package) shows that unit
first with millimetres alongside. Conversions are exact (1 in = 25.4 mm,
1 in² = 6.4516 cm², 1 in³ = 16.387064 cm³) and every figure carries its unit.
Mirrors ``frontend/src/components/v4/units/units.ts``.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

MM_PER_IN = 25.4
CM2_PER_IN2 = 6.4516
CM3_PER_IN3 = 16.387064

_RUN = re.compile(
    r"((?:[-−±]?\d[\d,]*(?:\.\d+)?)(?:\s*(?:×|x|–|-|to)\s*(?:[-−±]?\d[\d,]*(?:\.\d+)?))*)\s?(mm³|mm²|mm\b|cm³|cm²)")
_NUM = re.compile(r"[-−±]?\d[\d,]*(?:\.\d+)?")


def _inch_dp(mm: float) -> int:
    v = abs(mm) / MM_PER_IN
    return 3 if v < 10 else 2 if v < 100 else 1


def length(mm: Optional[float], unit: str) -> str:
    if mm is None:
        return "—"
    if unit == "in":
        return f"{mm / MM_PER_IN:,.{_inch_dp(mm)}f} in"
    return f"{mm:,.1f}".rstrip("0").rstrip(".") + " mm"


def dims(mm: Optional[Iterable[float]], unit: str) -> str:
    vals = [float(v) for v in (mm or []) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not vals:
        return "—"
    if unit == "in":
        return " × ".join(f"{v / MM_PER_IN:,.{_inch_dp(v)}f}" for v in vals) + " in"
    return " × ".join(f"{v:g}" for v in vals) + " mm"


def area_cm2(cm2, unit: str) -> str:
    if not isinstance(cm2, (int, float)) or isinstance(cm2, bool):
        return "N/A"
    return f"{cm2 / CM2_PER_IN2:,.2f} in²" if unit == "in" else f"{cm2:g} cm²"


def volume_cm3(cm3, unit: str) -> str:
    if not isinstance(cm3, (int, float)) or isinstance(cm3, bool):
        return "N/A"
    return f"{cm3 / CM3_PER_IN3:,.3f} in³" if unit == "in" else f"{cm3:g} cm³"


def in_text(text, unit: str, keep_mm: bool = False):
    """Engine text with every mm figure in inches ("needs 1306 mm" → "needs 51.42 in").

    ``keep_mm`` (a supplier's copy) keeps the millimetres alongside:
    "needs 51.42 in (1306 mm)".
    """
    if not isinstance(text, str) or unit != "in":
        return text

    def run(m: re.Match) -> str:
        nums, u = m.group(1), m.group(2)
        factor = {"mm": MM_PER_IN, "mm²": MM_PER_IN ** 2, "mm³": MM_PER_IN ** 3,
                  "cm²": CM2_PER_IN2, "cm³": CM3_PER_IN3}[u]

        def one(n: re.Match) -> str:
            raw = n.group(0)
            sign = raw[0] if raw[0] in "−±-" else ""
            try:
                v = float(raw.lstrip("−±-").replace(",", ""))
            except ValueError:
                return raw
            dp = _inch_dp(v) if u == "mm" else 3
            return f"{sign}{v / factor:,.{dp}f}"

        out = _NUM.sub(one, nums)
        shown = f"{out} {'in' if u == 'mm' else 'in²' if u in ('mm²', 'cm²') else 'in³'}"
        return f"{shown} ({nums} {u})" if keep_mm else shown

    return _RUN.sub(run, text)


# ── a supplier's copy: the unit first, millimetres alongside ───────────────────
# An RFQ package goes to a supplier, who may work in either unit; the drawing and
# the engine are in mm. Inches lead when the copy's unit is inches, with the mm
# figure beside each one ("11.81 × 7.874 × 3.937 in (300 × 200 × 100 mm)").
# In mm the figure is shown once.


def dims_with_mm(mm: Optional[Iterable[float]], unit: str) -> str:
    shown = dims(mm, unit)
    return f"{shown} ({dims(mm, 'mm')})" if unit == "in" and shown != "—" else shown


def area_with_cm2(cm2, unit: str) -> str:
    shown = area_cm2(cm2, unit)
    return f"{shown} ({area_cm2(cm2, 'mm')})" if unit == "in" and shown != "N/A" else shown


def volume_with_cm3(cm3, unit: str) -> str:
    shown = volume_cm3(cm3, unit)
    return f"{shown} ({volume_cm3(cm3, 'mm')})" if unit == "in" and shown != "N/A" else shown


async def length_unit_for(session, user_id: int) -> str:
    """The person's unit ("mm" when unset or unreadable)."""
    try:
        from src.db.models import User

        row = await session.get(User, user_id)
        prefs = getattr(row, "preferences", None) if row is not None else None
        unit = prefs.get("length_unit") if isinstance(prefs, dict) else None
        return unit if unit in ("mm", "in") else "mm"
    except Exception:  # noqa: BLE001 — a display preference never breaks an export
        return "mm"
