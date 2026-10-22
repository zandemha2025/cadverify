"""Outbound copies: what a record may carry outside the organization.

A record leaves the organization two ways, and every one of them is built here:

* public share links: ``GET /s/{id}`` (a check) and ``GET /s/cost/{id}`` (a
  should-cost);
* RFQ packages a buyer downloads and hands to a supplier: the package view,
  ``package_manifest.json``, ``line-items.csv``, ``supplier-brief.md``/``.pdf``,
  ``cost-decisions.json`` and, per record, ``cost-decision.json``,
  ``cost-drivers.csv``, ``declared-part.json``, ``part-context.json`` and
  ``should-cost-report.pdf``.

This is an allowlist. Each function below names the fields a copy keeps; a field,
driver, line item or assumption it doesn't name is left out, so a new field added
to a record stays inside the organization until someone puts it on this list.

May leave
  * the part: file name and type, label, geometry measured from the file, unit
    warnings, the geometric route reading;
  * findings: DFM verdicts, issues, blockers and fixes;
  * the should-cost on outside terms: per process, material and quantity, the
    price lines, the stated band, lead time, the engine's pick and crossover;
  * what the buyer chose to send: quantities, the declared part (number,
    description, material class, volumes, program), service conditions declared
    on the part, the route they chose to buy outside, their note to the supplier.

Never leaves
  * the shop's machines: names, counts, envelopes, fit verdicts (the
    ``verification`` block);
  * its rates and terms: a value the shop typed or bound (USER/SHOP provenance)
    is hidden, and any text quoting a $/hr or $/kg figure that isn't on
    ScaleCAD's generic rate card, a markup, an overhead or a utilization is
    withheld whole;
  * what it owns and chooses: a route priced on a machine of its own (price,
    lead time, envelope and all), the in-house/outside options and their rule,
    the recorded outcome and its note, approvers;
  * its calibration and actuals: calibrated prices go back to the engine's
    numbers before calibration, and a band measured on its own ground truth
    becomes the engine's stated band;
  * other parts (identity matches), internal ids and hashes, user ids.

Free text (driver sources, notes, assumptions, decision note, band basis,
findings) is cut of the clauses that name those things and then checked again:
any text that still names one of the shop's machines, says owned / in-house /
marginal / calibration / actuals, or quotes a private rate is withheld whole
(a list drops it; a field reads ``WITHHELD``). That check fails closed.

The functions are pure and idempotent: an outbound copy run through again comes
back unchanged, so packages saved before this module are cleaned on every read.
"""
from __future__ import annotations

import copy
import math
import re
from functools import lru_cache
from typing import Any, Iterable, Optional

# ── words a copy shows in place of what it leaves out ─────────────────────────
HIDDEN_INPUT = "Set by the sender's shop. Not shown outside it."
WITHHELD = "Not shown outside the sender's shop."

_PRIVATE_PROVENANCE = frozenset({"USER", "SHOP"})
# USER declarations about the part itself (what it is, how many cavities, how
# tight), not about the shop. They travel with their value and source.
PART_DECLARATIONS = frozenset({
    "material_class", "tolerance_class", "source_units", "n_cavities", "complexity",
})

# ── the allowlists ────────────────────────────────────────────────────────────
DRIVER_NAMES = frozenset({
    "material_cost", "support_material", "parts_per_build", "machine_cost",
    "machine_region_split", "cycle_time", "labor_cost", "learning_curve",
    "setup_cost", "nre_cost", "inspection_cost", "consumables_cost",
    "finishing_cost", "plate_removal_cost", "support_removal_cost",
    "stress_relief_cost", "sinter_cost", "finish_machining", "tolerance_class",
    "tooling_cost", "region_split", "min_charge_floor",
})
LINE_ITEMS = frozenset({
    "amortized_fixed", "material", "machine", "labor", "nre", "inspection",
    "consumables", "finishing", "tolerance", "plate_removal", "support_removal",
    "stress_relief", "sinter", "finish_machining", "min_charge_floor",
})
ASSUMPTION_NAMES = frozenset({
    "labor_rate", "region_labor", "region_material", "region_tooling", "margin",
    "overhead", "utilization", "stock_allowance", "machine_labor_frac",
    "perishable_frac", "daily_machine_hours", "n_cavities", "complexity",
    "material_class", "source_units", "tolerance_class",
})
_GEOMETRY_KEYS = ("volume_cm3", "surface_area_cm2", "bbox_mm", "watertight", "face_count")
_CHECK_GEOMETRY_KEYS = (
    "vertices", "faces", "volume_mm3", "surface_area_mm2", "bounding_box_mm",
    "is_watertight", "is_manifold", "center_of_mass", "units", "unit_detection",
)
_ISSUE_KEYS = (
    "code", "severity", "message", "fix_suggestion", "process", "affected_face_count",
    "affected_faces_sample", "affected_faces_truncated", "region_center",
    "measured_value", "required_value", "measurement_unit", "scope",
)
_ISSUE_TEXT = ("message", "fix_suggestion")
_CITATION_KEYS = ("standard", "clause", "text", "rule_id")
_FIX_KEYS = ("code", "severity", "message", "process", "fix", "measured_value",
             "required_value", "measurement_unit")
