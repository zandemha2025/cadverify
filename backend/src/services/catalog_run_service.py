"""The catalog run: many parts checked against the org's machines, sorted.

A catalog run is a batch (``job_type='catalog'``) whose every item gets the
same two steps as a single-part check, in the worker: the DFM analysis
(``analysis_service.run_analysis``) and the cost decision with the org's
machines, materials and rates bound (``routes._run_cost_decision``, the live
POST /validate/cost path). Each part lands in one bucket of the org's
makeability lattice, read verbatim from the decision's verification block:

    in_house     make in-house on your machines   (makeable_in_house)
    outside      buy outside                      (makeable_outside)
    new_machine  needs a new machine              (needs_capability)
    cant_make    can't be made as drawn           (not_makeable, geometry_invalid)

plus the honest remainders: ``not_sorted`` (checked, no machine verdict, e.g.
no machines declared), ``not_checked`` (the file couldn't be checked) and
``checking`` (still running).

Each row leads with the resource cost (machine time, material, ownership) and
the price second, every figure copied from the engine's own estimate for the
route the bucket names. Nothing is invented: a missing figure is ``None``.

Inputs: a ZIP of CAD files (the browser zips many files or a folder), and an
optional parts list (CSV or a BOM export) naming files with a quantity and a
material each. This module holds the pure parts of that (parsing, matching,
the quantity ladder, row derivation, totals, CSV) and the board read.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import and_, literal_column, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Analysis, Batch, BatchItem, CostDecision

MATERIAL_CLASSES = ("polymer", "aluminum", "steel", "stainless", "titanium")
MATERIAL_WORDS = {
    "polymer": "Plastic",
    "aluminum": "Aluminum",
    "steel": "Steel",
    "stainless": "Stainless steel",
    "titanium": "Titanium",
}
DEFAULT_RUN_QUANTITY = 100
MAX_QUANTITY = 10_000_000
# The cost engine's six-point quantity contract (routes._MAX_QTYS) and the
# ladder the single-part check uses (frontend lib/verify/run.ts QTY_LADDER).
QTY_LADDER = (1, 100, 1000, 2000, 5000, 10000)
MAX_PARTS_LIST_ROWS = 20_000

BUCKETS = ("in_house", "outside", "new_machine", "cant_make")
OTHER_BUCKETS = ("not_sorted", "not_checked", "checking")
_BUCKET_OF_VERDICT = {
    "makeable_in_house": "in_house",
    "makeable_with_secondary_op": "in_house",
    "makeable_outsource_only": "outside",
    "makeable_not_on_owned": "new_machine",
    "not_makeable": "cant_make",
    "environment_excluded": "cant_make",
}
GEOMETRY_INVALID_PREFIX = "GEOMETRY_INVALID: "


# ---------------------------------------------------------------------------
# Materials named in a parts list
# ---------------------------------------------------------------------------

# Words for each class, checked in order (stainless before steel).
_MATERIAL_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("titanium", re.compile(r"\b(ti|titanium|ti-?6al-?4v|ti6al4v|grade ?5|gr ?5)\b", re.I)),
    ("stainless", re.compile(r"\b(stainless|ss|sst|inox|30[0-9]l?|31[0-9]l?|17-?4|15-?5|13cr|duplex|super duplex|2205|2507|410|420|440c?|f6nm)\b", re.I)),
    ("aluminum", re.compile(r"\b(al|alu|alum|aluminum|aluminium|[1-7]0[0-9]{2}(-t[0-9]+)?|a356|alsi10mg|mic-?6)\b", re.I)),
    ("steel", re.compile(r"\b(steel|carbon steel|mild steel|tool steel|cs|a36|a105|a182|1018|1020|1045|4130|4140|4340|8620|d2|a2|o1|h13|cast iron|ductile iron|iron)\b", re.I)),
    ("polymer", re.compile(r"\b(plastic|polymer|pla|abs|petg|asa|nylon|pa6|pa11|pa12|pa66|pom|delrin|acetal|peek|pei|ultem|pc|polycarbonate|pp|polypropylene|pe|hdpe|uhmw|ptfe|teflon|tpu|resin|acrylic|pmma|pvc)\b", re.I)),
)
_UNPRICED = re.compile(r"\b(inconel|incoloy|hastelloy|nickel|monel|cobalt|cocr|stellite|copper|brass|bronze|zinc|zamak|magnesium|tungsten)\b", re.I)


def material_class_of(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """``(material_class, note)`` for a material as a parts list names it.

    An exact engine material name maps through the engine's own family table
    (``costing.rates.MATERIAL_FAMILY``); otherwise common words and grades map to
    one of the five priced classes. A family the cost engine doesn't price yet
    (nickel, copper, ...) or an unknown word returns ``None`` with a note, and
    the run's default material is used instead. Never guessed silently.
    """
    raw = (text or "").strip()
    if not raw:
        return None, None
    if raw.lower() in MATERIAL_CLASSES:
        return raw.lower(), None
    from src.costing.rates import MATERIAL_FAMILY

    for name, family in MATERIAL_FAMILY.items():
        if name.lower() == raw.lower():
            if family in MATERIAL_CLASSES:
                return family, None
            return None, f"{raw} isn't priced in a catalog run yet"
    if _UNPRICED.search(raw):
        return None, f"{raw} isn't priced in a catalog run yet"
    for cls, pattern in _MATERIAL_PATTERNS:
        if pattern.search(raw):
            return cls, None
    return None, f"{raw} isn't a material ScaleCAD recognises"


# ---------------------------------------------------------------------------
# Parts list (CSV or a BOM export)
# ---------------------------------------------------------------------------

_FILE_HEADERS = ("filename", "file", "file name", "file_name", "cad file", "cad_file", "cad", "model", "path", "document")
_QTY_HEADERS = ("quantity", "qty", "qty.", "count", "quantity per year", "annual quantity", "annual volume", "annual_volume", "volume", "units", "eau")
_MATERIAL_HEADERS = ("material", "material_class", "material class", "matl", "mat'l", "material spec", "spec")
_PART_HEADERS = ("part number", "part_number", "part no", "part no.", "part #", "pn", "p/n", "item number", "item", "part", "number")
_DESC_HEADERS = ("description", "desc", "name", "title")


def _header_index(headers: list[str], names: Iterable[str]) -> Optional[int]:
    norm = [re.sub(r"\s+", " ", (h or "").strip().lower()) for h in headers]
    for name in names:
        if name in norm:
            return norm.index(name)
    return None


def _parse_qty(raw: str, row_num: int) -> Optional[int]:
    s = (raw or "").strip().replace(",", "").replace("_", "")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        raise ValueError(f"Row {row_num}: quantity '{raw.strip()}' isn't a number")
    if v != int(v) or not (1 <= v <= MAX_QUANTITY):
        raise ValueError(f"Row {row_num}: quantity '{raw.strip()}' must be a whole number from 1 to {MAX_QUANTITY:,}")
    return int(v)


def parse_parts_list(text: str) -> list[dict]:
    """Rows of a parts list: ``file``, ``part_number``, ``quantity``, ``material``.

    Reads comma, semicolon or tab separated text with a header row, as most
    BOM and ERP exports are. A file column (or, failing that, a part-number
    column that matches file names) is required. Quantities must be whole
    numbers; materials are kept as written plus the class they map to.
    Raises ``ValueError`` naming the row for anything it can't read.
    """
    if text.startswith("﻿"):
        text = text[1:]
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError("The parts list is empty")
    fi = _header_index(headers, _FILE_HEADERS)
    pi = _header_index(headers, _PART_HEADERS)
    if fi is None and pi is None:
        raise ValueError("The parts list needs a column named filename (or file), or a part number column that matches file names")
    qi = _header_index(headers, _QTY_HEADERS)
    mi = _header_index(headers, _MATERIAL_HEADERS)
    di = _header_index(headers, _DESC_HEADERS)

    def cell(row: list[str], i: Optional[int]) -> str:
        return row[i].strip() if i is not None and i < len(row) and row[i] is not None else ""

    rows: list[dict] = []
    for row_num, row in enumerate(reader, start=2):
        if not any((c or "").strip() for c in row):
            continue
        if len(rows) >= MAX_PARTS_LIST_ROWS:
            raise ValueError(f"The parts list has more than {MAX_PARTS_LIST_ROWS:,} rows")
        file = cell(row, fi)
        part = cell(row, pi)
        if not file and not part:
            raise ValueError(f"Row {row_num}: no file name or part number")
        material = cell(row, mi) or None
        cls, note = material_class_of(material)
        rows.append({
            "row": row_num,
            "file": file or None,
            "part_number": part or None,
            "description": cell(row, di) or None,
            "quantity": _parse_qty(cell(row, qi), row_num),
            "material": material,
            "material_class": cls,
            "material_note": note,
        })
    return rows


def _keys(name: str) -> tuple[str, str]:
    base = os.path.basename((name or "").replace("\\", "/")).strip().lower()
    stem = os.path.splitext(base)[0]
    return base, stem


def match_parts_list(rows: list[dict], filenames: Iterable[str]) -> tuple[dict[str, dict], list[dict]]:
    """Match parts-list rows to the run's files.

    A row matches a file by its file column (full name, then the name without
    its extension), else by its part number against the file name without its
    extension, all ignoring case and folders. Returns ``(by_filename, unmatched)``:
    the row meta per run file, and the rows that name no file in the run.
    """
    files = list(filenames)
    by_base: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for f in files:
        base, stem = _keys(f)
        by_base.setdefault(base, f)
        by_stem.setdefault(stem, f)
    out: dict[str, dict] = {}
    unmatched: list[dict] = []
    for r in rows:
        hit = None
        if r.get("file"):
            base, stem = _keys(r["file"])
            hit = by_base.get(base) or by_stem.get(stem) or by_stem.get(base)
        if hit is None and r.get("part_number"):
            base, stem = _keys(r["part_number"])
            hit = by_stem.get(base) or by_stem.get(stem) or by_base.get(base)
        if hit is None or hit in out:
            unmatched.append(r)
            continue
        out[hit] = r
    return out, unmatched


def quantity_ladder(quantity: Optional[int]) -> list[int]:
    """The six costed quantities, with ``quantity`` as an exact point.

    The same rule as the single-part check's ``quantityLadderForAnnual``: the
    closest interior point of the ladder gives way to the declared quantity.
    """
    ladder = list(QTY_LADDER)
    if quantity is None or quantity <= 0 or quantity in ladder:
        return ladder
    import math

    interior = ladder[1:-1]
    nearest = min(interior, key=lambda q: abs(math.log(q) - math.log(quantity)))
    return sorted([q for q in ladder if q != nearest] + [quantity])


# ---------------------------------------------------------------------------
# One part's row on the board
# ---------------------------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _estimate(result: dict, process: Optional[str], qty: int) -> Optional[dict]:
    if not process:
        return None
    best = None
    for e in result.get("estimates") or []:
        if e.get("process") != process:
            continue
        if e.get("quantity") == qty:
            return e
        if best is None:
            best = e
    return best


def _driver(est: Optional[dict], name: str) -> Optional[dict]:
    for d in (est or {}).get("drivers") or []:
        if d.get("name") == name:
            return d
    return None


# The mass the engine charges for (stock cut from, material printed with its
# supports, metal poured), as its material_cost derivation states it:
# "... = 0.0518 kg × $1.5/kg ...". The board's SQL slice keeps just this clause.
_USED_KG = re.compile(r"=\s*(\d+(?:\.\d+)?)\s*kg\s*×\s*\$")
_USED_KG_SQL = "=[[:space:]]*[0-9.]+[[:space:]]*kg[[:space:]]*×[[:space:]]*[$]"


def material_used_kg(est: Optional[dict]) -> Optional[float]:
    """Material the engine charges for per part, from its material_cost derivation; None if it doesn't say."""
    src = (_driver(est, "material_cost") or {}).get("source")
    m = _USED_KG.search(src) if isinstance(src, str) else None
    kg = float(m.group(1)) if m else None
    return kg if kg is not None and kg > 0 else None


