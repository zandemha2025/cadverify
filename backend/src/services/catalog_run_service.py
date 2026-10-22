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

import asyncio
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
from src.services.direct_upload_service import DirectUploadPreparationValidationError

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


def read_material(text: Optional[str]) -> dict:
    """What a parts list's material words name: ``{class, grade, note}``.

    ``class``: the family the run prices it in (the five classes, or ``nickel``),
    None when ScaleCAD can't price it. ``grade``: the grade key when the words
    name one ("4140", "Delrin"); the engine then prices each route in that grade
    where it runs it (``costing.material_grades``). ``note``: why it isn't priced,
    in plain words. A plastic ScaleCAD has no price for, or a metal family it
    doesn't price, is never priced as something else.
    """
    from src.costing.material_grades import PRICED_FAMILIES, engine_names_for, family_of_grade, grade_of

    raw = (text or "").strip()
    out: dict[str, Optional[str]] = {"class": None, "grade": None, "note": None}
    if not raw:
        return out
    if raw.lower() in MATERIAL_CLASSES:
        out["class"] = raw.lower()
        return out
    grade = grade_of(raw)
    if grade is not None:
        family = family_of_grade(grade)
        out["grade"] = grade
        if family not in PRICED_FAMILIES:
            out["note"] = f"{raw} isn't priced in ScaleCAD yet"
        elif family == "polymer" and not engine_names_for(raw):
            out["note"] = f"{raw} isn't a plastic ScaleCAD prices yet"
        else:
            out["class"] = family
        return out
    if _UNPRICED.search(raw):
        out["note"] = f"{raw} isn't priced in ScaleCAD yet"
        return out
    for cls, pattern in _MATERIAL_PATTERNS:
        if pattern.search(raw):
            out["class"] = cls
            return out
    out["note"] = f"{raw} isn't a material ScaleCAD recognises"
    return out


