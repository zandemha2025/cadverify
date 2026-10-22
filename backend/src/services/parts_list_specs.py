"""Part specs in a parts list (CSV or a BOM export): finish, Ra, heat treatment,
inspection and the certifications the supplier must hold.

A catalog run's parts list already names each file's quantity and material
(catalog_run_service.parse_parts_list). These columns, when present, give each
part its declared specs too (src.costing.part_specs), so a run prices and
gates them like specs declared on the part's page. Column names and cell words
are matched loosely ("Surface finish: Type II anodize + bead blast", "Ra (µin):
32", "Heat treat: Q&T", "Inspection: FAI", "Certifications: AS9100, NADCAP (heat
treating), ITAR"); a word ScaleCAD can't map names its row and the whole list is
refused, never guessed. A bare Ra number needs a unit in the cell or the header.
"""
from __future__ import annotations

import csv
import io
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
    ("electropolish", re.compile(r"electro\s*-?\s*polish", re.I)),
    ("powder_coat", re.compile(r"powder", re.I)),
    ("plating", re.compile(r"plat(e|ed|ing)\b|electroless|nickel|chrom|zinc|cadmium|e-?coat", re.I)),
    ("as_machined", re.compile(r"as[\s-]*machined|none|bare|no finish", re.I)),
)
_HEAT_WORDS: tuple = (
    ("hip", re.compile(r"\bhip\b|isostatic", re.I)),
    ("stress_relief", re.compile(r"stress[\s-]*reli", re.I)),
    ("solution_age", re.compile(r"solution|\bage(d|ing)?\b|\bsta\b|precipitation", re.I)),
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
_RA_CELL = re.compile(r"^\s*(?:ra\s*)?([0-9]*\.?[0-9]+)\s*(µm|um|micron|microns|µin|uin|microinch(?:es)?|µ\"|)\s*(?:ra)?\s*$", re.I)


def _spec_words(raw: str, table: tuple, what: str, row_num: int) -> list[str]:
    """Each comma/semicolon/plus-separated phrase mapped to one spec key, in order."""
    out: list[str] = []
    for phrase in re.split(r"[;,+/]|\bthen\b|\band\b", raw):
        phrase = phrase.strip()
        if not phrase:
            continue
        hit = next((key for key, pattern in table if pattern.search(phrase)), None)
        if hit is None:
            raise ValueError(f"Row {row_num}: {what} '{phrase}' isn't one ScaleCAD knows")
        if hit not in out:
            out.append(hit)
    return out


def _ra_um(raw: str, header_unit: Optional[str], row_num: int) -> tuple[float, str]:
    m = _RA_CELL.match(raw or "")
    if not m:
        raise ValueError(f"Row {row_num}: Ra '{raw.strip()}' isn't a number with µm or µin")
    value = float(m.group(1))
    unit_word = (m.group(2) or "").lower()
    unit = ("uin" if unit_word.startswith(("µin", "uin", "microinch")) or unit_word == 'µ"'
            else "um" if unit_word else header_unit)
    if unit is None:
        raise ValueError(f"Row {row_num}: Ra '{raw.strip()}' needs a unit: write {raw.strip()} µm or {raw.strip()} µin")
    from src.costing.part_specs import UM_PER_UIN

    return (value * UM_PER_UIN if unit == "uin" else value), unit


def parse_spec_cells(cells: dict, row_num: int, *, ra_header_unit: Optional[str] = None) -> Optional[dict]:
    """A parts-list row's spec columns as declared part specs (None when blank).

    ``cells`` maps ``finish`` / ``ra`` / ``heat`` / ``inspection`` / ``certs`` to the
    raw text. Every phrase must map to a known spec, and the result is validated
    like a spec declared on the part; anything ScaleCAD can't read names the row.
    """
    from src.costing.part_specs import normalize_part_specs

    specs: dict = {}
    if cells.get("finish"):
        specs["finishes"] = _spec_words(cells["finish"], _FINISH_WORDS, "finish", row_num)
    if cells.get("ra"):
        specs["ra_um"], specs["ra_unit"] = _ra_um(cells["ra"], ra_header_unit, row_num)
    if cells.get("heat"):
        specs["heat_treatments"] = _spec_words(cells["heat"], _HEAT_WORDS, "heat treatment", row_num)
    if cells.get("inspection"):
        specs["inspection"] = _spec_words(cells["inspection"], _INSPECTION_WORDS, "inspection", row_num)
    if cells.get("certs"):
        raw = cells["certs"]
        specs["certifications"] = _spec_words(re.sub(r"\([^)]*\)", "", raw), _CERT_WORDS, "certification", row_num)
        named = " ".join(re.findall(r"\(([^)]*)\)", raw))
        if "nadcap" in specs["certifications"] and named.strip():
            specs["nadcap_processes"] = _spec_words(named, _NADCAP_WORDS, "NADCAP process", row_num)
    if not specs:
        return None
    try:
        return normalize_part_specs(specs)
    except ValueError as exc:
        raise ValueError(f"Row {row_num}: {exc}")


def attach(rows: list[dict], text: str) -> list[dict]:
    """rows (from parse_parts_list) with part_specs added from the same text.

    Reads the header and rows exactly as parse_parts_list does (same dialect
    sniffing, blank rows skipped, row numbers from 2). A list without spec
    columns comes back unchanged. Raises ValueError naming the row.
    """
    from src.services.catalog_run_service import _header_index

    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        headers = next(reader)
    except StopIteration:
        return rows
    spec_cols = {key: _header_index(headers, names) for key, names in (
        ("finish", _FINISH_HEADERS), ("ra", _RA_HEADERS), ("heat", _HEAT_HEADERS),
        ("inspection", _INSPECTION_HEADERS), ("certs", _CERT_HEADERS))}
    if all(i is None for i in spec_cols.values()):
        return rows
    ra_head = headers[spec_cols["ra"]].lower() if spec_cols["ra"] is not None else ""
    ra_header_unit = ("uin" if re.search(r"uin|µin|micro\s*inch", ra_head)
                      else "um" if re.search(r"\bum\b|µm|micron", ra_head) else None)

    def cell(row: list, i: Optional[int]) -> str:
        return row[i].strip() if i is not None and i < len(row) and row[i] is not None else ""

    by_row = {r.get("row"): r for r in rows}
    for row_num, row in enumerate(reader, start=2):
        target = by_row.get(row_num)
        if target is None:
            continue
        specs = parse_spec_cells({k: cell(row, i) for k, i in spec_cols.items()}, row_num,
                                 ra_header_unit=ra_header_unit)
        if specs:
            target["part_specs"] = specs
    return rows