def _density(material: Optional[str]) -> Optional[float]:
    if not material:
        return None
    from src.profiles.database import get_material_by_name

    m = get_material_by_name(material)
    return _num(getattr(m, "density", None)) if m is not None else None


def _first_sentence(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = s.strip()
    i = t.find(". ")
    return (t[:i] if i > 0 else t).rstrip(".")


_FAILURE_WORDS: tuple[tuple[re.Pattern, str], ...] = (
    # A time cap first: a mesh strategy stopped at its cap says nothing about the geometry.
    (re.compile(r"parsing exceeded|exceeded \d+(\.\d+)?s (timeout|cap)|timed out", re.I),
     "Reading the file ran past the time limit; check it on its own"),
    (re.compile(r"could not (tessellate|mesh)|all \d+ mesh strategies failed", re.I),
     "The CAD kernel couldn't make a solid from this file (open, wire-only or damaged geometry)"),
    (re.compile(r"not a valid stl|could not (parse|read|load)|unable to (parse|read|load)|no geometry|empty mesh", re.I),
     "The file couldn't be read as STEP, STL or IGES"),
    (re.compile(r"unsupported (native cad|drawing)", re.I), "A native CAD file or drawing: export it as STEP"),
    (re.compile(r"exceeds limit|exceeds the upload size|too large", re.I), "The file is over the 100 MB limit"),
    (re.compile(r"active organization changed", re.I), "Your active organization changed during the run"),
    (re.compile(r"batch cancelled|cancelled", re.I), "Skipped: the run was cancelled"),
)


def failure_words(error: Optional[str]) -> Optional[str]:
    """Why a part couldn't be checked, in plain words (the raw error stays in ``error``)."""
    if not error:
        return None
    for pattern, words in _FAILURE_WORDS:
        if pattern.search(error):
            return words
    text = re.sub(r"^\s*\d{3}:\s*", "", error)
    return _first_sentence(text)


def process_words(process: Optional[str]) -> str:
    from src.services.catalog_service import process_label

    return process_label(process) if process else "No route"


def _lower(words: str) -> str:
    """Lower-case a name for mid-sentence use, keeping acronyms ("DLP 3D printing" stays)."""
    return words[0].lower() + words[1:] if len(words) > 1 and words[1].islower() else words


def _machines_of(machines: list[dict], process: Optional[str]) -> list[str]:
    return [m["name"] for m in machines if m.get("process") == process]


def _who(machines: list[dict], process: Optional[str]) -> str:
    names = _machines_of(machines, process)
    if len(names) == 1:
        return names[0]
    return f"Your {_lower(process_words(process))} machines" if names else f"A {_lower(process_words(process))} machine"


def derive_part_row(
    *,
    item: dict,
    analysis: Optional[dict],
    decision: Optional[dict],
    meta: Optional[dict],
    machines: list[dict],
    default_quantity: int,
    governance: Optional[dict] = None,
) -> dict:
    """One part on the board: bucket, reason, resources first, price second.

    ``item``: the batch item's ``ulid``, ``filename``, ``status``,
    ``error_message``, ``duration_ms``. ``analysis`` / ``decision``: ``{ulid,
    mesh_hash, result_json}`` or None. ``meta``: the parts-list row for this
    file. ``machines``: the org's ``{name, process}`` list. ``governance``: the
    record's outcome and sign-off fields (``governance_fields`` shape plus
    ``signers``: ``{user_id: name}``), or None. Pure.
    """
    meta = meta or {}
    qty = int(meta.get("quantity") or default_quantity)
    status = item.get("status")
    error = item.get("error_message")
    result = (decision or {}).get("result_json") or {}
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    verdict = verification.get("verdict") if verification else None
    part_key = (decision or {}).get("mesh_hash") or (analysis or {}).get("mesh_hash")

    row: dict[str, Any] = {
        "item_id": item.get("ulid"),
        "filename": item.get("filename"),
        "part_number": meta.get("part_number"),
        "description": meta.get("description"),
        "status": status,
        "part_key": part_key,
        "analysis_id": (analysis or {}).get("ulid"),
        "cost_decision_id": (decision or {}).get("ulid"),
        "quantity": qty,
        "quantity_source": "list" if meta.get("quantity") else "run",
        "verdict": verdict,
        "bucket": None,
        "reason": None,
        "route": None,
        "material": {
            "declared": meta.get("material"),
            "class": meta.get("material_class"),
            "note": meta.get("material_note"),
            "name": None,
            "mass_kg_each": None,
            "mass_basis": None,
            "used_kg_each": None,
        },
        "hours_each": None,
        "hours_total": None,
        "mass_kg_total": None,
        "used_kg_total": None,
        "unit_cost_usd": None,
        "total_cost_usd": None,
        "price_withheld": None,
        "machine_rate_usd": None,
        "marginal": False,
        "capability": None,
        "cheaper_outside": None,
        "duration_ms": item.get("duration_ms"),
        "error": None,
        # The part's declared specs as the run priced them (the record's specs
        # block), else as the parts list declared them: plain lines and the
        # certifications whoever makes it must hold.
        "specs": _row_specs(result.get("specs"), meta.get("part_specs")),
        # The outcome recorded on the part's record and its sign-off, said
        # plainly when what was signed off has changed since.
        "outcome": None,
        "signoff": None,
        "record_out_of_date": False,
    }
    if decision is not None and governance:
        from src.services.signoff_service import signoff_view

        row["outcome"] = governance.get("user_disposition")
        row["signoff"] = signoff_view(governance, governance.get("signers") or {})
        row["record_out_of_date"] = bool(governance.get("is_stale"))

    if status in ("pending", "queued", "processing"):
        row["bucket"] = "checking"
        row["reason"] = "Checking"
        return row
    if status in ("failed", "skipped"):
        row["bucket"] = "not_checked"
        row["reason"] = failure_words(error) or ("Skipped" if status == "skipped" else "Couldn't be checked")
        row["error"] = error
        return row

    if decision is None:
        if error and error.startswith(GEOMETRY_INVALID_PREFIX):
            row["bucket"] = "cant_make"
            row["verdict"] = "geometry_invalid"
            reason = error[len(GEOMETRY_INVALID_PREFIX):]
            row["reason"] = f"Not a valid solid: {_first_sentence(reason) or 'the geometry needs repair'}"
        else:
            row["bucket"] = "not_sorted"
            row["reason"] = "Checked; no price or machine verdict"
        return row

    if result.get("status") == "GEOMETRY_INVALID":
        row["bucket"] = "cant_make"
        row["verdict"] = "geometry_invalid"
        row["reason"] = f"Not a valid solid: {_first_sentence(result.get('reason')) or 'the geometry needs repair'}"
        return row

    bucket = _BUCKET_OF_VERDICT.get(verdict or "")
    decision_block = result.get("decision") or {}
    rec = (decision_block.get("recommendation") or {}).get(str(qty)) or {}
    make_now = rec.get("process") or decision_block.get("make_now_process")
    if bucket is None:
        row["bucket"] = "not_sorted"
        row["reason"] = ("Not checked against machines: add your machines in Your shop"
                         if not verification.get("inventory_declared") else "No machine verdict for this part")
        process = make_now
    elif bucket == "in_house":
        resource = verification.get("resource") or {}
        process = resource.get("process")
        machine = resource.get("machine") or verification.get("best_machine")
        row["route"] = {"process": process, "machine": machine, "owned": True}
    elif bucket == "outside":
        process = make_now
        row["route"] = {"process": process, "machine": None, "owned": False}
    elif bucket == "new_machine":
        from src.services.part_summary_service import derive_makeability_fields

        fields = derive_makeability_fields(result)
        gap = fields.get("makeability_gap") or {}
        process = gap.get("process") or make_now
        fails = gap.get("gap") or []
        first = fails[0] if fails else {}
        row["capability"] = {
            "process": process,
            "gate": gap.get("gate"),
            "single": gap.get("single"),
            "need": first.get("need"),
            "have": first.get("have"),
            "human": first.get("human"),
            "all": [f.get("human") for f in fails if f.get("human")],
        }
        row["route"] = {"process": process, "machine": None, "owned": False}
    else:  # cant_make
        process = None

    row["bucket"] = row["bucket"] or bucket
    est = _estimate(result, process, qty) if process else None

    # --- the reason, in one line ---------------------------------------
    if bucket == "in_house":
        mat = (est or {}).get("material")
        row["reason"] = f"On your {row['route']['machine'] or process_words(process)}" + (f" · {mat}" if mat else "")
    elif bucket == "outside":
        names = ", ".join(sorted({m.get('process') for m in machines if m.get('process')}))
        row["reason"] = (f"No machine of yours does {_lower(process_words(process))}" if process
                         else "No route on your machines")
        if not names:
            row["reason"] = "No machines declared to compare against"
    elif bucket == "new_machine":
        cap = row["capability"] or {}
        human = _first_sentence(cap.get("human"))
        row["reason"] = f"{_who(machines, process)}: {human}" if human else f"{_who(machines, process)} doesn't fit"
    elif bucket == "cant_make":
        env = verification.get("env_exclusions") or []
        gaps = verification.get("gap") or []
        human = None
        if verdict == "environment_excluded" and env:
            e0 = env[0] if isinstance(env[0], dict) else {}
            human = e0.get("human") or e0.get("reason")
        if not human and gaps:
            g0 = gaps[0] if isinstance(gaps[0], dict) else {}
            human = g0.get("human")
        row["reason"] = _first_sentence(human) or "No route makes it as drawn"

    if bucket is None and not row["reason"]:
        row["reason"] = "No machine verdict"

    # --- resources first, price second -----------------------------------
    if est is not None:
        cycle = _driver(est, "cycle_time")
        hours = _num((cycle or {}).get("value"))
        machine_cost = _num((_driver(est, "machine_cost") or {}).get("value"))
        row["hours_each"] = hours
        row["hours_total"] = round(hours * qty, 4) if hours is not None else None
        if hours and machine_cost is not None and hours > 0:
            row["machine_rate_usd"] = round(machine_cost / hours, 2)
        row["marginal"] = _driver(est, "owned_in_house") is not None
        material = est.get("material")
        row["material"]["name"] = material
        volume = _num((result.get("geometry") or {}).get("volume_cm3"))
        density = _density(material)
        if volume is not None and density is not None:
            each = volume * density / 1000.0
            row["material"]["mass_kg_each"] = round(each, 5)
            row["material"]["mass_basis"] = f"measured volume {volume:g} cm³ × {material} {density:g} g/cm³ (book value)"
            row["mass_kg_total"] = round(each * qty, 4)
        used = material_used_kg(est)
        if used is not None:
            row["material"]["used_kg_each"] = round(used, 5)
            row["used_kg_total"] = round(used * qty, 4)
        if est.get("dfm_ready", True) and _num(est.get("unit_cost_usd")) is not None:
            row["unit_cost_usd"] = _num(est.get("unit_cost_usd"))
            row["total_cost_usd"] = round(row["unit_cost_usd"] * qty, 2)
        else:
            blockers = est.get("dfm_blockers") or []
            row["price_withheld"] = _first_sentence(blockers[0]) if blockers else "Not makeable as drawn on this route"

    # In-house, but a route outside is cheaper at this quantity: say so.
    if bucket == "in_house" and make_now and make_now != process and row["unit_cost_usd"] is not None:
        alt = _num(rec.get("unit_cost_usd"))
        if alt is not None and alt < row["unit_cost_usd"] and rec.get("dfm_ready", True):
            row["cheaper_outside"] = {"process": make_now, "unit_cost_usd": alt}
    return row


def _row_specs(block: Any, declared: Any) -> Optional[dict]:
    from src.costing.part_specs import normalize_part_specs, required_certifications, spec_summary

    if isinstance(block, dict) and block.get("summary"):
        return {"summary": list(block.get("summary") or []),
                "supplier_must_hold": [c.get("label") for c in block.get("certifications") or [] if isinstance(c, dict)],
                "excluded_processes": list(block.get("excluded_processes") or [])}
    try:
        specs = normalize_part_specs(declared) if isinstance(declared, dict) else None
    except ValueError:
        specs = None
    if not specs:
        return None
    return {"summary": spec_summary(specs),
            "supplier_must_hold": [c["label"] for c in required_certifications(specs)],
            "excluded_processes": []}


def bucket_totals(rows: list[dict]) -> dict:
    """Per bucket: parts, quantity, machine hours, material kg (the parts' own mass, and
    the material the engine charges for) and cost at quantity.

    Sums only real figures; ``*_parts`` says how many parts each sum covers.
    """
    out: dict[str, dict] = {}
    for key in BUCKETS + OTHER_BUCKETS:
        sel = [r for r in rows if r.get("bucket") == key]

        def total(field: str) -> tuple[Optional[float], int]:
            vals = [r[field] for r in sel if _num(r.get(field)) is not None]
            return (round(sum(vals), 4) if vals else None), len(vals)

        hours, hours_n = total("hours_total")
        mass_vals = [r["mass_kg_total"] for r in sel if _num(r.get("mass_kg_total")) is not None]
        used, used_n = total("used_kg_total")
        cost, cost_n = total("total_cost_usd")
        out[key] = {
            "parts": len(sel),
            "quantity": sum(int(r.get("quantity") or 0) for r in sel),
            "hours": hours,
            "hours_parts": hours_n,
            "mass_kg": round(sum(mass_vals), 4) if mass_vals else None,
            "mass_parts": len(mass_vals),
            "used_kg": used,
            "used_parts": used_n,
            "cost_usd": round(cost, 2) if cost is not None else None,
            "cost_parts": cost_n,
        }
    return out


def bucket_breakdown(rows: list[dict]) -> dict:
    """Per bucket, what its parts take, resources first.

    ``machines``: machine hours per machine of yours (in-house), or per process
    you'd have made outside or need a new machine for (``machine`` None), most
    hours first. ``materials``: the material the engine charges for, by grade
    (``used_kg``), with the parts' own mass (``part_kg``) beside it.
    ``missing`` (needs a new machine): the capability each lacks, by process,
    gate and need, most parts first. Sums only real figures; each entry says how
    many parts it covers. Pure.
    """
    out: dict[str, dict] = {}
    for key in BUCKETS + OTHER_BUCKETS:
        sel = [r for r in rows if r.get("bucket") == key]
        machines: dict[tuple, dict] = {}
        materials: dict[str, dict] = {}
        missing: dict[tuple, dict] = {}
        for r in sel:
            route = r.get("route") or {}
            process = route.get("process") or (r.get("capability") or {}).get("process")
            owned = bool(route.get("owned"))
            if process or route.get("machine"):
                k = (route.get("machine") if owned else None, process)
                m = machines.setdefault(k, {"machine": k[0], "process": process, "owned": owned,
                                            "parts": 0, "hours": None, "hours_parts": 0})
                m["parts"] += 1
                h = _num(r.get("hours_total"))
                if h is not None:
                    m["hours"] = round((m["hours"] or 0.0) + h, 4)
                    m["hours_parts"] += 1
            mat = (r.get("material") or {}).get("name")
            if mat:
                g = materials.setdefault(mat, {"material": mat, "parts": 0, "used_kg": None, "used_parts": 0,
                                               "part_kg": None, "part_parts": 0})
                g["parts"] += 1
                used = _num(r.get("used_kg_total"))
                if used is not None:
                    g["used_kg"] = round((g["used_kg"] or 0.0) + used, 4)
                    g["used_parts"] += 1
                part = _num(r.get("mass_kg_total"))
                if part is not None:
                    g["part_kg"] = round((g["part_kg"] or 0.0) + part, 4)
                    g["part_parts"] += 1
            cap = r.get("capability")
            if key == "new_machine" and isinstance(cap, dict):
                need = cap.get("need") if isinstance(cap.get("need"), (str, int, float)) else None
                k = (cap.get("process"), cap.get("gate"), need if cap.get("gate") == "material" else None)
                g = missing.setdefault(k, {"process": k[0], "gate": k[1], "need": k[2], "human": cap.get("human"),
                                           "parts": 0, "hours": None})
                g["parts"] += 1
                h = _num(r.get("hours_total"))
                if h is not None:
                    g["hours"] = round((g["hours"] or 0.0) + h, 4)

        def by_hours(e: dict) -> tuple:
            return (-(e.get("hours") or 0.0), -e["parts"], str(e.get("machine") or e.get("process") or ""))

        out[key] = {
            "machines": sorted(machines.values(), key=by_hours),
            "materials": sorted(materials.values(), key=lambda g: (-(g["used_kg"] or g["part_kg"] or 0.0), -g["parts"], g["material"])),
            "missing": sorted(missing.values(), key=lambda g: (-g["parts"], str(g["process"] or ""), str(g["gate"] or ""))),
        }
    return out


# ---------------------------------------------------------------------------
# The board read and its CSV
# ---------------------------------------------------------------------------

async def _org_machines(session: AsyncSession, org_id: str) -> list[dict]:
    from src.db.models import MachineInstance

    rows = (await session.execute(
        select(MachineInstance.name, MachineInstance.process).where(MachineInstance.org_id == org_id)
        .order_by(MachineInstance.name)
    )).all()
    return [{"name": n, "process": p} for n, p in rows]


def run_meta(batch: Batch) -> dict:
    return dict((batch.manifest_json or {}).get("catalog") or {})


# The part of a cost decision the board reads (derive_part_row), cut down in the
# database. A decision's ``estimates`` (every process at every quantity, with
# each driver's provenance) is ~170 KB of its ~190 KB; the board needs only a
# few fields of each estimate and the name and value of three of its drivers.
# Other keys are kept exactly as stored (present, absent or JSON null), so a row
# reads the same as from the whole record (tests/test_catalog_run_e2e.py
# compares them).
_BOARD_DECISION_KEYS = ("status", "reason", "verification", "geometry", "specs")
_BOARD_DECISION_BLOCK_KEYS = ("recommendation", "make_now_process")
_BOARD_ESTIMATE_KEYS = ("process", "quantity", "material", "unit_cost_usd", "dfm_ready", "dfm_blockers")
_BOARD_DRIVERS = ("cycle_time", "machine_cost", "owned_in_house", "material_cost")


def _sql_names(names: Iterable[str]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _sql_array(expr: str) -> str:
    return f"CASE WHEN jsonb_typeof({expr}) = 'array' THEN {expr} ELSE '[]'::jsonb END"


_BOARD_DECISION_SQL = f"""(
CASE WHEN cost_decisions.result_json IS NULL THEN NULL ELSE
  COALESCE((SELECT jsonb_object_agg(k, v) FROM jsonb_each(cost_decisions.result_json) AS t(k, v)
            WHERE k IN ({_sql_names(_BOARD_DECISION_KEYS)})), '{{}}'::jsonb)
  || CASE WHEN jsonb_typeof(cost_decisions.result_json -> 'decision') = 'object' THEN jsonb_build_object('decision',
       COALESCE((SELECT jsonb_object_agg(k, v) FROM jsonb_each(cost_decisions.result_json -> 'decision') AS t(k, v)
                 WHERE k IN ({_sql_names(_BOARD_DECISION_BLOCK_KEYS)})), '{{}}'::jsonb))
     WHEN cost_decisions.result_json ? 'decision' THEN jsonb_build_object('decision', cost_decisions.result_json -> 'decision')
     ELSE '{{}}'::jsonb END
  || CASE WHEN cost_decisions.result_json ? 'estimates' THEN jsonb_build_object('estimates', COALESCE((
       SELECT jsonb_agg(
         COALESCE((SELECT jsonb_object_agg(k, v) FROM jsonb_each(e) AS t(k, v)
                   WHERE k IN ({_sql_names(_BOARD_ESTIMATE_KEYS)})), '{{}}'::jsonb)
         || CASE WHEN e ? 'drivers' THEN jsonb_build_object('drivers', COALESCE((
              SELECT jsonb_agg(jsonb_build_object('name', d -> 'name', 'value', d -> 'value')
                || CASE WHEN d ->> 'name' = 'material_cost' AND jsonb_typeof(d -> 'source') = 'string'
                        THEN jsonb_build_object('source', substring(d ->> 'source' from '{_USED_KG_SQL}')) ELSE '{{}}'::jsonb END
                ORDER BY n) FROM jsonb_array_elements({_sql_array("e -> 'drivers'")}) WITH ORDINALITY AS dd(d, n)
              WHERE d ->> 'name' IN ({_sql_names(_BOARD_DRIVERS)})), '[]'::jsonb))
            ELSE '{{}}'::jsonb END
         ORDER BY i)
       FROM jsonb_array_elements({_sql_array("cost_decisions.result_json -> 'estimates'")}) WITH ORDINALITY AS ee(e, i)
       WHERE jsonb_typeof(e) = 'object'), '[]'::jsonb))
     ELSE '{{}}'::jsonb END
END)"""


async def build_board(session: AsyncSession, batch: Batch) -> dict:
    """The run's board: every item as a row, bucket totals and the run's facts.

    Polled every few seconds while a run goes, so it reads only the columns and
    the slice of each decision the rows use (``_BOARD_DECISION_SQL``).
    """
    meta = run_meta(batch)
    items = (await session.execute(
        select(
            BatchItem.ulid, BatchItem.filename, BatchItem.status, BatchItem.error_message, BatchItem.duration_ms,
            Analysis.ulid, Analysis.mesh_hash,
            CostDecision.ulid, CostDecision.mesh_hash,
            literal_column(_BOARD_DECISION_SQL, type_=JSONB),
            CostDecision.user_disposition, CostDecision.approval_status, CostDecision.approved_by_user_id,
            CostDecision.approved_at, CostDecision.approval_note, CostDecision.stale_at, CostDecision.stale_reason,
        )
        .select_from(BatchItem)
        .outerjoin(Analysis, and_(BatchItem.analysis_id == Analysis.id, Analysis.org_id == BatchItem.org_id))
        .outerjoin(CostDecision, and_(BatchItem.cost_decision_id == CostDecision.id, CostDecision.org_id == BatchItem.org_id))
        .where(BatchItem.batch_id == batch.id)
        .order_by(BatchItem.id)
    )).all()
    machines = await _org_machines(session, batch.org_id)
    per_file = meta.get("items") or {}
    default_qty = int(meta.get("quantity") or DEFAULT_RUN_QUANTITY)
    from src.services import signoff_service

    signers = await signoff_service.names_for(session, [it[12] for it in items])
    now = datetime.now(timezone.utc)
    rows = []
    for (item_ulid, filename, status, error_message, duration_ms,
         analysis_ulid, analysis_hash, decision_ulid, decision_hash, decision_slice,
         disposition, approval, signer, signed_at, signoff_note, stale_at, stale_reason) in items:
        if stale_at is not None and stale_at.tzinfo is None:
            stale_at = stale_at.replace(tzinfo=timezone.utc)
        gov = {"approval_status": approval, "approved_by_user_id": signer,
               "approved_at": signed_at.isoformat() if signed_at else None, "approval_note": signoff_note,
               "is_stale": stale_at is not None and stale_at <= now, "stale_reason": stale_reason,
               "stale_at": stale_at.isoformat() if stale_at else None}
        rows.append(derive_part_row(
            item={"ulid": item_ulid, "filename": filename, "status": status,
                  "error_message": error_message, "duration_ms": duration_ms},
            analysis=({"ulid": analysis_ulid, "mesh_hash": analysis_hash} if analysis_ulid is not None else None),
            decision=({"ulid": decision_ulid, "mesh_hash": decision_hash, "result_json": decision_slice or {}}
                      if decision_ulid is not None else None),
            meta=per_file.get(filename),
            machines=machines,
            default_quantity=default_qty,
            governance={**gov, "user_disposition": disposition, "signers": signers},
        ))
    return {
        "batch_id": batch.ulid,
        "status": batch.status,
        "free": bool(meta.get("free")),
        "material_class": meta.get("material_class"),
        "quantity": default_qty,
        "parts_list": meta.get("parts_list"),
        "unmatched": meta.get("unmatched") or [],
        "machines": machines,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "rows": rows,
        "totals": bucket_totals(rows),
        "breakdown": bucket_breakdown(rows),
    }


OUTCOME_WORDS = {"inhouse": "Make in-house", "outside": "Make outside",
                 "acquire": "Acquire capability", "redesign": "Redesign"}

BUCKET_WORDS = {
    "in_house": "Make in-house",
    "outside": "Buy outside",
    "new_machine": "Needs a new machine",
    "cant_make": "Can't be made as drawn",
    "not_sorted": "Not sorted",
    "not_checked": "Not checked",
    "checking": "Checking",
}

CSV_HEADER = (
    "file,part_number,bucket,reason,route,machine,owned,material,declared_material,quantity,"
    "machine_hours_each,machine_hours_total,part_mass_kg_each,material_kg_total,"
    "unit_cost_usd,total_cost_usd,price_note,status,error,material_used_kg_each,material_used_kg_total,"
    "specs,supplier_must_hold,outcome,signed_off_by,signed_off_at,signoff_out_of_date\n"
)


def board_csv_rows(board: dict) -> Iterable[str]:
    from src.services.batch_service import _csv_escape

    def f(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, float):
            return f"{v:.6g}" if abs(v) < 1e6 else f"{v:.2f}"
        return _csv_escape(str(v))

    yield CSV_HEADER
    for r in board["rows"]:
        route = r.get("route") or {}
        mat = r.get("material") or {}
        note = r.get("price_withheld") or ""
        if r.get("marginal") and r.get("unit_cost_usd") is not None:
            note = "your machine at marginal rate"
        yield ",".join([
            f(r.get("filename")), f(r.get("part_number")), f(BUCKET_WORDS.get(r.get("bucket"), r.get("bucket"))),
            f(r.get("reason")), f(process_words(route.get("process")) if route.get("process") else None),
            f(route.get("machine")), f(route.get("owned")) if route else "",
            f(mat.get("name")), f(mat.get("declared")), f(r.get("quantity")),
            f(r.get("hours_each")), f(r.get("hours_total")), f(mat.get("mass_kg_each")), f(r.get("mass_kg_total")),
            f(r.get("unit_cost_usd")), f(r.get("total_cost_usd")), f(note), f(r.get("status")), f(r.get("error")),
            f(mat.get("used_kg_each")), f(r.get("used_kg_total")),
            f("; ".join((r.get("specs") or {}).get("summary") or []) or None),
            f("; ".join((r.get("specs") or {}).get("supplier_must_hold") or []) or None),
            f(OUTCOME_WORDS.get(r.get("outcome"), r.get("outcome"))),
            f((r.get("signoff") or {}).get("by")), f((r.get("signoff") or {}).get("at")),
            f((r.get("signoff") or {}).get("stale")) if r.get("signoff") else "",
        ]) + "\n"
