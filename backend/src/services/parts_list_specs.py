"""Part specs in a parts list (CSV or a BOM export): finish, Ra, heat treatment,
inspection and the certifications the supplier must hold.

A catalog run's parts list already names each file's quantity and material
(catalog_run_service.parse_parts_list). These columns, when present, give each
part its declared specs too (src.costing.part_specs), so a run prices and
gates them like specs declared on the part's page. Column names and cell words
are matched loosely ("Surface finish: Type II anodize + bead blast", "Ra (µin):
32", "Heat treat: Q&T", "Inspection: FAI", "Certifications: AS9100, NADCAP (heat
treating), ITAR").

A spec cell never refuses a run. A phrase ScaleCAD doesn't price ("Black
oxide", "EN 10204 3.1", "Roundness check", an Ra with no unit) is kept as
written in the row's ``spec_notes`` and listed as not priced; it is never
guessed into a priced spec. A colour after an anodize ("Type II anodize,
black") is part of that anodize: priced as the anodize, the colour kept as a
note.
"""
from __future__ import annotations

import re
from typing import Optional

_FINISH_HEADERS = ("finish", "finishes", "surface finish", "surface_finish", "coating", "surface treatment")
_RA_HEADERS = ("ra", "ra (um)", "ra (µm)", "ra um", "ra µm", "ra_um", "roughness", "surface roughness",
               "ra (uin)", "ra (µin)", "ra uin", "ra µin", "ra_uin", "roughness (uin)", "roughness (um)")
_HEAT_HEADERS = ("heat treatment", "heat treat", "heat_treatment", "heat_treat", "ht")
_INSPECTION_HEADERS = ("inspection", "inspection level", "inspection_level", "qa", "quality")
_CERT_HEADERS = ("certifications", "certification", "certs", "supplier certifications",
                 "required certifications", "supplier must hold")

# Words a parts list uses for each spec, checked in order (hard anodize before anodize).
_FINISH_WORDS: tuple = (
    ("anodize_iii", re.compile(r"hard\s*(coat|anodi[sz])|type\s*(iii|3)\b|\bhardcoat", re.I)),
    ("anodize_ii", re.compile(r"anodi[sz]|type\s*(ii|2)\b", re.I)),
    ("bead_blast", re.compile(r"bead|blast|grit", re.I)),
    ("passivate", re.compile(r"passivat", re.I)),
    ("electropolish", re.compile(r"electro\s*(?:-\s*)?polish", re.I)),
    ("powder_coat", re.compile(r"powder", re.I)),
    ("plating", re.compile(r"plat(e|ed|ing)\b|electroless|nickel|chrom|zinc|cadmium|e-?coat", re.I)),
    ("as_machined", re.compile(r"as[\s-]*machined|none|bare|no finish", re.I)),
)
_HEAT_WORDS: tuple = (
    ("hip", re.compile(r"\bhip\b|isostatic", re.I)),
    ("stress_relief", re.compile(r"stress[\s-]*reli", re.I)),
    # 17-4 PH / 15-5 PH conditions (H900 … H1150) are solution treated and aged.
    ("solution_age", re.compile(r"solution|\bage(d|ing)?\b|\bsta\b|precipitation|\bh\s?(900|925|1025|1075|1100|1150)(-?m)?\b", re.I)),
    ("quench_temper", re.compile(r"quench|temper|q\s*&\s*t|through[\s-]*harden", re.I)),
    ("case_harden", re.compile(r"case|carburi[sz]|nitrid|carbonitrid", re.I)),
)
_INSPECTION_WORDS: tuple = (
    ("fai_as9102", re.compile(r"\bfai\b|as\s*9102|first[\s-]*article", re.I)),
    ("cmm_report", re.compile(r"\bcmm\b", re.I)),
    ("full_100", re.compile(r"100\s*%|100 percent|every part|full inspection", re.I)),
    ("standard", re.compile(r"standard|normal|sample|none", re.I)),
)
_CERT_WORDS: tuple = (
    ("as9100", re.compile(r"as\s*9100", re.I)),
    ("iso9001", re.compile(r"iso\s*9001", re.I)),
    ("nadcap", re.compile(r"nadcap", re.I)),
    ("itar", re.compile(r"\bitar\b", re.I)),
)
_NADCAP_WORDS: tuple = (
    ("heat_treating", re.compile(r"heat", re.I)),
    ("chemical_processing", re.compile(r"chemical|anodi|plat|passiv", re.I)),
    ("nondestructive_testing", re.compile(r"\bndt\b|non[\s-]*destructive", re.I)),
    ("coatings", re.compile(r"coating", re.I)),
    ("welding", re.compile(r"weld", re.I)),
    ("measurement_inspection", re.compile(r"measure|inspection", re.I)),
)
# An Ra cell, read with fullmatch on its words with whitespace runs as one space
# (plain_cell): a number, a unit or none, "Ra" before or after. Each piece
# matches a bounded run, so reading it is linear in the cell however it is written.
_RA_CELL = re.compile(r"(?:ra ?)?([0-9]+(?:\.[0-9]+)?|\.[0-9]+) ?(µm|um|micron|microns|µin|uin|microinch(?:es)?|µ\"|) ?(?:ra)?", re.I)
# The longest Ra cell read as a number; a longer one is kept as a note.
MAX_RA_CHARS = 40