def material_class_of(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """``(material_class, note)`` for a material as a parts list names it (``read_material``)."""
    m = read_material(text)
    return m["class"], m["note"]


# ---------------------------------------------------------------------------
# Parts list (CSV or a BOM export)
# ---------------------------------------------------------------------------

_FILE_HEADERS = ("filename", "file", "file name", "file_name", "cad file", "cad_file", "cad", "model", "path", "document")
_QTY_HEADERS = ("quantity", "qty", "qty.", "count", "quantity per year", "annual quantity", "annual volume", "annual_volume", "volume", "units", "eau")
_MATERIAL_HEADERS = ("material", "material_class", "material class", "matl", "mat'l", "material spec", "spec")
_PART_HEADERS = ("part number", "part_number", "part no", "part no.", "part #", "pn", "p/n", "item number", "item", "part", "number")
_DESC_HEADERS = ("description", "desc", "name", "title")
# What the organization pays today to buy the part, and per how many.
_PRICE_HEADERS = ("current price", "current_price", "current unit price", "current price (usd)", "current price usd",
                  "buy price", "buy_price", "unit price", "unit_price", "unit price (usd)", "price", "price (usd)",
                  "price each", "price_each", "current cost", "unit cost", "cost each", "purchase price")
_PER_HEADERS = ("per", "price per", "price_per", "per qty", "price unit", "pricing unit", "price uom")
MAX_PRICE_USD = 10_000_000
_EACH_WORDS = {"", "each", "ea", "ea.", "pc", "pcs", "piece", "pieces", "unit", "units", "part", "1"}


def _parse_per(raw: str, row_num: int) -> int:
    """How many parts a listed price buys: "each" is 1, "100" or "per 100" is 100."""
    t = (raw or "").strip().lower()
    t = re.sub(r"^(per|/)\s*", "", t).replace(",", "")
    if t in _EACH_WORDS:
        return 1
    if t in ("c", "hundred"):
        return 100
    if t in ("thousand", "k"):
        return 1000
    if t.isdigit() and 1 <= int(t) <= MAX_QUANTITY:
        return int(t)
    raise ValueError(f"Row {row_num}: 'per' '{raw.strip()}' must be each or a number of parts, like 100")


def _parse_price(raw: str, per_raw: str, row_num: int) -> tuple[Optional[float], Optional[str]]:
    """``(usd each, as written)`` for a current price cell ("$12.40", "1,250 / 100"), or ``(None, None)``."""
    s = (raw or "").strip()
    if not s:
        return None, None
    per_text = per_raw
    m = re.match(r"^(.*?)\s*(?:/|per)\s*([0-9,]+|each|ea|pc|c|k)\s*$", s, re.I)
    if m:
        s, per_text = m.group(1), m.group(2)
    t = re.sub(r"(?i)usd|us\$|\$", "", s).replace(",", "").replace(" ", "")
    try:
        v = float(t)
    except ValueError:
        raise ValueError(f"Row {row_num}: current price '{raw.strip()}' isn't a number in US dollars")
    if not (0 < v <= MAX_PRICE_USD):
        raise ValueError(f"Row {row_num}: current price '{raw.strip()}' must be more than $0 and at most ${MAX_PRICE_USD:,}")
    per = _parse_per(per_text or "", row_num)
    shown = f"${v:,.2f}" + (f" per {per:,}" if per > 1 else " each")
    return round(v / per, 6), shown


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
    ci = _header_index(headers, _PRICE_HEADERS)
    ei = _header_index(headers, _PER_HEADERS)

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
        read = read_material(material)
        price, price_text = _parse_price(cell(row, ci), cell(row, ei), row_num)
        rows.append({
            "row": row_num,
            "file": file or None,
            "part_number": part or None,
            "description": cell(row, di) or None,
            "quantity": _parse_qty(cell(row, qi), row_num),
            "material": material,
            "material_class": read["class"],
            "material_grade": read["grade"],
            "material_note": read["note"],
            "current_price_usd": price,
            "current_price": price_text,
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


def _mass_field(est: Optional[dict], key: str) -> Optional[float]:
    """One figure of the estimate's structured ``material_mass`` (None on older records)."""
    mm = (est or {}).get("material_mass")
    kg = _num(mm.get(key)) if isinstance(mm, dict) else None
    return kg if kg is not None and kg > 0 else None


def material_used_kg(est: Optional[dict]) -> Optional[float]:
    """Material the engine charges for per part: the estimate's ``material_mass.used_kg``,
    else (older records) read from its material_cost derivation; None if it doesn't say."""
    kg = _mass_field(est, "used_kg")
    if kg is not None:
        return kg
    src = (_driver(est, "material_cost") or {}).get("source")
    m = _USED_KG.search(src) if isinstance(src, str) else None
    kg = float(m.group(1)) if m else None
    return kg if kg is not None and kg > 0 else None


def _kg_round(kg: float) -> float:
    """A mass to 5 decimals, or 3 significant figures under 10 g: a tiny part never rounds to 0."""
    return round(kg, 5) if kg >= 0.01 or kg <= 0 else float(f"{kg:.3g}")


def _density(material: Optional[str]) -> Optional[float]:
    if not material:
        return None
    from src.profiles.database import get_material_by_name

    m = get_material_by_name(material)
    return _num(getattr(m, "density", None)) if m is not None else None


# A size the engine wrote unrounded ("268.814272mm") in records made before its
# sentences rounded them: shown to 0.1 mm, like every size the engine writes now.
_RAW_MM = re.compile(r"(?<![\d.])(\d+\.\d{3,})(?=\s?mm\b)")


def _tidy_mm(s: Optional[str]) -> Optional[str]:
    if not isinstance(s, str):
        return s
    return _RAW_MM.sub(lambda m: f"{round(float(m.group(1)), 1):g}", s)


def _first_sentence(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    t = _tidy_mm(s).strip()
    i = t.find(". ")
    return (t[:i] if i > 0 else t).rstrip(".")


TIMED_OUT_WORDS = "Checking ran past its time limit; check it again"
_TIME_LIMIT = re.compile(r"parsing exceeded|exceeded \d+(\.\d+)?s (timeout|cap)|timed out|time limit|"
                         r"TIMEOUT_SEC|took longer than", re.I)
_FAILURE_WORDS: tuple[tuple[re.Pattern, str], ...] = (
    # A time cap first: a mesh strategy stopped at its cap says nothing about the geometry.
    (_TIME_LIMIT, TIMED_OUT_WORDS),
    (re.compile(r"could not (tessellate|mesh)|all \d+ mesh strategies failed", re.I),
     "The CAD kernel couldn't make a solid from this file (open, wire-only or damaged geometry)"),
    (re.compile(r"not a valid stl|could not (parse|read|load)|unable to (parse|read|load)|no geometry|empty mesh", re.I),
     "The file couldn't be read as STEP, STL or IGES"),
    (re.compile(r"unsupported (native cad|drawing)", re.I), "A native CAD file or drawing: export it as STEP"),
    (re.compile(r"exceeds limit|exceeds the upload size|too large", re.I), "The file is over the 100 MB limit"),
    (re.compile(r"active organization changed", re.I), "Your active organization changed during the run"),
    (re.compile(r"batch cancelled|cancelled", re.I), "Skipped: the run was cancelled"),
)


# A setting's name ("ANALYSIS_TIMEOUT_SEC=60s") never reaches a person's screen or file.
_SETTING = re.compile(r"\b[A-Z][A-Z0-9]*(_[A-Z0-9]+)+\b(=\S+)?")


def plain_error(error: Optional[str]) -> Optional[str]:
    """The raw error with setting names and API hints taken out (for the CSV)."""
    if not error:
        return error
    t = _SETTING.sub("the time limit", error) if _TIME_LIMIT.search(error) else _SETTING.sub("", error)
    t = re.sub(r"\s*Reduce scope with \?processes=\S*.*$", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def failure_words(error: Optional[str]) -> Optional[str]:
    """Why a part couldn't be checked, in plain words (the raw error stays in ``error``)."""
    if not error:
        return None
    for pattern, words in _FAILURE_WORDS:
        if pattern.search(error):
            return words
    text = re.sub(r"^\s*\d{3}:\s*", "", plain_error(error) or "")
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
    buy_price: Optional[dict] = None,
) -> dict:
    """One part on the board: bucket, reason, resources first, price second.

    Make or buy is decided by cost, not by ability alone (``decide_make_or_buy``):
    a part one of your machines can make is "Make in-house" only when making it
    costs less than buying it, against what you pay today when a price is known
    (``buy_price``: the part's typed price, which wins, else the parts list's)
    and the cheapest outside price otherwise. ``buy_price`` is the part's stored
    ``part_contexts.buy_price`` or None.

    ``item``: the batch item's ``ulid``, ``filename``, ``status``,
    ``error_message``, ``duration_ms``. ``analysis`` / ``decision``: ``{ulid,
    mesh_hash, result_json}`` or None. ``meta``: the parts-list row for this
    file. ``machines``: the org's ``{name, process}`` list. ``governance``: the
    record's outcome and sign-off fields (``governance_fields`` shape plus
    ``signers``: ``{user_id: name}``), or None. Pure.
    """
    meta = meta or {}
    qty = int(meta.get("quantity") or default_quantity)
    price = current_price(meta, buy_price)
    status = item.get("status")
    error = item.get("error_message")
    result = (decision or {}).get("result_json") or {}
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    verdict = verification.get("verdict") if verification else None
    part_key = (decision or {}).get("mesh_hash") or (analysis or {}).get("mesh_hash")

    row: dict[str, Any] = {
        "item_id": item.get("ulid"),
        "filename": item.get("filename"),
        "name": item.get("filename"),
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
        # On the parts list (its quantity, material and price are the list's), or
        # a file in the ZIP the list doesn't name (kept apart from the totals).
        "listed": meta.get("row") is not None,
        # What you pay today (or None), the in-house side, the buy side, and the saving.
        "current_price": price,
        "make": None,
        "buy": None,
        "could_make": None,
        "saving": None,
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
        elif meta.get("material") and not meta.get("material_class") and meta.get("material_note"):
            # A material ScaleCAD can't price: the shape is checked, the part isn't priced as anything else.
            row["bucket"] = "not_sorted"
            row["reason"] = f"{meta['material_note']}: its shape was checked, it isn't priced"
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
    opt = (decision_block.get("options") or {}).get(str(qty)) or None
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
        inside = (opt or {}).get("in_house") or {}
        if inside.get("process"):
            # The cheapest route on a machine of yours at this quantity (the engine's own comparison).
            process, machine = inside["process"], inside.get("machine") or machine
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
            "human": _tidy_mm(first.get("human")),
            "all": [_tidy_mm(f.get("human")) for f in fails if f.get("human")],
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
        owned_machine = next((m for m in machines if m.get("name") == (row.get("route") or {}).get("machine")
                              and m.get("running_rate_usd") is not None), None)
        if row["marginal"] and owned_machine is not None:
            # The running rate of the machine as you set it, the same on every row
            # (cost ÷ hours also carries learning at quantity, utilization and margin).
            row["machine_rate_usd"] = owned_machine["running_rate_usd"]
        material = est.get("material")
        row["material"]["name"] = material
        volume = _num((result.get("geometry") or {}).get("volume_cm3"))
        density = _mass_field(est, "density_g_cm3") or _density(material)
        each = _mass_field(est, "part_kg")
        if each is None and volume is not None and density is not None:
            each = volume * density / 1000.0
        if each is not None:
            row["material"]["mass_kg_each"] = _kg_round(each)
            if volume is not None and density is not None:
                row["material"]["mass_basis"] = f"measured volume {volume:g} cm³ × {material} {density:g} g/cm³ (book value)"
            row["mass_kg_total"] = _kg_round(each * qty)
        used = material_used_kg(est)
        if used is not None:
            row["material"]["used_kg_each"] = _kg_round(used)
            row["used_kg_total"] = _kg_round(used * qty)
        if est.get("dfm_ready", True) and _num(est.get("unit_cost_usd")) is not None:
            row["unit_cost_usd"] = _num(est.get("unit_cost_usd"))
            row["total_cost_usd"] = round(row["unit_cost_usd"] * qty, 2)
        else:
            blockers = est.get("dfm_blockers") or []
            row["price_withheld"] = _first_sentence(blockers[0]) if blockers else "Not makeable as drawn on this route"

    # The grade the parts list names, when the route was priced in another grade of the same metal.
    listed, used = meta.get("material"), row["material"]["name"]
    if listed and used and meta.get("material_grade") and process:
        from src.costing.material_grades import same_grade

        if not same_grade(used, listed):
            row["material"]["note"] = (f"{listed} isn't priced for {_lower(process_words(process))} in ScaleCAD; "
                                       f"priced as {used}, confirm")

    # Make or buy, by cost.
    decide_make_or_buy(row, result=result, opt=opt, price=price, qty=qty, est=est)

    # In-house, but a route outside is cheaper at this quantity (inside the estimate's range): say so.
    if row["bucket"] == "in_house" and row["unit_cost_usd"] is not None:
        out = (opt or {}).get("outside") or {}
        alt = _num(out.get("unit_cost_usd"))
        if alt is not None and out.get("process") and alt < row["unit_cost_usd"] and price is None:
            row["cheaper_outside"] = {"process": out["process"], "unit_cost_usd": alt,
                                      "same_process": bool(out.get("same_process"))}
        elif opt is None and make_now and make_now != process:
            alt = _num(rec.get("unit_cost_usd"))
            if alt is not None and alt < row["unit_cost_usd"] and rec.get("dfm_ready", True):
                row["cheaper_outside"] = {"process": make_now, "unit_cost_usd": alt}
    return row


# What decides make or buy, in one line (the board and the summary print it).
BUCKET_RULE = ("Make in-house when one of your machines makes it for less than buying it: what you pay today "
               "where you gave a price, else the cheapest outside price. A difference inside the in-house "
               "estimate's range counts as a tie, and a tie stays on your machine.")


def current_price(meta: Optional[dict], stored: Optional[dict]) -> Optional[dict]:
    """What you pay today for one part: ``{usd_each, source, text}`` or None.

    A price typed on the part's Decision view (``source: "you"``) wins over the
    parts list's; a price an earlier run's list stored is used only when this
    run's list gives none.
    """
    meta = meta or {}
    if isinstance(stored, dict) and stored.get("source") == "you" and _num(stored.get("usd_each")):
        return {"usd_each": float(stored["usd_each"]), "source": "you",
                "text": _price_text(stored)}
    if _num(meta.get("current_price_usd")):
        return {"usd_each": float(meta["current_price_usd"]), "source": "parts_list",
                "text": meta.get("current_price") or f"${float(meta['current_price_usd']):,.2f} each"}
    if isinstance(stored, dict) and _num(stored.get("usd_each")):
        return {"usd_each": float(stored["usd_each"]), "source": "parts_list", "text": _price_text(stored)}
    return None


def _price_text(stored: dict) -> str:
    per = int(stored.get("per") or 1)
    price = _num(stored.get("price_usd")) or float(stored["usd_each"]) * per
    return f"${price:,.2f}" + (f" per {per:,}" if per > 1 else " each")


def decide_make_or_buy(row: dict, *, result: dict, opt: Optional[dict], price: Optional[dict], qty: int,
                       est: Optional[dict]) -> None:
    """Put a part a machine of yours can make in "Make in-house" or "Buy outside", by cost.

    The in-house side is the engine's cheapest route on a machine of yours at the
    part's quantity; the buy side is what you pay today when known, else the
    engine's cheapest outside price (a job shop running the same process
    included). The engine's own rule decides (``decision.prefer_in_house``): a
    difference inside the in-house estimate's range is a tie and stays on your
    machine. A current price never changes the engine's figures, so it never
    marks the part's record out of date: it only moves the part between the two
    buckets and sets the saving. Sets ``make``, ``buy``, ``could_make`` and
    ``saving`` on the row and, when buying wins, the bucket, route and price.
    """
    from src.costing.decision import prefer_in_house

    inside = (opt or {}).get("in_house") if isinstance(opt, dict) else None
    outside = (opt or {}).get("outside") if isinstance(opt, dict) else None
    if inside and _num(inside.get("unit_cost_usd")) is not None:
        row["make"] = {"process": inside.get("process"), "machine": inside.get("machine"),
                       "material": inside.get("material"), "unit_cost_usd": _num(inside.get("unit_cost_usd")),
                       "low_usd": _num(inside.get("low_usd")), "high_usd": _num(inside.get("high_usd"))}
    if price is not None:
        row["buy"] = {"unit_cost_usd": price["usd_each"], "source": price["source"], "text": price["text"],
                      "process": None, "same_process": False}
    elif outside and _num(outside.get("unit_cost_usd")) is not None:
        row["buy"] = {"unit_cost_usd": _num(outside.get("unit_cost_usd")), "source": "model", "text": None,
                      "process": outside.get("process"), "same_process": bool(outside.get("same_process"))}
    elif row["bucket"] in ("outside", "new_machine") and row.get("unit_cost_usd") is not None:
        row["buy"] = {"unit_cost_usd": row["unit_cost_usd"], "source": "model", "text": None,
                      "process": (row.get("route") or {}).get("process"), "same_process": False}

    make, buy = row["make"], row["buy"]
    if row["bucket"] != "in_house" or make is None:
        return
    if buy is None:
        return  # nothing to buy it from: your machine is the only price
    if price is not None:
        pick, basis = prefer_in_house(
            {"unit_cost_usd": make["unit_cost_usd"], "low_usd": make["low_usd"] if make["low_usd"] is not None
             else make["unit_cost_usd"], "lead_low_days": None},
            {"unit_cost_usd": price["usd_each"], "lead_high_days": None})
    else:
        pick, basis = (opt or {}).get("pick") or "in_house", (opt or {}).get("basis")
    row["make_or_buy_basis"] = basis
    if pick == "in_house":
        if price is not None:
            each = round(price["usd_each"] - make["unit_cost_usd"], 2)
            row["saving"] = {"each": each, "total": round(each * qty, 2), "vs": price["source"]}
        return
    # Buying wins: the part moves to "Buy outside" and says what making it would cost.
    times = make["unit_cost_usd"] / buy["unit_cost_usd"] if buy["unit_cost_usd"] else None
    row["could_make"] = {"process": make["process"], "machine": make["machine"],
                         "unit_cost_usd": make["unit_cost_usd"], "times": round(times, 1) if times else None}
    row["bucket"] = "outside"
    row["route"] = {"process": buy.get("process"), "machine": None, "owned": False}
    who = make["machine"] or process_words(make["process"])
    ratio = f" ({row['could_make']['times']:g}× the buy price)" if times else ""
    row["reason"] = f"Could make in-house at ${make['unit_cost_usd']:,.2f} on your {who}{ratio}"
    row["unit_cost_usd"] = buy["unit_cost_usd"]
    row["total_cost_usd"] = round(buy["unit_cost_usd"] * qty, 2)
    row["marginal"] = False
    row["machine_rate_usd"] = None
    if buy.get("process") and buy["process"] != make["process"]:
        out_est = _estimate(result, buy["process"], qty)
        if out_est is not None:
            cycle = _num((_driver(out_est, "cycle_time") or {}).get("value"))
            row["hours_each"] = cycle
            row["hours_total"] = round(cycle * qty, 4) if cycle is not None else None
            row["material"]["name"] = out_est.get("material") or row["material"]["name"]
            used = material_used_kg(out_est)
            row["material"]["used_kg_each"] = _kg_round(used) if used is not None else None
            row["used_kg_total"] = _kg_round(used * qty) if used is not None else None
    elif price is not None:
        # Bought from your supplier: no route of ours, so no machine time or material of ours.
        row["hours_each"] = row["hours_total"] = None
        row["used_kg_total"] = None


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


# Names a CAD exporter writes into a STEP product tree that aren't anyone's
# name for the part ("Open CASCADE STEP translator 7.8 1.1", "Part1", "SOLID").
_NOISE_NAME = re.compile(
    r"open\s*cascade|step\s*translator|\bap\s*2(03|14|42)\b|^(part|body|solid|shape|component|product|"
    r"assembly|assy|instance|nauo)\s*[-_.#]?\s*\d*(\.\d+)?$|^unnamed|^untitled|^none$|^\d+$", re.I)


def plain_body_name(name: Optional[str]) -> Optional[str]:
    """A body's own name from the STEP product tree, or None when it is an exporter's stamp."""
    n = (name or "").strip()
    if not n or _NOISE_NAME.search(n):
        return None
    return n[:80]


_SPLIT_KIND_WORDS = {
    "separate_bodies": "separate bodies",
    "weldment": "a weldment",
    "assembly": "an assembly",
    "bodies": "several bodies",
}


def body_rows(
    *,
    item: dict,
    entry: dict,
    parent_meta: Optional[dict],
    analyses: dict,
    decisions: dict,
    machines: list[dict],
    default_quantity: int,
    governance_of=None,
    buy_prices: Optional[dict] = None,
) -> list[dict]:
    """A file split body by body (``catalog_bodies``): one row per body shape.

    ``entry`` is the run manifest's record of the split; ``analyses`` maps an
    analysis id to ``{ulid, mesh_hash}`` and ``decisions`` a decision ulid to
    ``{ulid, mesh_hash, result_json}`` (the board's slice). The quantity is the
    file's times the copies of that shape in the file. A weldment member has no
    machining price: its row gives its stock and material, and says welding isn't
    priced. Pure.
    """
    parent_meta = parent_meta or {}
    base = int(parent_meta.get("quantity") or default_quantity)
    kind = entry.get("kind")
    out: list[dict] = []
    for d in entry.get("designs") or []:
        copies = max(1, int(d.get("copies") or 1))
        meta = {**parent_meta, "quantity": base * copies}
        status = d.get("status")
        error = None
        row_status = "completed"
        if status in ("geometry_invalid", "open"):
            error = GEOMETRY_INVALID_PREFIX + str(d.get("reason") or "the geometry needs repair")
        elif status == "error":
            row_status, error = "failed", str(d.get("reason") or "The body couldn't be checked.")
        elif status == "not_checked":
            row_status = "skipped"
        decision = decisions.get(d.get("decision_ulid")) if d.get("decision_ulid") else None
        row = derive_part_row(
            item={"ulid": f"{item.get('ulid')}:{d.get('design')}", "filename": d.get("filename"),
                  "status": row_status, "error_message": error, "duration_ms": None},
            analysis=analyses.get(d.get("analysis_id")),
            decision=decision,
            meta=meta,
            machines=machines,
            default_quantity=default_quantity,
            governance=governance_of(decision) if (governance_of and decision) else None,
            buy_price=(buy_prices or {}).get((decision or {}).get("mesh_hash")),
        )
        row["quantity_source"] = "list" if parent_meta.get("quantity") else "run"
        if status == "not_checked" and d.get("reason"):
            row["reason"] = d["reason"]
        name = plain_body_name(d.get("name"))
        ids = d.get("bodies") or []
        of = entry.get("body_count")
        row["body"] = {
            "file": item.get("filename"),
            "file_key": entry.get("parent_mesh_hash"),
            "kind": kind,
            "ids": ids,
            "copies": copies,
            "of": of,
            "shape": d.get("shape"),
            "name": name,
        }
        # "bracket-assembly.step, body 1 of 3": the file the person gave, and which body.
        which = name or (f"body {ids[0]}" if ids else "a body")
        row["name"] = f"{item.get('filename')}, {which}" + (f" of {of}" if of and not name else "")
        if status == "member":
            stock = d.get("stock_material") or {}
            row["bucket"] = "not_sorted"
            row["reason"] = f"Weldment member: {d.get('shape') or 'cut stock'}. Welding isn't priced yet"
            row["price_withheld"] = "welding isn't priced yet"
            if stock.get("mass_kg") is not None:
                row["material"]["name"] = stock.get("material")
                row["material"]["mass_kg_each"] = stock.get("mass_kg")
                row["material"]["mass_basis"] = (f"measured volume × {stock.get('material')} "
                                                 f"{stock.get('density_g_cm3')} g/cm³ (book value)")
                row["mass_kg_total"] = round(float(stock["mass_kg"]) * row["quantity"], 4)
        out.append(row)
    return out


def split_file_note(filename: str, entry: dict) -> dict:
    """What the board says about a file it shows body by body."""
    n = entry.get("body_count") or 0
    shapes = entry.get("shapes") or len(entry.get("designs") or [])
    what = _SPLIT_KIND_WORDS.get(entry.get("kind") or "", "several bodies")
    words = (f"{filename} holds {n} bodies ({what}): on the board as {shapes} "
             f"{'row' if shapes == 1 else 'rows'}, one per shape, at the file's quantity times its copies. "
             "It counts as one part of the run's allowance.")
    if entry.get("kind") == "weldment":
        words += " Its members are cut stock; welding isn't priced yet."
    return {
        "filename": filename,
        "part_key": entry.get("parent_mesh_hash"),
        "kind": entry.get("kind"),
        "summary": entry.get("summary"),
        "bodies": n,
        "rows": shapes,
        "words": words,
    }


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
        select(MachineInstance.name, MachineInstance.process, MachineInstance.count,
               MachineInstance.hourly_rate_usd, MachineInstance.capital_frac)
        .where(MachineInstance.org_id == org_id)
        .order_by(MachineInstance.name)
    )).all()
    return [machine_entry(n, p, c, r, cf) for n, p, c, r, cf in rows]


def machine_entry(name, process, count=1, rate=None, capital_frac=None) -> dict:
    """A machine as the board names it, with its running rate when you set an hourly rate.

    Running ("marginal") rate: the hourly rate you set, less the share of it that
    pays for the machine itself (yours, else the rate card's typical share),
    because a machine you own is already paid for.
    """
    from src.costing.rates import build_rate_card

    out = {"name": name, "process": process, "count": max(1, int(count or 1))}
    if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
        cf = float(capital_frac) if isinstance(capital_frac, (int, float)) and not isinstance(capital_frac, bool) \
            else float(build_rate_card().g("machine_capital_frac"))
        out.update(hourly_rate_usd=round(float(rate), 2), capital_frac=round(cf, 4),
                   capital_frac_set=isinstance(capital_frac, (int, float)) and not isinstance(capital_frac, bool),
                   running_rate_usd=round(float(rate) * (1.0 - cf), 2))
    return out


async def _buy_prices(session: AsyncSession, org_id: str, part_keys: Iterable[str]) -> dict[str, dict]:
    """``{mesh_hash: buy_price}`` stored on the parts' declared contexts."""
    from src.db.models import PartContext

    keys = sorted({k for k in part_keys if k})
    if not keys:
        return {}
    rows = (await session.execute(
        select(PartContext.mesh_hash, PartContext.buy_price)
        .where(PartContext.org_id == org_id, PartContext.mesh_hash.in_(keys), PartContext.buy_price.isnot(None))
    )).all()
    return {h: p for h, p in rows if isinstance(p, dict)}


def run_meta(batch: Batch) -> dict:
    return dict((batch.manifest_json or {}).get("catalog") or {})


# ---------------------------------------------------------------------------
# A run's parts: their quantities and materials, and the free allowance
# ---------------------------------------------------------------------------
#
# A run from a ZIP posted with the request does both in the request. A run from
# a ZIP uploaded to storage (``direct_upload_id``) is unpacked on the worker
# (``batch_tasks.prepare_direct_upload_batch``): the request keeps the run's
# options in ``manifest_json["catalog_run"]`` and the worker does both once the
# ZIP is unpacked, with the same batch extraction limits as a posted ZIP.

PENDING_KEY = "catalog_run"


def apply_catalog_meta(
    batch: Batch,
    items_data: list[dict],
    *,
    free: bool,
    material_class: Optional[str],
    quantity: int,
    parts_list: Optional[list[dict]],
    list_name: Optional[str],
    zip_name: Optional[str] = None,
) -> None:
    """Give each part its quantity ladder and material, and keep the run's facts.

    The parts list wins per file; a file it doesn't name takes the run's
    quantity and material. A material the list names is priced as that grade
    (``read_material``); one ScaleCAD can't price leaves the part checked and
    not priced, never priced in the run's material instead. Rows naming no file
    in the ZIP are kept (first 200) so the board can list them honestly.
    """
    names = [it["filename"] for it in items_data if it.get("status") not in {"skipped", "failed"}]
    by_file, unmatched = match_parts_list(parts_list or [], names)
    per_file: dict[str, dict] = {}
    for it in items_data:
        if it.get("status") in {"skipped", "failed"}:
            continue
        row = by_file.get(it["filename"])
        qty = (row or {}).get("quantity") or quantity
        cls = (row or {}).get("material_class") if (row or {}).get("material") else material_class
        it["quantities"] = ";".join(str(q) for q in quantity_ladder(qty))
        it["material_class"] = cls
        if row is not None:
            per_file[it["filename"]] = {
                k: row.get(k) for k in ("part_number", "description", "quantity", "material", "material_class",
                                        "material_grade", "material_note", "row", "part_specs",
                                        "current_price_usd", "current_price")
                if k not in ("part_specs", "current_price_usd", "current_price", "material_grade") or row.get(k)
            }
    manifest_json = dict(batch.manifest_json or {})
    manifest_json["catalog"] = {
        "name": run_name(zip_name, list_name),
        "zip_name": zip_name,
        "free": free,
        "material_class": material_class,
        "quantity": quantity,
        "parts_list": (
            {"name": list_name, "rows": len(parts_list), "matched": len(by_file), "unmatched": len(unmatched)}
            if parts_list is not None else None
        ),
        "unmatched": [
            {k: r.get(k) for k in ("row", "file", "part_number", "description", "quantity", "material")}
            for r in unmatched[:200]
        ],
        "items": per_file,
    }
    batch.manifest_json = manifest_json


async def reserve_catalog_run(session: AsyncSession, user_id: int, batch: Batch, access) -> Any:
    """Count the run's new parts against the free allowance, atomically with the batch.

    ``access`` is ``catalog_allowance.CatalogAccess``; None is returned for a run
    that isn't free. Raises the allowance's own 403 / 409 (``HTTPException``).
    """
    if not access.free:
        return None
    import hashlib

    from src.auth.catalog_allowance import file_identity, reserve_catalog_parts
    from src.auth.validation_caps import SAMPLE_PART_SHA256
    from src.services import batch_service

    items = (await session.execute(
        select(BatchItem.id, BatchItem.filename).where(
            BatchItem.batch_id == batch.id, BatchItem.status == "pending"
        ).order_by(BatchItem.id)
    )).all()

    def _identities() -> list[tuple[int, str]]:
        out = []
        for item_id, filename in items:
            data = batch_service.read_batch_blob(batch.ulid, filename)
            if hashlib.sha256(data).hexdigest() in SAMPLE_PART_SHA256:
                continue  # the app's sample part never counts
            out.append((item_id, file_identity(filename, data)))
        return out

    identities = await asyncio.to_thread(_identities)
    return await reserve_catalog_parts(
        session, user_id, batch.id, identities, access=access, exclude_batch_id=batch.id
    )


def pending_options(*, free: bool, material_class: Optional[str], quantity: int,
                    parts_list: Optional[list[dict]], list_name: Optional[str],
                    zip_name: Optional[str] = None) -> dict:
    """The options a run from a stored ZIP is prepared with on the worker (plain JSON)."""
    return {"free": free, "material_class": material_class, "quantity": int(quantity),
            "parts_list": parts_list, "list_name": list_name, "zip_name": zip_name}


# Names a browser gives a ZIP it packs itself: not the person's name for the run.
_GENERIC_ZIP = re.compile(r"^(catalog|parts|files|archive|download|upload|batch|new folder|untitled)( ?\(\d+\))?$", re.I)


def run_name(zip_name: Optional[str], list_name: Optional[str]) -> Optional[str]:
    """The run's name: the ZIP's (or folder's) name, else the parts list's, without extensions."""
    def stem(n: Optional[str]) -> str:
        base = os.path.basename((n or "").replace("\\", "/")).strip()
        return re.sub(r"\.(zip|csv|tsv|txt)$", "", base, flags=re.I).strip()[:120]

    z = stem(zip_name)
    if z and not _GENERIC_ZIP.match(z):
        return z
    return stem(list_name) or None


class CatalogRunRefused(DirectUploadPreparationValidationError):
    """The worker refused a run from a stored ZIP (the allowance, one free run at a
    time, the phone or work-email gate): its code, message and the allowance's
    details. A refusal a retry can't change, so the preparation ends at once."""

    def __init__(self, code: str, message: str, detail: Optional[dict] = None):
        super().__init__(403, code, message)
        self.refusal = dict(detail or {})


def refusal_of(exc: Exception) -> CatalogRunRefused:
    """The allowance's HTTPException as the worker's refusal."""
    detail = getattr(exc, "detail", None)
    detail = detail if isinstance(detail, dict) else {"message": str(detail or exc)}
    return CatalogRunRefused(str(detail.get("code") or "catalog_run_refused"),
                             str(detail.get("message") or "The catalog run wasn't started."), detail)


def prepare_items(batch: Batch, items_data: list[dict]) -> None:
    """Worker: each part's quantities and material, from the options the request kept."""
    opts = (batch.manifest_json or {}).get(PENDING_KEY) or {}
    apply_catalog_meta(
        batch, items_data, free=bool(opts.get("free")), material_class=opts.get("material_class"),
        quantity=int(opts.get("quantity") or DEFAULT_RUN_QUANTITY), parts_list=opts.get("parts_list"),
        list_name=opts.get("list_name"), zip_name=opts.get("zip_name"),
    )


async def reserve_prepared_run(session: AsyncSession, batch: Batch) -> None:
    """Worker: reserve the run's new parts once its items exist (raises ``CatalogRunRefused``).

    The account's allowance is read now, not when the ZIP was posted: a plan
    that changed since applies. The reservation is kept on the run's facts so
    the app can say how many parts were new and how many are left.
    """
    from fastapi import HTTPException

    from src.auth.catalog_allowance import _access

    access = await _access(session, batch.user_id)
    try:
        reservation = await reserve_catalog_run(session, batch.user_id, batch, access)
    except HTTPException as exc:
        raise refusal_of(exc) from exc
    manifest_json = dict(batch.manifest_json or {})
    catalog = dict(manifest_json.get("catalog") or {})
    catalog["free"] = access.free
    if reservation is not None:
        catalog["reservation"] = {"new": reservation.new, "reruns": reservation.reruns,
                                  "cap": reservation.cap, "remaining": reservation.remaining}
    manifest_json["catalog"] = catalog
    batch.manifest_json = manifest_json


# The part of a cost decision the board reads (derive_part_row), cut down in the
# database. A decision's ``estimates`` (every process at every quantity, with
# each driver's provenance) is ~170 KB of its ~190 KB; the board needs only a
# few fields of each estimate and the name and value of three of its drivers.
# Other keys are kept exactly as stored (present, absent or JSON null), so a row
# reads the same as from the whole record (tests/test_catalog_run_e2e.py
# compares them).
_BOARD_DECISION_KEYS = ("status", "reason", "verification", "geometry", "specs")
_BOARD_DECISION_BLOCK_KEYS = ("recommendation", "make_now_process", "options")
_BOARD_ESTIMATE_KEYS = ("process", "quantity", "material", "unit_cost_usd", "dfm_ready", "dfm_blockers", "material_mass")
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

    # Files the run checked body by body: completed, no decision of their own.
    from src.services.catalog_bodies import read_file_bodies

    candidates = [(it[1], it[6]) for it in items if it[2] == "completed" and it[7] is None and not it[3] and it[6]]
    found = await asyncio.gather(*(read_file_bodies(batch.org_id, batch.ulid, h) for _f, h in candidates))
    split = {f: e for (f, _h), e in zip(candidates, found) if isinstance(e, dict)}
    split_decisions, split_analyses = await _split_records(session, batch.org_id, split)
    signers = await signoff_service.names_for(
        session, [it[12] for it in items] + [d["governance"]["approved_by_user_id"] for d in split_decisions.values()])
    buy_prices = await _buy_prices(session, batch.org_id, [it[8] for it in items if it[8]] + [
        v["decision"]["mesh_hash"] for v in split_decisions.values()])
    now = datetime.now(timezone.utc)

    def _gov(approval, signer, signed_at, signoff_note, stale_at, stale_reason) -> dict:
        if stale_at is not None and stale_at.tzinfo is None:
            stale_at = stale_at.replace(tzinfo=timezone.utc)
        return {"approval_status": approval, "approved_by_user_id": signer,
                "approved_at": signed_at.isoformat() if signed_at else None, "approval_note": signoff_note,
                "is_stale": stale_at is not None and stale_at <= now, "stale_reason": stale_reason,
                "stale_at": stale_at.isoformat() if stale_at else None}

    rows = []
    split_files = []
    for (item_ulid, filename, status, error_message, duration_ms,
         analysis_ulid, analysis_hash, decision_ulid, decision_hash, decision_slice,
         disposition, approval, signer, signed_at, signoff_note, stale_at, stale_reason) in items:
        entry = split.get(filename)
        if entry and status == "completed":
            # A file of several bodies: a row per body shape, never one block.
            rows.extend(body_rows(
                item={"ulid": item_ulid, "filename": filename}, entry=entry, parent_meta=per_file.get(filename),
                analyses=split_analyses, decisions={k: v["decision"] for k, v in split_decisions.items()},
                machines=machines, default_quantity=default_qty,
                governance_of=lambda dec: {**split_decisions[dec["ulid"]]["governance"], "signers": signers},
                buy_prices=buy_prices,
            ))
            split_files.append(split_file_note(filename, entry))
            continue
        gov = _gov(approval, signer, signed_at, signoff_note, stale_at, stale_reason)
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
            buy_price=buy_prices.get(decision_hash) if decision_hash else None,
        ))
        rows[-1]["name"] = filename
    manifest = batch.manifest_json or {}
    has_list = bool(meta.get("parts_list"))
    scoped = [r for r in rows if r.get("listed")] if has_list else rows
    unlisted = [r for r in rows if not r.get("listed")] if has_list else []
    # A run from a stored ZIP is unpacked on the worker first (input_mode
    # direct_upload until then); a refusal there is kept as the run's failure.
    preparing = batch.input_mode == "direct_upload" and batch.status not in ("completed", "failed", "cancelled")
    return {
        "batch_id": batch.ulid,
        "status": batch.status,
        "preparing": preparing,
        "failure": manifest.get("failure") if batch.status == "failed" else None,
        "reservation": meta.get("reservation"),
        "parts": None if preparing else max(0, (batch.total_items or 0) - (batch.failed_items or 0)),
        "free": bool(meta.get("free")),
        "material_class": meta.get("material_class"),
        "quantity": default_qty,
        "parts_list": meta.get("parts_list"),
        "unmatched": meta.get("unmatched") or [],
        "machines": machines,
        "machine_count": sum(int(m.get("count") or 1) for m in machines),
        "name": meta.get("name"),
        "files": len(items),
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "rows": rows,
        "split_files": split_files,
        # With a parts list, the totals and the answer cover the parts on it;
        # files in the ZIP it doesn't name are kept apart (``unlisted``).
        "has_list": has_list,
        "totals": bucket_totals(scoped),
        "breakdown": bucket_breakdown(scoped),
        "unlisted": {"parts": len(unlisted), "totals": bucket_totals(unlisted)} if has_list else None,
        "answer": make_or_buy_answer(scoped),
        "bucket_rule": BUCKET_RULE,
    }


def make_or_buy_answer(rows: list[dict]) -> dict:
    """The run's answer in counts and money: make N, buy M, the rest, and the saving.

    ``saving_usd``: what making the in-house parts saves against what you pay
    today, summed over the in-house parts with a current price (each part's
    saving × its quantity); None when no in-house part has one. Nothing is
    summed from a model price: the saving is against real prices only.
    """
    def n(*keys: str) -> int:
        return sum(1 for r in rows if r.get("bucket") in keys)

    make = [r for r in rows if r.get("bucket") == "in_house"]
    saved = [r for r in make if isinstance(r.get("saving"), dict)]
    return {
        "parts": len(rows),
        "make": len(make),
        "buy": n("outside"),
        "new_machine": n("new_machine"),
        "cant_make": n("cant_make"),
        "not_checked": n("not_checked"),
        "not_sorted": n("not_sorted"),
        "checking": n("checking"),
        "undecided": n("cant_make", "not_checked", "not_sorted", "checking"),
        "with_price": sum(1 for r in rows if r.get("current_price")),
        "saving_usd": round(sum(r["saving"]["total"] for r in saved), 2) if saved else None,
        "saving_parts": len(saved),
        "make_without_price": len(make) - len(saved),
        "make_cost_usd": round(sum(r["total_cost_usd"] for r in make if _num(r.get("total_cost_usd")) is not None), 2)
        if make else None,
    }


async def _split_records(session: AsyncSession, org_id: str, split: dict) -> tuple[dict, dict]:
    """The decisions (board slice + sign-off) and analyses of the bodies the run split files into."""
    ulids = [d["decision_ulid"] for e in split.values() for d in (e.get("designs") or []) if d.get("decision_ulid")]
    ids = [int(d["analysis_id"]) for e in split.values() for d in (e.get("designs") or [])
           if isinstance(d.get("analysis_id"), int)]
    decisions: dict = {}
    analyses: dict = {}
    if ulids:
        for (ulid, mesh_hash, slice_, disposition, approval, signer, signed_at, note, stale_at,
             stale_reason) in (await session.execute(
                select(CostDecision.ulid, CostDecision.mesh_hash, literal_column(_BOARD_DECISION_SQL, type_=JSONB),
                       CostDecision.user_disposition, CostDecision.approval_status, CostDecision.approved_by_user_id,
                       CostDecision.approved_at, CostDecision.approval_note, CostDecision.stale_at,
                       CostDecision.stale_reason)
                .where(CostDecision.ulid.in_(ulids), CostDecision.org_id == org_id))).all():
            now = datetime.now(timezone.utc)
            if stale_at is not None and stale_at.tzinfo is None:
                stale_at = stale_at.replace(tzinfo=timezone.utc)
            decisions[ulid] = {
                "decision": {"ulid": ulid, "mesh_hash": mesh_hash, "result_json": slice_ or {}},
                "governance": {"approval_status": approval, "approved_by_user_id": signer,
                               "approved_at": signed_at.isoformat() if signed_at else None, "approval_note": note,
                               "is_stale": stale_at is not None and stale_at <= now, "stale_reason": stale_reason,
                               "stale_at": stale_at.isoformat() if stale_at else None,
                               "user_disposition": disposition},
            }
    if ids:
        for aid, ulid, mesh_hash in (await session.execute(
                select(Analysis.id, Analysis.ulid, Analysis.mesh_hash)
                .where(Analysis.id.in_(ids), Analysis.org_id == org_id))).all():
            analyses[aid] = {"ulid": ulid, "mesh_hash": mesh_hash}
    return decisions, analyses


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
    "name,description,on_parts_list,current_price_usd_each,current_price_from,make_usd_each,make_on,"
    "buy_usd_each,buy_from,saving_usd_each,saving_usd_total,"
    "specs,supplier_must_hold,outcome,signed_off_by,signed_off_at,signoff_out_of_date\n"
)