_CONFIDENCE_KEYS = ("low_usd", "high_usd", "point_usd", "level", "method", "validated",
                    "n_samples", "half_width_pct", "basis", "label")
_REC_KEYS = ("process", "material", "unit_cost_usd", "dfm_ready", "dfm_verdict",
             "lead_low_days", "lead_high_days")
_REDESIGN_KEYS = ("process", "material", "unit_cost_usd", "caveat")
_ROUTING_KEYS = ("archetype", "recommended_process", "eval_family", "material_hint",
                 "confidence", "alternatives", "drivers")
_FEASIBILITY_KEYS = ("process", "verdict", "score", "costed")
_DECLARED_PART_KEYS = ("part_id", "description", "material_class", "quantity",
                       "annual_volume", "program", "parent_assembly", "units_per_parent")
_PART_CONTEXT_KEYS = ("program", "parent_assembly", "units_per_parent", "annual_volume",
                      "provenance")
_SERVICE_ENV_KEYS = ("max_temp_c", "min_temp_c", "pressure_bar", "corrosive",
                     "sour_service", "medium", "standard")
_RAW_CAD_KEYS = ("included", "reason", "filename", "bytes")

# Verdicts that mean a machine the shop owns makes the route.
_IN_HOUSE_VERDICTS = frozenset({"makeable_in_house", "makeable_with_secondary_op"})
_MAKE_FAMILIES = frozenset({
    "additive", "subtractive", "fabrication", "edm", "metal_powder_bed", "binder_jet", "ded",
})
_TOOLING_FAMILIES = frozenset({"formative", "casting", "forging"})

# ── free text ─────────────────────────────────────────────────────────────────
# Clauses the engine writes about the shop's own data, cut before the check.
_CLAUSES = (
    re.compile(r"\s*\[shop: [^\]]*\]"),
    re.compile(r"\s*× [\d.]+ from your actuals on [^()]*\([^)]*\)"),
    re.compile(r";\s*moved with your calibration \([^)]*\)"),
    re.compile(r"\s*Owned machines: .*$", re.S),
)
# What a text must not say once those clauses are gone.
_PRIVATE_WORDS = re.compile(
    r"\bown(?:s|ed)?\b|in[- ]house|marginal|calibrat|\bactuals\b|your actual|\bsunk\b"
    r"|fitted machine|declared envelope|envelope of '|machine '|\[shop:|\bshop '"
    r"|your (?:machine|shop|building|printer|rate|queue)"
    r"|×\s?\d+(?:\.\d+)? (?:markup|overhead)\b|÷\s?\d+(?:\.\d+)? utilization",
    re.I,
)
# ScaleCAD's own wording that happens to use one of those words about the
# engine, never about a shop. Ignored by the check (and by the tests' byte scan).
ENGINE_PHRASES = (
    "pick on intent, not just the marginal $.",
    "slicer-calibrated",
    "calibrated against PrusaSlicer",
)
_RATE_FIGURE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?/\s?(?:hr|h|hour|kg)\b", re.I)


@lru_cache(maxsize=1)
def _generic_rates() -> frozenset:
    """Every number on ScaleCAD's generic rate card and material catalog: the only
    $/hr and $/kg figures a copy may quote."""
    from src.costing.rates import RATE_CARD_V0
    from src.profiles.database import MATERIALS

    found: set = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
        elif isinstance(node, (int, float)) and not isinstance(node, bool) and math.isfinite(node):
            found.add(round(float(node), 6))

    walk(RATE_CARD_V0)
    for m in MATERIALS:
        walk(getattr(m, "cost_per_kg", None))
        walk(dict(getattr(m, "cost_per_kg_by_form", None) or {}))
    return frozenset(found)


def _quotes_private_rate(text: str) -> bool:
    generic = _generic_rates()
    for m in _RATE_FIGURE.finditer(text):
        try:
            value = round(float(m.group(1).replace(",", "")), 6)
        except ValueError:
            return True
        if value not in generic:
            return True
    return False


