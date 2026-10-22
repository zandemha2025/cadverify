"""Which rate card a price was figured at, and which of its lines are the org's own (ce-10, ce-16).

An org publishes rate cards (``rate_library_service``): v1, v2, ... The engine
prices every check at the card in effect when the check ran, as its base table
(``routes._run_cost_decision``). Two things follow, and this module owns both:

* **Lines priced at the org's own rates say so.** A value the org changed in its
  published card (``changed_keys``: the labor rate, a machine rate, a material
  price, ...) is the org's, not a typical value. ``apply_rate_card`` re-tags every
  cost line and assumption that uses one: provenance ``SHOP`` (the org's own
  number, like a shop profile's), ``rate_card`` = the version, and the line's
  ``source`` names the value and the card ("$58/h labor rate from your rates
  v1"). Values the card still carries unchanged from the typical table stay
  ``DEFAULT``: copying a typical number into a card doesn't make it measured.
  Overhead and margin are named on the assumptions, not on each line (they scale
  every line; tagging each would claim more than the rate it uses).
* **A saved price says which card it was figured at.** ``basis`` reads a record's
  card version (the stamp ``apply_rate_card`` leaves, else the card in effect
  when the record was made) and the card in effect now, so every place that shows
  a price can say "Priced at rates v0; your rates are v1. Re-cost."

Version 0 is the typical table (``RATE_CARD_V0``), in use until an org publishes.
Pure functions take plain dicts and rows; ``org_rate_rows`` is the one org-scoped
read.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from src.costing.rates import RATE_CARD_V0

# What each cost line uses from the rate card, by its driver name. ``{P}`` is the
# process (enum name), ``{M}`` the material name, ``{C}`` the material class.
LINE_KEYS: dict[str, tuple[str, ...]] = {
    "labor_cost": ("labor_rate", "post_hr.{P}", "post_hr_part.{P}", "post_hr_build.{P}"),
    "setup_cost": ("labor_rate", "setup_hr.{P}"),
    "nre_cost": ("labor_rate", "nre_hr.{P}"),
    "inspection_cost": ("labor_rate", "fai_hr.{P}", "inspect_hr_part.{P}"),
    "machine_cost": ("machine_rate.{P}", "utilization"),
    "material_cost": ("material_price.{M}", "material_price.@{C}"),
    "tooling_cost": ("tooling.{P}",),
    "min_charge_floor": ("min_charge.{P}",),
    "consumables_cost": ("perishable_frac",),
    "finishing_cost": ("finish_per_part.{P}", "finish_lot_charge.{P}"),
    "post_process_cost": ("finish_per_part.{P}", "finish_lot_charge.{P}"),
}

# Assumption rows (``result.assumptions``) that are a single global rate-card key.
GLOBAL_ASSUMPTIONS = ("labor_rate", "margin", "overhead", "utilization", "stock_allowance",
                      "daily_machine_hours", "machine_labor_frac", "perishable_frac",
                      "machine_capital_frac")


def _num(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pt_name(token: Any) -> Optional[str]:
    """A process key from a payload or an estimate ('cnc_3axis', 'CNC_3AXIS', the enum) -> 'CNC_3AXIS'."""
    from src.analysis.models import ProcessType

    if isinstance(token, ProcessType):
        return token.name
    s = str(token or "")
    for pt in ProcessType:
        if s == pt.value or s == pt.name or s.upper() == pt.name:
            return pt.name
    return None


def _same(a, b) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return abs(fa - fb) <= 1e-9 * max(1.0, abs(fa), abs(fb))
    return a == b


def changed_keys(payload: Optional[dict]) -> dict[str, float]:
    """The dotted keys an org's card sets to a value other than the typical table's,
    with the card's value: ``{"labor_rate": 58.0, "machine_rate.CNC_3AXIS": 82.0,
    "material_price.Steel 1018": 2.4}``."""
    if not isinstance(payload, dict):
        return {}
    out: dict[str, float] = {}
    g0 = RATE_CARD_V0.get("global") or {}
    for k, v in (payload.get("global") or {}).items():
        if k in g0 and not _same(v, g0[k]) and _num(v) is not None:
            out[k] = float(v)
    p0 = {pt.name: fields for pt, fields in (RATE_CARD_V0.get("process") or {}).items()}
    for token, fields in (payload.get("process") or {}).items():
        name = _pt_name(token)
        if name is None or not isinstance(fields, dict) or name not in p0:
            continue
        for f, v in fields.items():
            if f in p0[name] and not _same(v, p0[name][f]) and _num(v) is not None:
                out[f"{f}.{name}"] = float(v)
    m0 = RATE_CARD_V0.get("material_prices") or {}
    for k, v in (payload.get("material_prices") or {}).items():
        if (k not in m0 or not _same(v, m0[k])) and _num(v) is not None:
            out[f"material_price.{k}"] = float(v)
    return out


_WHAT = {
    "labor_rate": lambda v: f"${v:g}/h labor rate",
    "margin": lambda v: f"margin {v * 100:g}%",
    "overhead": lambda v: f"overhead {v * 100:g}%",
    "utilization": lambda v: f"utilization {v * 100:g}%",
    "perishable_frac": lambda v: f"tools and coolant at {v * 100:g}% of machine",
    "stock_allowance": lambda v: f"stock allowance ×{v:g}",
    "daily_machine_hours": lambda v: f"{v:g} machine hours a day",
    "machine_labor_frac": lambda v: f"operator share {v * 100:g}%",
    "machine_capital_frac": lambda v: f"machine capital share {v * 100:g}%",
}
_FIELD_WHAT = {
    "machine_rate": lambda v: f"${v:g}/h machine rate",
    "setup_hr": lambda v: f"{v:g} h setup",
    "nre_hr": lambda v: f"{v:g} h programming",
    "fai_hr": lambda v: f"{v:g} h first article",
    "inspect_hr_part": lambda v: f"{v:g} h inspection a part",
    "post_hr": lambda v: f"{v:g} h post-process",
    "post_hr_part": lambda v: f"{v:g} h post-process a part",
    "post_hr_build": lambda v: f"{v:g} h post-process a build",
    "min_charge": lambda v: f"${v:g} order minimum",
    "tooling": lambda v: f"${v:,.0f} tooling",
    "finish_per_part": lambda v: f"${v:g} finishing a part",
    "finish_lot_charge": lambda v: f"${v:g} finishing a lot",
}


def what(key: str, value: float) -> str:
    """One changed key in words: 'labor_rate' 58 -> '$58/h labor rate'."""
    if key in _WHAT:
        return _WHAT[key](value)
    field, _, rest = key.partition(".")
    if field == "material_price":
        return f"${value:g}/kg {rest.lstrip('@')}"
    if field in _FIELD_WHAT:
        return _FIELD_WHAT[field](value)
    return f"{key.replace('_', ' ')} {value:g}"


def _line_keys(name: str, process: Optional[str], material: Optional[str], material_class: Optional[str]) -> list[str]:
    out = []
    for k in LINE_KEYS.get(name, ()):
        if "{P}" in k and not process:
            continue
        out.append(k.replace("{P}", process or "").replace("{M}", material or "").replace("{C}", material_class or ""))
    return out


def apply_rate_card(result: dict, version: Optional[int], payload: Optional[dict]) -> dict:
    """Tag a fresh result's lines and assumptions that use the org's own published
    rates, and stamp the card version on the result. A result priced at the
    typical table (``version`` None) comes back unchanged. Never changes a number."""
    if not isinstance(result, dict) or version is None:
        return result
    changed = changed_keys(payload)
    out = copy.deepcopy(result)
    out["rate_card"] = {
        "version": int(version),
        "changed": {k: changed[k] for k in sorted(changed)},
        "source": f"your published rate card v{int(version)}",
    }
    if not changed:
        return out
    tag = f"from your rates v{int(version)}"
    material_class = out.get("material_class")
    for est in out.get("estimates") or []:
        if not isinstance(est, dict):
            continue
        process = _pt_name(est.get("process"))
        material = est.get("material")
        for d in est.get("drivers") or []:
            if not isinstance(d, dict) or d.get("unit") != "$":
                continue
            if d.get("provenance") not in (None, "DEFAULT"):
                continue  # the user's or a shop profile's value for this quote wins
            used = [k for k in _line_keys(d.get("name") or "", process, material, material_class) if k in changed]
            if not used:
                continue
            d["provenance"] = "SHOP"
            d["rate_card"] = int(version)
            d["source"] = f"{d.get('source') or ''}; {', '.join(what(k, changed[k]) for k in used)} {tag}".lstrip("; ")
    for a in out.get("assumptions") or []:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        if name in GLOBAL_ASSUMPTIONS and name in changed and a.get("provenance") in (None, "DEFAULT"):
            a["provenance"] = "SHOP"
            a["rate_card"] = int(version)
            a["source"] = f"{a.get('source') or ''}; {what(name, changed[name])} {tag}".lstrip("; ")
    return out


# ---------------------------------------------------------------------------
# Which card a saved record was priced at, and which is in effect now
# ---------------------------------------------------------------------------


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if not isinstance(dt, datetime):
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def in_effect(rows: Iterable[Any], at: datetime) -> int:
    """The version in effect at ``at`` over the org's card timeline (published and
    since-archived cards, which were in effect for their window); 0 = the typical table."""
    at = _aware(at)
    best = 0
    for r in rows:
        if getattr(r, "status", None) not in ("published", "archived"):
            continue
        ef, et = _aware(getattr(r, "effective_from", None)), _aware(getattr(r, "effective_to", None))
        if ef is None or at is None or ef > at or (et is not None and et <= at):
            continue
        best = max(best, int(getattr(r, "version", 0) or 0))
    return best


def priced_version(result_json: Any, created_at: Optional[datetime], rows: Iterable[Any]) -> int:
    """The card a record was priced at: its own stamp, else the card in effect when it was made."""
    stamp = (result_json or {}).get("rate_card") if isinstance(result_json, dict) else None
    if isinstance(stamp, dict) and isinstance(stamp.get("version"), int):
        return int(stamp["version"])
    if created_at is None:
        return 0
    return in_effect(rows, created_at)


def basis(result_json: Any, created_at: Optional[datetime], rows: list, *, enabled: bool,
          now: Optional[datetime] = None) -> dict:
    """``{"priced": 0, "current": 1, "out_of_date": True, "text": "Priced at rates v0; your rates are v1."}``.

    ``enabled`` is the rate-library flag: with it off the engine prices every check
    at the typical table, so nothing is out of date by rates."""
    now = now or datetime.now(timezone.utc)
    priced = priced_version(result_json, created_at, rows)
    current = in_effect(rows, now) if enabled else 0
    out_of_date = enabled and priced != current
    return {
        "priced": priced,
        "current": current,
        "out_of_date": out_of_date,
        "text": (f"Priced at rates v{priced}; your rates are v{current}." if out_of_date
                 else f"Priced at your rates v{priced}." if priced else "Priced at typical rates (v0)."),
    }


async def org_rate_rows(session, org_id: Optional[str]) -> list:
    """The org's rate-card timeline (published and archived cards), one query."""
    if not org_id:
        return []
    from sqlalchemy import select

    from src.db.models import RateCardVersion

    return list((await session.execute(
        select(RateCardVersion.version, RateCardVersion.status, RateCardVersion.effective_from,
               RateCardVersion.effective_to)
        .where(RateCardVersion.org_id == org_id, RateCardVersion.status.in_(("published", "archived")))
    )).all())


async def basis_for(session, org_id: Optional[str], decisions: Iterable[Any]) -> dict:
    """``{decision ulid: basis}`` for saved records of one org (one read for all of them)."""
    from src.services.rate_library_service import rate_library_enabled

    ds = list(decisions)
    rows = await org_rate_rows(session, org_id) if ds else []
    enabled = rate_library_enabled()
    out = {}
    for d in ds:
        rj = d.__dict__.get("result_json") if hasattr(d, "__dict__") else None
        out[d.ulid] = basis(rj, getattr(d, "created_at", None), rows, enabled=enabled)
    return out