# A colour named after an anodize ("Type II anodize, black") is that anodize's colour.
_COLOUR = re.compile(r"^(black|clear|natural|red|blue|gold|green|grey|gray|bronze|olive|orange|purple|violet|"
                     r"silver|yellow|dyed|undyed|colou?r\b.*)$", re.I)
SPEC_COLUMN_NAMES = {"finish": "finish", "ra": "Ra", "heat": "heat treatment", "inspection": "inspection",
                     "certs": "certifications"}


def _note(column: str, value: str, why: str) -> dict:
    return {"column": column, "value": value, "why": why}


def _spec_words(raw: str, table: tuple, what: str, row_num: int, notes: Optional[list] = None) -> list[str]:
    """Each comma/semicolon/plus-separated phrase mapped to one spec key, in order.

    A phrase that maps to none goes to ``notes`` (not priced); without ``notes``
    it raises, naming the row (the single-cell reader's contract).
    """
    out: list[str] = []
    for phrase in re.split(r"[;,+/]|\bthen\b|\band\b", plain_cell(raw)):
        phrase = phrase.strip()
        if not phrase:
            continue
        hit = next((key for key, pattern in table if pattern.search(phrase)), None)
        if hit is None and out and out[-1] in ("anodize_ii", "anodize_iii") and _COLOUR.match(phrase):
            if notes is not None:
                notes.append(_note(what, phrase, "the anodize's colour; priced as the anodize"))
            continue
        if hit is None:
            if notes is None:
                raise ValueError(f"Row {row_num}: {what} '{phrase}' isn't one ScaleCAD knows")
            notes.append(_note(what, phrase, "not priced: ScaleCAD has no price for it yet"))
            continue
        if hit not in out:
            out.append(hit)
    return out


def plain_cell(raw: Optional[str]) -> str:
    """A cell's words with each run of spaces, tabs and line breaks read as one space.

    What every matcher here, and the parts list's price reader, reads.
    """
    return " ".join((raw or "").split())


class _RaError(ValueError):
    """An Ra cell ScaleCAD can't read as a number, naming the row; ``why`` is the reason alone."""

    def __init__(self, row_num: int, shown: str, why: str):
        self.shown, self.why = shown, why
        super().__init__(f"Row {row_num}: Ra '{shown}' {why}")