class _Terms:
    """The shop's private names for one record: its machines (from the record and
    the organization's inventory). Matched case-insensitively in every text."""

    def __init__(self, names: Iterable[str]):
        clean = {n.strip() for n in names if isinstance(n, str) and len(n.strip()) >= 3}
        self.names = tuple(sorted(clean, key=len, reverse=True))
        self._lower = tuple(n.lower() for n in self.names)

    def found_in(self, text: str) -> bool:
        low = text.lower()
        return any(n in low for n in self._lower)


def private_names(result_json: Any) -> set[str]:
    """Machine names a saved record carries (verification, options, picks, lead
    times), so a copy can keep them out of every text."""
    out: set[str] = set()
    r = result_json if isinstance(result_json, dict) else {}
    v = r.get("verification") if isinstance(r.get("verification"), dict) else {}
    out.add(v.get("best_machine"))
    res = v.get("resource") if isinstance(v.get("resource"), dict) else {}
    out.add(res.get("machine"))
    for info in (v.get("per_route") or {}).values():
        if isinstance(info, dict):
            out.add(info.get("best_machine"))
    dec = r.get("decision") if isinstance(r.get("decision"), dict) else {}
    for opt in (dec.get("options") or {}).values():
        if isinstance(opt, dict) and isinstance(opt.get("in_house"), dict):
            out.add(opt["in_house"].get("machine"))
    for rec in (dec.get("recommendation") or {}).values():
        if isinstance(rec, dict):
            out.add(rec.get("machine"))
    for e in r.get("estimates") or []:
        cap = ((e or {}).get("lead_time") or {}).get("capacity") if isinstance(e, dict) else None
        if isinstance(cap, dict):
            out.add(cap.get("machine"))
    return {n for n in out if isinstance(n, str) and n.strip()}


def text(value: Any, terms: _Terms | None = None) -> Optional[str]:
    """One free text as it may leave, or None when it may not.

    Known clauses about the shop are cut; whatever still names a machine of the
    shop, its ownership, calibration or actuals, or quotes a rate that isn't
    ScaleCAD's generic one, is withheld whole.
    """
    if not isinstance(value, str):
        return None
    out = value
    for clause in _CLAUSES:
        out = clause.sub("", out)
    scan = out
    for phrase in ENGINE_PHRASES:
        scan = scan.replace(phrase, "")
    if _PRIVATE_WORDS.search(scan) or _quotes_private_rate(scan):
        return None
    if terms is not None and terms.found_in(scan):
        return None
    return out


def _field_text(value: Any, terms: _Terms) -> Any:
    if value is None:
        return None
    t = text(value, terms)
    return WITHHELD if t is None else t


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _int(q: Any) -> Any:
    try:
        return int(q)
    except (TypeError, ValueError):
        return q


def _plain(node: Any, terms: _Terms, depth: int = 0) -> Any:
    """A JSON value made of plain facts (numbers, flags, short words): strings are
    checked like any text, nothing nests deeper than a few levels."""
    if depth > 4:
        return None
    if isinstance(node, str):
        return text(node, terms)
    if isinstance(node, bool) or node is None:
        return node
    if isinstance(node, (int, float)):
        return node if math.isfinite(node) else None
    if isinstance(node, (list, tuple)):
        return [_plain(v, terms, depth + 1) for v in node]
    if isinstance(node, dict):
        return {k: _plain(v, terms, depth + 1) for k, v in node.items() if isinstance(k, str)}
    return None


def _pick(src: Any, keys: Iterable[str]) -> dict:
    src = src if isinstance(src, dict) else {}
    return {k: src[k] for k in keys if k in src}


# ── findings (shared by checks and should-costs) ──────────────────────────────
def issue(node: Any, terms: _Terms) -> Optional[dict]:
    if not isinstance(node, dict):
        return None
    out = _pick(node, _ISSUE_KEYS)
    for k in _ISSUE_TEXT:
        if k in out:
            out[k] = _field_text(out[k], terms)
    for k in ("affected_faces_sample", "region_center"):
        if k in out:
            out[k] = _plain(out[k], terms)
    if isinstance(node.get("citation"), dict):
        cit = _pick(node["citation"], _CITATION_KEYS)
        if "text" in cit:
            cit["text"] = _field_text(cit["text"], terms)
        out["citation"] = cit
    return out


def _issues(nodes: Any, terms: _Terms) -> list:
    return [i for i in (issue(n, terms) for n in (nodes or [])) if i is not None]


def _texts(nodes: Any, terms: _Terms) -> list:
    return [t for t in (text(n, terms) for n in (nodes or [])) if t is not None]