_PRICE_FROM = {"you": "your price on the part", "parts_list": "the parts list", "model": "model price"}


def _buy_from(buy: Optional[dict]) -> Optional[str]:
    if not buy:
        return None
    if buy.get("source") != "model":
        return _PRICE_FROM.get(buy.get("source"))
    proc = buy.get("process")
    if not proc:
        return "model price"
    return f"{process_words(proc)} outside" + (" (a shop running your process)" if buy.get("same_process") else "")


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
            f(r.get("unit_cost_usd")), f(r.get("total_cost_usd")), f(note), f(r.get("status")),
            f(plain_error(r.get("error"))),
            f(mat.get("used_kg_each")), f(r.get("used_kg_total")),
            f(r.get("name") or r.get("filename")), f(r.get("description")), f(r.get("listed")) if "listed" in r else "",
            f((r.get("current_price") or {}).get("usd_each")),
            f(_PRICE_FROM.get((r.get("current_price") or {}).get("source"))),
            f((r.get("make") or {}).get("unit_cost_usd")), f((r.get("make") or {}).get("machine")),
            f((r.get("buy") or {}).get("unit_cost_usd")), f(_buy_from(r.get("buy"))),
            f((r.get("saving") or {}).get("each")), f((r.get("saving") or {}).get("total")),
            f("; ".join((r.get("specs") or {}).get("summary") or []) or None),
            f("; ".join((r.get("specs") or {}).get("supplier_must_hold") or []) or None),
            f(OUTCOME_WORDS.get(r.get("outcome"), r.get("outcome"))),
            f((r.get("signoff") or {}).get("by")), f((r.get("signoff") or {}).get("at")),
            f((r.get("signoff") or {}).get("stale")) if r.get("signoff") else "",
        ]) + "\n"