def _paren_split(raw: str) -> tuple[str, list[str]]:
    """``raw`` without its "(…)" groups, and the text inside each, in one pass.

    The same reading as ``re.sub(r"\\([^)]*\\)", "", raw)`` and
    ``re.findall(r"\\(([^)]*)\\)", raw)``: a group runs from a "(" to the next ")".
    """
    outside: list[str] = []
    inside: list[str] = []
    at = 0
    while True:
        opened = raw.find("(", at)
        closed = raw.find(")", opened + 1) if opened >= 0 else -1
        if closed < 0:
            break
        outside.append(raw[at:opened])
        inside.append(raw[opened + 1:closed])
        at = closed + 1
    outside.append(raw[at:])
    return "".join(outside), inside


def _ra_um(raw: str, header_unit: Optional[str], row_num: int) -> tuple[float, str]:
    written = plain_cell(raw)
    if len(written) > MAX_RA_CHARS:
        raise _RaError(row_num, written[:MAX_RA_CHARS] + "…",
                       f"is longer than {MAX_RA_CHARS} characters: write a number with µm or µin")
    m = _RA_CELL.fullmatch(written)
    if not m:
        raise _RaError(row_num, written, "isn't a number with µm or µin")
    value = float(m.group(1))
    unit_word = (m.group(2) or "").lower()
    unit = ("uin" if unit_word.startswith(("µin", "uin", "microinch")) or unit_word == 'µ"'
            else "um" if unit_word else header_unit)
    if unit is None:
        raise _RaError(row_num, written, f"needs a unit: write {written} µm or {written} µin")
    from src.costing.part_specs import UM_PER_UIN

    return (value * UM_PER_UIN if unit == "uin" else value), unit


def parse_spec_cells(cells: dict, row_num: int, *, ra_header_unit: Optional[str] = None,
                     notes: Optional[list] = None) -> Optional[dict]:
    """A parts-list row's spec columns as declared part specs (None when blank).

    ``cells`` maps ``finish`` / ``ra`` / ``heat`` / ``inspection`` / ``certs`` to the
    raw text. Each phrase that maps to a known spec is declared, and the result
    is validated like a spec declared on the part.

    With a ``notes`` list (a catalog run's parts list), nothing raises: a phrase
    or cell ScaleCAD can't price is appended there as ``{column, value, why}``
    and left out of the specs. Without one, anything it can't read raises a
    ``ValueError`` naming the row.
    """
    from src.costing.part_specs import normalize_part_specs

    lenient = notes is not None
    specs: dict = {}
    if cells.get("finish"):
        specs["finishes"] = _spec_words(cells["finish"], _FINISH_WORDS, "finish", row_num, notes)
    if cells.get("ra"):
        try:
            specs["ra_um"], specs["ra_unit"] = _ra_um(cells["ra"], ra_header_unit, row_num)
        except _RaError as exc:
            if not lenient:
                raise
            notes.append(_note("Ra", exc.shown, "not priced: " + exc.why))
    if cells.get("heat"):
        specs["heat_treatments"] = _spec_words(cells["heat"], _HEAT_WORDS, "heat treatment", row_num, notes)
    if cells.get("inspection"):
        specs["inspection"] = _spec_words(cells["inspection"], _INSPECTION_WORDS, "inspection", row_num, notes)
    if cells.get("certs"):
        outside, inside = _paren_split(cells["certs"])
        specs["certifications"] = _spec_words(outside, _CERT_WORDS, "certification", row_num, notes)
        named = " ".join(inside)
        if "nadcap" in specs["certifications"] and named.strip():
            specs["nadcap_processes"] = _spec_words(named, _NADCAP_WORDS, "NADCAP process", row_num, notes)
    specs = {k: v for k, v in specs.items() if v not in ([], None)}
    if not specs:
        return None
    try:
        return normalize_part_specs(specs)
    except ValueError as exc:
        if not lenient:
            raise ValueError(f"Row {row_num}: {exc}")
    # Keep every field that stands on its own; the one that doesn't is a note, as written.
    kept: dict = {}
    for key in ("finishes", "ra_um", "heat_treatments", "inspection", "certifications", "nadcap_processes"):
        if key not in specs:
            continue
        trial = {**kept, key: specs[key]}
        if key == "ra_um":
            trial["ra_unit"] = specs.get("ra_unit")
        if key == "certifications" and "nadcap_processes" in specs:
            trial["nadcap_processes"] = specs["nadcap_processes"]
        try:
            normalize_part_specs(trial)
        except ValueError as exc:
            column = {"finishes": "finish", "ra_um": "Ra", "heat_treatments": "heat treatment",
                      "inspection": "inspection", "certifications": "certifications",
                      "nadcap_processes": "certifications"}[key]
            cell_key = {"finish": "finish", "Ra": "ra", "heat treatment": "heat", "inspection": "inspection",
                        "certifications": "certs"}[column]
            notes.append(_note(column, (cells.get(cell_key) or "").strip(), f"not priced: {exc}"))
            continue
        kept = trial
    return normalize_part_specs(kept) if kept else None