# ── a check (DFM analysis) ────────────────────────────────────────────────────
def check_record(result_json: Any, *, terms: Iterable[str] = ()) -> dict:
    """The parts of a saved check that may leave: geometry, findings, verdicts."""
    r = result_json if isinstance(result_json, dict) else {}
    t = _Terms(set(terms) | private_names(r))
    scores = []
    for ps in r.get("process_scores") or []:
        if not isinstance(ps, dict):
            continue
        row = _pick(ps, ("process", "score", "verdict", "recommended_material",
                         "recommended_machine", "estimated_cost_factor", "standards"))
        for k in ("recommended_material", "recommended_machine"):
            if k in row:
                row[k] = text(row[k], t)
        if "standards" in row:
            row["standards"] = _texts(row["standards"], t)
        row["issues"] = _issues(ps.get("issues"), t)
        scores.append(row)
    fixes = []
    for fx in r.get("priority_fixes") or []:
        if isinstance(fx, dict):
            row = _pick(fx, _FIX_KEYS)
            for k in ("message", "fix"):
                if k in row:
                    row[k] = _field_text(row[k], t)
            fixes.append(row)
    return {
        "process_scores": scores,
        "universal_issues": _issues(r.get("universal_issues"), t),
        "geometry": _plain(_pick(r.get("geometry"), _CHECK_GEOMETRY_KEYS), t),
        "best_process": r.get("best_process") if isinstance(r.get("best_process"), str) else None,
        "priority_fixes": fixes,
    }


# ── a should-cost (cost decision) ─────────────────────────────────────────────
def _priced_in_house(est: dict, in_house_routes: set) -> bool:
    if est.get("process") in in_house_routes or est.get("owned_in_house"):
        return True
    cap = (est.get("lead_time") or {}).get("capacity")
    if isinstance(cap, dict) and (cap.get("in_house") or cap.get("machine")):
        return True
    for d in est.get("drivers") or []:
        if isinstance(d, dict) and (d.get("name") == "owned_in_house"
                                    or "fitted machine" in str(d.get("source") or "")):
            return True
    return False


def _in_house_routes(r: dict) -> set:
    """Routes the shop makes on a machine of its own, by every mark the engine
    leaves: the §0 verdict, the decision's options and picks, the estimate flags."""
    out: set = set()
    v = r.get("verification") if isinstance(r.get("verification"), dict) else {}
    for pv, info in (v.get("per_route") or {}).items():
        if isinstance(info, dict) and info.get("verdict") in _IN_HOUSE_VERDICTS:
            out.add(pv)
    dec = r.get("decision") if isinstance(r.get("decision"), dict) else {}
    for opt in (dec.get("options") or {}).values():
        if isinstance(opt, dict) and isinstance(opt.get("in_house"), dict):
            out.add(opt["in_house"].get("process"))
    for rec in (dec.get("recommendation") or {}).values():
        if isinstance(rec, dict) and rec.get("in_house"):
            out.add(rec.get("process"))
    for e in r.get("estimates") or []:
        if isinstance(e, dict) and _priced_in_house(e, set()):
            out.add(e.get("process"))
    return {p for p in out if isinstance(p, str)}


def _uncalibrate(est: dict) -> Optional[dict]:
    """The estimate as the engine priced it, before the organization's calibration
    (``calibration_service.overlay``) moved it. None if it can't be put back."""
    cal = est.get("calibration")
    if cal is None:
        return est
    before = cal.get("before") if isinstance(cal, dict) else None
    unit = _num((before or {}).get("unit_cost_usd"))
    if unit is None:
        return None
    out = copy.deepcopy(est)
    out.pop("calibration", None)
    out["unit_cost_usd"] = round(unit, 2)
    drivers = [d for d in out.get("drivers") or [] if isinstance(d, dict)]
    machine = next((d for d in drivers if d.get("name") == "machine_cost"), None)
    cycle = next((d for d in drivers if d.get("name") == "cycle_time"), None)
    m_before = _num(before.get("machine_cost_usd"))
    if machine is not None and m_before is not None:
        m_after = _num(machine.get("value"))
        if m_after is not None and _num(out.get("variable_cost_usd")) is not None:
            out["variable_cost_usd"] = round(out["variable_cost_usd"] - (m_after - m_before), 2)
        machine["value"] = m_before
        items = out.get("line_items")
        if isinstance(items, dict) and "machine" in items:
            items["machine"] = m_before
    if cycle is not None and _num(before.get("cycle_time_hr")) is not None:
        cycle["value"] = before["cycle_time_hr"]
    conf = out.get("confidence")
    if isinstance(conf, dict):
        for k in ("low_usd", "high_usd", "point_usd"):
            if _num(before.get(k)) is not None:
                conf[k] = before[k]
    out["drivers"] = drivers
    return out


def _stated_band(est: dict) -> Optional[dict]:
    """The band a copy carries: the engine's stated assumption band. A band
    measured on the organization's own ground truth is its calibration, so it is
    replaced by the stated one around the same price."""
    conf = est.get("confidence")
    if not isinstance(conf, dict):
        return None
    if conf.get("method") == "assumption-band" and not conf.get("validated"):
        return _pick(conf, _CONFIDENCE_KEYS)
    unit = _num(est.get("unit_cost_usd"))
    band = _num(est.get("est_error_band_pct"))
    if unit is None or band is None:
        return None
    from src.costing.confidence import confidence_interval

    level = _num(conf.get("level")) or 0.80
    return confidence_interval(unit, assumption_band_pct=band, level=level).to_dict()


def _driver(d: Any, terms: _Terms) -> Optional[dict]:
    if not isinstance(d, dict) or d.get("name") not in DRIVER_NAMES:
        return None
    out = _pick(d, ("name", "value", "unit", "provenance", "source", "error_band_pct"))
    if out.get("provenance") in _PRIVATE_PROVENANCE and out.get("name") not in PART_DECLARATIONS:
        # A "$" driver is a price line of the result; anything else (an hourly
        # rate, a count, hours on the shop's machine) is the shop's own input.
        if out.get("unit") != "$":
            out["value"] = None
        out["source"] = HIDDEN_INPUT
    elif "source" in out:
        out["source"] = _field_text(out["source"], terms)
    return out


def _capacity(cap: Any, terms: _Terms) -> Optional[dict]:
    if not isinstance(cap, dict):
        return None
    out = _pick(cap, ("n_machines", "machine_hours_per_day", "provenance", "basis"))
    if out.get("provenance") in _PRIVATE_PROVENANCE:
        out["n_machines"] = None
        out["machine_hours_per_day"] = None
        if "basis" in out:
            out["basis"] = HIDDEN_INPUT
    elif "basis" in out:
        out["basis"] = _field_text(out["basis"], terms)
    return out


def _estimate(e: dict, terms: _Terms) -> dict:
    out = _pick(e, ("process", "material", "quantity", "unit_cost_usd", "fixed_cost_usd",
                    "variable_cost_usd", "est_error_band_pct", "dfm_ready", "dfm_verdict",
                    "dfm_score", "environment_excluded"))
    conf = _stated_band(e)
    if conf is not None:
        conf["basis"] = _field_text(conf.get("basis"), terms)
        if conf.get("label"):
            conf["label"] = _field_text(conf["label"], terms)
        out["confidence"] = conf
    if "environment_exclusion_reason" in e:
        out["environment_exclusion_reason"] = _field_text(e["environment_exclusion_reason"], terms)
    out["dfm_blockers"] = [_field_text(b, terms) for b in e.get("dfm_blockers") or []]
    if "dfm_blocker_details" in e:
        out["dfm_blocker_details"] = _issues(e.get("dfm_blocker_details"), terms)
    items = e.get("line_items")
    if isinstance(items, dict):
        out["line_items"] = {k: v for k, v in items.items() if k in LINE_ITEMS}
    out["drivers"] = [d for d in (_driver(d, terms) for d in e.get("drivers") or []) if d]
    lt = e.get("lead_time")
    if isinstance(lt, dict):
        lead = _pick(lt, ("low_days", "high_days", "mid_days"))
        if isinstance(lt.get("components"), dict):
            lead["components"] = _plain(lt["components"], terms)
        lead["capacity"] = _capacity(lt.get("capacity"), terms)
        out["lead_time"] = lead
    return out


def _assumption(a: Any, terms: _Terms) -> Optional[dict]:
    if not isinstance(a, dict) or a.get("name") not in ASSUMPTION_NAMES:
        return None
    out = _pick(a, ("name", "value", "unit", "provenance", "source"))
    if out.get("provenance") in _PRIVATE_PROVENANCE and out.get("name") not in PART_DECLARATIONS:
        out["value"] = None
        out["source"] = HIDDEN_INPUT
    elif out.get("name") not in PART_DECLARATIONS and _off_card(out):
        # Tagged DEFAULT but not ScaleCAD's default: the organization's governed
        # rate library. Its rates and terms are its own.
        out["value"] = None
        out["source"] = HIDDEN_INPUT
    elif "source" in out:
        out["source"] = _field_text(out["source"], terms)
    return out