def spec_columns(headers: list[str]) -> dict[str, Optional[int]]:
    """Where each spec column is in a parts list's header row: ``{finish, ra, heat, inspection, certs}`` to an index or None."""
    from src.services.catalog_run_service import _header_index

    return {key: _header_index(headers, names) for key, names in (
        ("finish", _FINISH_HEADERS), ("ra", _RA_HEADERS), ("heat", _HEAT_HEADERS),
        ("inspection", _INSPECTION_HEADERS), ("certs", _CERT_HEADERS))}


def attach(rows: list[dict], text: str) -> list[dict]:
    """rows (from parse_parts_list) with part_specs added from the same text.

    Reads the header and rows exactly as parse_parts_list does (same dialect,
    blank rows skipped, row numbers from 2). A list without spec columns comes
    back unchanged. Never raises over a spec cell: what ScaleCAD can't price is
    kept on the row as ``spec_notes`` (``[{column, value, why}]``).
    """
    from src.services.catalog_run_service import list_reader

    if text.startswith("﻿"):
        text = text[1:]
    reader = list_reader(text)
    try:
        headers = next(reader)
    except StopIteration:
        return rows
    spec_cols = spec_columns(headers)
    if all(i is None for i in spec_cols.values()):
        return rows
    ra_head = headers[spec_cols["ra"]].lower() if spec_cols["ra"] is not None else ""
    ra_header_unit = ("uin" if re.search(r"uin|µin|micro\s*inch", ra_head)
                      else "um" if re.search(r"(?:^|[^a-z])um\b|µm|micron", ra_head) else None)

    def cell(row: list, i: Optional[int]) -> str:
        return row[i].strip() if i is not None and i < len(row) and row[i] is not None else ""

    by_row = {r.get("row"): r for r in rows}
    for row_num, row in enumerate(reader, start=2):
        target = by_row.get(row_num)
        if target is None:
            continue
        notes: list = []
        specs = parse_spec_cells({k: cell(row, i) for k, i in spec_cols.items()}, row_num,
                                 ra_header_unit=ra_header_unit, notes=notes)
        if specs:
            target["part_specs"] = specs
        if notes:
            target["spec_notes"] = notes
    return rows


def not_priced(rows: list[dict]) -> list[dict]:
    """Every spec the list names that isn't priced: ``[{row, part, column, value, why}]``, in list order.

    An anodize's colour is priced with its anodize, so it isn't one (it stays on the row's notes).
    """
    out: list[dict] = []
    for r in rows:
        for n in r.get("spec_notes") or []:
            if str(n.get("why") or "").startswith("not priced"):
                out.append({"row": r.get("row"), "part": r.get("part_number") or r.get("file"), **n})
    return out


def note_text(note: dict) -> str:
    """One not-priced spec as a line: ``Finish: Black oxide (not priced)``."""
    column = str(note.get("column") or "spec")
    value = str(note.get("value") or "")
    why = str(note.get("why") or "")
    tail = "colour of the anodize" if why.startswith("the anodize's colour") else "not priced"
    return f"{column[:1].upper()}{column[1:]}: {value} ({tail})"