def _off_card(a: dict) -> bool:
    from src.costing.rates import RATE_CARD_V0

    generic = (RATE_CARD_V0.get("global") or {}).get(a.get("name"))
    value = _num(a.get("value"))
    if value is None or _num(generic) is None:
        return False
    return round(value, 6) != round(float(generic), 6)


def _family(pv: Any) -> Optional[str]:
    from src.analysis.models import ProcessType
    from src.costing.rates import process_family

    try:
        return process_family(ProcessType(pv))
    except Exception:
        return None


def _rec_from(est: dict) -> dict:
    lead = est.get("lead_time") or {}
    return {
        "process": est.get("process"),
        "material": est.get("material"),
        "unit_cost_usd": est.get("unit_cost_usd"),
        "dfm_ready": est.get("dfm_ready"),
        "dfm_verdict": est.get("dfm_verdict"),
        "lead_low_days": lead.get("low_days"),
        "lead_high_days": lead.get("high_days"),
    }


def _cheapest(kept: list, q: Any, families: frozenset) -> Optional[dict]:
    """The engine's own tier-1 rule over the routes a copy keeps: the cheapest
    DFM-ready route of these families at the quantity, else the cheapest of them."""
    at = [e for e in kept if e.get("quantity") == _int(q) and not e.get("environment_excluded")
          and _family(e.get("process")) in families and _num(e.get("unit_cost_usd")) is not None]
    ready = [e for e in at if e.get("dfm_ready")]
    pool = ready or at
    return min(pool, key=lambda e: e["unit_cost_usd"]) if pool else None


def _find(kept: list, process: Any, q: Any, material: Any) -> Optional[dict]:
    rows = [e for e in kept if e.get("process") == process and e.get("quantity") == _int(q)]
    exact = [e for e in rows if e.get("material") == material]
    rows = exact or rows
    return rows[0] if len(rows) == 1 else None


def _decision(dec: Any, kept: list, dropped: set, calibrated: set, terms: _Terms) -> Optional[dict]:
    """The engine's decision over the routes the copy keeps.

    Nothing priced in-house: the engine's picks, prices and crossover, minus the
    in-house options and rule. A route priced on the shop's own machine is not in
    the copy, so a pick that was in-house becomes the engine's own rule (cheapest
    eligible route) over the routes the copy shows, and a crossover computed
    against the in-house price is not shown.
    """
    if not isinstance(dec, dict):
        return None
    rec_in = dec.get("recommendation") if isinstance(dec.get("recommendation"), dict) else {}
    redes_in = dec.get("if_redesigned") if isinstance(dec.get("if_redesigned"), dict) else {}
    rec_out: dict = {}
    redes_out: dict = {}
    repicked = False
    for q, r in rec_in.items():
        if not isinstance(r, dict):
            continue
        est = None if r.get("process") in dropped else _find(kept, r.get("process"), q, r.get("material"))
        if est is not None:
            row = _pick(r, _REC_KEYS)
            if (est.get("process"), est.get("quantity")) in calibrated:
                row["unit_cost_usd"] = est.get("unit_cost_usd")
        else:
            pick = _cheapest(kept, q, _MAKE_FAMILIES)
            repicked = True
            if pick is None:
                continue
            row = _rec_from(pick)
        rec_out[q] = row
        alt = redes_in.get(q)
        if (isinstance(alt, dict) and alt.get("process") not in dropped
                and _num(alt.get("unit_cost_usd")) is not None
                and _num(row.get("unit_cost_usd")) is not None
                and alt["unit_cost_usd"] < row["unit_cost_usd"]):
            redes_out[q] = _pick(alt, _REDESIGN_KEYS)
            if "caveat" in redes_out[q]:
                redes_out[q]["caveat"] = text(redes_out[q]["caveat"], terms)
        else:
            redes_out[q] = None
    for q in redes_in:
        redes_out.setdefault(q, None)
    if rec_in and not rec_out:
        # Every pick was on the shop's own machine and nothing outside is priced.
        return None
    out = _pick(dec, ("make_now_process", "make_now_material", "tooling_process",
                      "tooling_dfm_ready", "crossover_qty"))
    if repicked or dropped:
        if rec_out:
            q_lo = min(rec_out, key=lambda k: _int(k) if isinstance(_int(k), int) else math.inf)
            out["make_now_process"] = rec_out[q_lo].get("process")
            out["make_now_material"] = rec_out[q_lo].get("material")
        elif out.get("make_now_process") in dropped:
            out["make_now_process"] = out["make_now_material"] = None
        out["crossover_qty"] = None
        if out.get("tooling_process") in dropped:
            quantities = [_int(k) for k in rec_in if isinstance(_int(k), int)]
            tool = _cheapest(kept, max(quantities), _TOOLING_FAMILIES) if quantities else None
            out["tooling_process"] = tool.get("process") if tool else None
            out["tooling_dfm_ready"] = bool(tool.get("dfm_ready")) if tool else True
        out["note"] = None
    else:
        out["note"] = text(dec.get("note"), terms) if dec.get("note") is not None else None
    out["recommendation"] = rec_out
    out["if_redesigned"] = redes_out
    return out


def _routing(node: Any, terms: _Terms) -> Optional[dict]:
    if not isinstance(node, dict):
        return None
    out = _pick(node, _ROUTING_KEYS)
    if "alternatives" in out:
        out["alternatives"] = [a for a in out["alternatives"] or [] if isinstance(a, str)]
    if "drivers" in out:
        out["drivers"] = _plain(out["drivers"], terms)
    if "reasoning" in node:
        out["reasoning"] = _field_text(node["reasoning"], terms)
    return out


def _names_route(note: str, routes: set) -> bool:
    return any(re.search(rf"\b{re.escape(p)}\b", note) for p in routes)


def cost_record(result_json: Any, *, terms: Iterable[str] = ()) -> dict:
    """The parts of a saved should-cost that may leave (see the module doc)."""
    r = result_json if isinstance(result_json, dict) else {}
    t = _Terms(set(terms) | private_names(r))
    dropped = _in_house_routes(r)
    kept: list = []
    calibrated: set = set()
    for e in r.get("estimates") or []:
        if not isinstance(e, dict) or _priced_in_house(e, dropped):
            continue
        plain = _uncalibrate(e)
        if plain is None:
            continue
        if e.get("calibration") is not None:
            calibrated.add((e.get("process"), e.get("quantity")))
        kept.append(_estimate(plain, t))
    notes = _texts(r.get("notes"), t)
    if dropped:
        # A note about a route the copy leaves out would describe what isn't there.
        notes = [n for n in notes if not _names_route(n, dropped)]
    out = {
        "filename": r.get("filename") if isinstance(r.get("filename"), str) else None,
        "status": r.get("status") if isinstance(r.get("status"), str) else None,
        "reason": text(r.get("reason"), t) if r.get("reason") is not None else None,
        "geometry": _plain(_pick(r.get("geometry"), _GEOMETRY_KEYS), t),
        "material_class": r.get("material_class") if isinstance(r.get("material_class"), str) else None,
        "quantities": [q for q in r.get("quantities") or [] if isinstance(q, int)],
        "estimates": kept,
        "engine_feasibility": [
            {**_pick(f, _FEASIBILITY_KEYS), "blockers": _texts(f.get("blockers"), t)}
            if "blockers" in f else _pick(f, _FEASIBILITY_KEYS)
            for f in r.get("engine_feasibility") or [] if isinstance(f, dict)
        ],
        "routing": _routing(r.get("routing"), t),
        "notes": notes,
        "assumptions": [a for a in (_assumption(a, t) for a in r.get("assumptions") or []) if a],
        "decision": _decision(r.get("decision"), kept, dropped, calibrated, t),
    }
    if r.get("unit_warnings"):
        out["unit_warnings"] = [w for w in (_plain(w, t) for w in r["unit_warnings"]) if w]
    return out


def unvalidated(cost: dict) -> bool:
    """Whether a copy's should-cost carries an unvalidated band (every stated band is)."""
    for e in (cost or {}).get("estimates") or []:
        if ((e or {}).get("confidence") or {}).get("validated") is not True:
            return True
    return False


# ── share links ───────────────────────────────────────────────────────────────
def _iso(dt: Any) -> Optional[str]:
    return dt.isoformat() if hasattr(dt, "isoformat") else None


def cost_share(d: Any, *, terms: Iterable[str] = ()) -> dict:
    """``GET /s/cost/{id}``: the should-cost and the file it is for. No owner,
    ids, hashes, governance or anything the module doc keeps inside."""
    cost = cost_record(getattr(d, "result_json", None) or {}, terms=terms)
    dec = cost.get("decision") or {}
    return {
        "filename": getattr(d, "filename", None),
        "file_type": getattr(d, "file_type", None),
        "label": getattr(d, "label", None),
        "created_at": _iso(getattr(d, "created_at", None)),
        "make_now_process": dec.get("make_now_process"),
        "crossover_qty": dec.get("crossover_qty"),
        "quantities": list(getattr(d, "quantities", None) or cost["quantities"]),
        "geometry": cost["geometry"],
        "material_class": cost["material_class"],
        "routing": cost["routing"],
        "estimates": cost["estimates"],
        "decision": cost["decision"],
        "assumptions": cost["assumptions"],
        "engine_feasibility": cost["engine_feasibility"],
        "notes": cost["notes"],
        "status": cost["status"],
    }


def check_share(a: Any, *, terms: Iterable[str] = ()) -> dict:
    """``GET /s/{id}``: the check of the file. No prices, machines or records."""
    return {
        "filename": getattr(a, "filename", None),
        "file_type": getattr(a, "file_type", None),
        "verdict": getattr(a, "verdict", None),
        "face_count": getattr(a, "face_count", None),
        "duration_ms": getattr(a, "duration_ms", None),
        "created_at": _iso(getattr(a, "created_at", None)),
        **check_record(getattr(a, "result_json", None) or {}, terms=terms),
    }


# ── RFQ packages ──────────────────────────────────────────────────────────────
def requested_route(user_disposition: Any, basis: Any) -> Optional[dict]:
    """The route the buyer chose to buy outside ("Make outside" with its process,
    material and quantity): the request a supplier quotes. Any other outcome is
    the shop's own choice and stays inside."""
    if user_disposition != "outside" or not isinstance(basis, dict):
        return None
    out = _pick(basis, ("process", "material", "quantity"))
    return out if out.get("process") else None


def rfq_item(item: Any, *, terms: Iterable[str] = ()) -> dict:
    """One record in an RFQ package, as the supplier receives it."""
    item = item if isinstance(item, dict) else {}
    meta = item.get("decision") if isinstance(item.get("decision"), dict) else {}
    cost = cost_record(item.get("cost_decision") or {}, terms=terms)
    dec = cost.get("decision") or {}
    requested = meta.get("requested") if "requested" in meta else requested_route(
        meta.get("user_disposition"), meta.get("disposition_basis"))
    out_meta = {
        **_pick(meta, ("id", "filename", "file_type", "label", "engine_version", "created_at",
                       "quantities", "approval_status")),
        "is_stale": bool(meta.get("is_stale")),
        "unvalidated_confidence": unvalidated(cost),
        "make_now_process": dec.get("make_now_process"),
        "crossover_qty": dec.get("crossover_qty"),
        "requested": requested_route("outside", requested) if isinstance(requested, dict) else None,
    }
    out: dict = {"decision": out_meta, "cost_decision": cost}
    declared = item.get("declared_part")
    if isinstance(declared, dict):
        part = _pick(declared.get("part"), _DECLARED_PART_KEYS)
        for k in ("description", "program", "parent_assembly"):
            if k in part and part[k] is not None:
                part[k] = _field_text(part[k], _Terms(terms))
        out["declared_part"] = {"match": declared.get("match"), "part": part}
    else:
        out["declared_part"] = None
    ctx = item.get("part_context")
    if isinstance(ctx, dict):
        c = _pick(ctx, _PART_CONTEXT_KEYS)
        env = ctx.get("service_environment")
        if isinstance(env, dict):
            c["service_environment"] = _plain(_pick(env, _SERVICE_ENV_KEYS), _Terms(terms))
        out["part_context"] = c
    else:
        out["part_context"] = None
    raw = item.get("raw_cad")
    out["raw_cad"] = _pick(raw, _RAW_CAD_KEYS) if isinstance(raw, dict) else None
    return out


def rfq_governance(meta: Any) -> dict:
    """What a supplier's copy says about a record's review: its status, whether it
    is out of date, and the route requested. Approvers, outcomes and notes stay."""
    meta = meta if isinstance(meta, dict) else {}
    return {
        "approval_status": meta.get("approval_status") or "unreviewed",
        "is_stale": bool(meta.get("is_stale")),
        "requested": meta.get("requested") if isinstance(meta.get("requested"), dict) else None,
    }


async def org_names(session: Any, org_id: Any) -> tuple[str, ...]:
    """The organization's machine names, to keep out of every text of a copy.
    Best effort: a failed read leaves the names the record itself carries."""
    from sqlalchemy.ext.asyncio import AsyncSession

    if not isinstance(session, AsyncSession) or not isinstance(org_id, str) or not org_id:
        return ()
    try:
        from sqlalchemy import select

        from src.db.models import MachineInstance

        # A savepoint, so a failed read never aborts the caller's transaction.
        async with session.begin_nested():
            rows = (await session.execute(
                select(MachineInstance.name).where(MachineInstance.org_id == org_id)
            )).scalars().all()
        return tuple(n for n in rows if isinstance(n, str))
    except Exception:
        return ()
