"""A customer's actuals, read the way they have them and matched to checked parts.

The validation moment starts here. An ops owner exports what their shop really
did (a CSV or an Excel sheet from the ERP / MES): a part number or file name, a
quantity, machine hours and/or cost per part, the process, maybe the machine and
a date. This module:

* reads the file (CSV with any of , ; tab, or the first sheet of an .xlsx, read
  with the standard library and size caps; no macros, no formulas evaluated);
* guesses which column is which from the header names, and which method each
  process value means (both prefilled, both editable by the person importing);
* matches every row to one of the organization's checked parts, by file hash,
  by part number (declared on the part, given in a catalog run's parts list, or
  the record's label), or by file name. A row that fits more than one part is
  ASKED about, never guessed; a row that fits none says why;
* imports the matched rows through the existing ground-truth create path, so
  they share its org scoping, validation, dedup and stand-in rules.

Org scoping: every read of parts, part numbers and machines is
``WHERE org_id = caller-org``. A row can only ever match the caller's parts.
"""
from __future__ import annotations

import csv
import io
import math
import os
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analysis.models import ProcessType

MAX_ROWS = 5000
MAX_COLUMNS = 200
_XLSX_MAX_UNZIPPED = 60 * 1024 * 1024
_XLSX_MAX_RATIO = 200

# ---------------------------------------------------------------------------
# Fields a column can map to
# ---------------------------------------------------------------------------

FIELDS: dict[str, str] = {
    "part": "Part number or file name",
    "file_name": "File name",
    "part_number": "Part number",
    "file_hash": "File hash (SHA-256)",
    "quantity": "Quantity",
    "machine_hours": "Machine hours per part",
    "machine_hours_total": "Machine hours for the whole quantity",
    "cost_each": "Cost per part",
    "cost_total": "Cost for the whole quantity",
    "process": "Process",
    "machine": "Machine",
    "date": "Date",
    "reference": "Job, PO or invoice no.",
    "notes": "Notes",
    "kind": "Kind (actual, quote, test)",
}

IDENTITY_FIELDS = ("part", "file_name", "part_number", "file_hash")

# Header words per field, most specific first. Compared after lower-casing and
# collapsing everything that isn't a letter or digit to one space.
_HEADER_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("file_hash", ("sha256", "sha 256", "file hash", "file sha256", "evidence sha256", "hash", "checksum")),
    ("machine_hours_total", ("total machine hours", "machine hours total", "total hours", "job hours",
                             "total run hours", "hours total", "total machine time")),
    ("machine_hours", ("actual machine hours", "machine hours", "machine hrs", "machine hours each",
                       "hours per part", "hours each", "hrs each", "hrs per part", "machine time",
                       "run time", "runtime", "cycle time", "actual hours", "hours", "hrs")),
    ("cost_total", ("total cost", "job cost", "extended cost", "line total", "cost total", "total actual cost")),
    ("cost_each", ("actual unit cost usd", "actual cost each", "cost each", "unit cost", "cost per part",
                   "cost per unit", "actual unit cost", "cost part", "price each", "unit price", "actual cost", "cost")),
    ("file_name", ("file name", "filename", "file", "cad file", "model file", "model", "cad")),
    ("part_number", ("part number", "part no", "part num", "part nr", "pn", "p n", "item number", "item no",
                     "item", "part id", "material number", "article")),
    ("part", ("part", "part id")),
    ("quantity", ("quantity", "qty", "order qty", "order quantity", "lot size", "parts made", "qty made",
                  "pieces", "pcs", "count", "units")),
    ("process", ("process", "method", "operation", "routing", "manufacturing process")),
    ("machine", ("machine", "machine name", "work center", "workcenter", "work centre", "resource",
                 "equipment", "asset", "printer")),
    ("date", ("invoice date", "completed", "completion date", "finish date", "date completed", "ship date",
              "job date", "date")),
    ("reference", ("source", "job number", "job no", "job", "work order", "wo", "po", "po number",
                   "invoice", "invoice no", "reference", "ref", "vendor quote id")),
    ("notes", ("notes", "note", "comment", "comments", "remarks")),
    ("kind", ("source type", "kind", "type of record", "record type")),
]


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (h or "").lower()).strip()


def guess_mapping(headers: list[str]) -> dict[str, int]:
    """Which column each field most likely is, from the header names alone.

    Each column is used once; a field with no plausible header is left out (the
    person importing picks it). The existing template's column names map too.
    """
    norm = [_norm_header(h) for h in headers]
    taken: set[int] = set()
    out: dict[str, int] = {}
    # Exact header matches first (any field), then "contains" matches.
    for exact in (True, False):
        for fieldname, aliases in _HEADER_ALIASES:
            if fieldname in out:
                continue
            for alias in aliases:
                hit = None
                for i, h in enumerate(norm):
                    if i in taken or not h:
                        continue
                    if (h == alias) if exact else (len(alias) > 3 and re.search(rf"\b{re.escape(alias)}\b", h)):
                        hit = i
                        break
                if hit is not None:
                    out[fieldname] = hit
                    taken.add(hit)
                    break
    return out


def hours_unit_of(header: Optional[str]) -> str:
    """'min' when the hours column's header says minutes, else 'h'."""
    h = _norm_header(header or "")
    return "min" if re.search(r"\b(min|mins|minute|minutes)\b", h) else "h"


# ---------------------------------------------------------------------------
# Process words -> engine process ids
# ---------------------------------------------------------------------------

KNOWN_PROCESSES = frozenset(p.value for p in ProcessType)

_PROCESS_WORDS: list[tuple[str, str]] = [
    (r"\b5[\s-]*ax", "cnc_5axis"),
    (r"\bfive[\s-]*axis", "cnc_5axis"),
    (r"\b3[\s-]*ax", "cnc_3axis"),
    (r"\bthree[\s-]*axis", "cnc_3axis"),
    (r"\bwire\b.*\bedm\b|\bwedm\b|\bedm\b", "wire_edm"),
    (r"\bturn|\blathe|\bcnc\s*turn", "cnc_turning"),
    (r"\bmill|\bvmc\b|\bhmc\b|\bmachining\b|\bcnc\b", "cnc_3axis"),
    (r"\bfdm\b|\bfff\b|\bfilament", "fdm"),
    (r"\bdlp\b", "dlp"),
    (r"\bsla\b|\bresin|\bstereolith", "sla"),
    (r"\bmjf\b|multi\s*jet", "mjf"),
    (r"\bsls\b|selective laser sinter|nylon powder", "sls"),
    (r"\bslm\b", "slm"),
    (r"\bdmls\b|metal powder|laser powder bed|\blpbf\b|metal print", "dmls"),
    (r"\bebm\b|electron[\s-]*beam", "ebm"),
    (r"binder[\s-]*jet", "binder_jetting"),
    (r"\bwaam\b|wire[\s-]*arc", "waam"),
    (r"\bded\b|directed energy|metal deposition", "ded"),
    (r"injection|\bmold|\bmould", "injection_molding"),
    (r"die[\s-]*cast", "die_casting"),
    (r"investment|lost[\s-]*wax", "investment_casting"),
    (r"sand[\s-]*cast", "sand_casting"),
    (r"\bforg", "forging"),
    (r"sheet|laser[\s-]*cut|\bbrake\b|\bbend|\bpunch|fabricat", "sheet_metal"),
]


def guess_process(raw: Optional[str]) -> Optional[str]:
    """The engine process a free-text process value most likely means, or None."""
    v = (raw or "").strip().lower()
    if not v:
        return None
    if v in KNOWN_PROCESSES:
        return v
    compact = v.replace(" ", "_").replace("-", "_")
    if compact in KNOWN_PROCESSES:
        return compact
    for pattern, process in _PROCESS_WORDS:
        if re.search(pattern, v):
            return process
    return None


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


class TableError(ValueError):
    """The file can't be read as a table; the message says why in plain words."""


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]          # data rows only, each padded to len(headers)
    lines: list[int]               # the file line (CSV) or sheet row (XLSX) of each data row
    kind: str                      # "csv" | "xlsx"
    notes: list[str] = field(default_factory=list)


def read_table(filename: str, data: bytes) -> Table:
    """A CSV or the first sheet of an .xlsx, as header + rows of text."""
    name = (filename or "").lower()
    if not data:
        raise TableError("The file is empty.")
    if name.endswith(".xls") or data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise TableError("This is an old Excel file (.xls). Save it as .xlsx or CSV and import that.")
    if name.endswith((".xlsx", ".xlsm")) or data[:4] == b"PK\x03\x04":
        grid = _read_xlsx(data)
        kind = "xlsx"
        notes: list[str] = []
    else:
        text, notes = _decode(data)
        grid = _read_csv(text)
        kind = "csv"
    # Header: the first row with at least two non-empty cells.
    start = None
    for i, (line, row) in enumerate(grid):
        if sum(1 for c in row if c.strip()) >= 2:
            start = i
            break
    if start is None:
        raise TableError("No header row found: the first row with column names needs at least two columns.")
    header_line, headers = grid[start]
    headers = [h.strip() for h in headers][:MAX_COLUMNS]
    while headers and not headers[-1]:
        headers.pop()
    if len(headers) < 2:
        raise TableError("The header row needs at least two named columns.")
    rows: list[list[str]] = []
    lines: list[int] = []
    for line, row in grid[start + 1:]:
        cells = [(c or "").strip() for c in row[: len(headers)]]
        if not any(cells):
            continue
        cells += [""] * (len(headers) - len(cells))
        rows.append(cells)
        lines.append(line)
        if len(rows) > MAX_ROWS:
            raise TableError(f"The file has more than {MAX_ROWS:,} rows. Split it and import each part.")
    if not rows:
        raise TableError("The file has a header row but no rows under it.")
    return Table(headers=headers, rows=rows, lines=lines, kind=kind, notes=notes)


def _decode(data: bytes) -> tuple[str, list[str]]:
    try:
        return data.decode("utf-8-sig"), []
    except UnicodeDecodeError:
        # Excel on Windows saves CSV as Windows-1252 by default.
        return data.decode("cp1252", errors="replace"), [
            "Read as Windows-1252 text (the file isn't UTF-8). Check accented names look right."
        ]


def _read_csv(text: str) -> list[tuple[int, list[str]]]:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    out: list[tuple[int, list[str]]] = []
    try:
        for row in reader:
            out.append((reader.line_num, row))
            if len(out) > MAX_ROWS + 50:
                break
    except csv.Error as exc:
        raise TableError(f"The CSV couldn't be read near line {reader.line_num}: {exc}.") from exc
    return out


_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DATE_FMT_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 30, 36, 45, 46, 47, 50, 57}


def _xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    raw = zf.read(name)
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise TableError("This spreadsheet carries XML features ScaleCAD doesn't read. Save it as CSV and import that.")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise TableError("The spreadsheet couldn't be read. Save it as CSV and import that.") from exc


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return -1
    n = 0
    for ch in letters.group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _excel_date(serial: float) -> str:
    return (datetime(1899, 12, 30) + timedelta(days=float(serial))).date().isoformat()


def _num_text(v: str) -> str:
    try:
        f = float(v)
    except ValueError:
        return v
    if math.isfinite(f) and f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(f)


def _read_xlsx(data: bytes) -> list[tuple[int, list[str]]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise TableError("The spreadsheet couldn't be opened. Save it as .xlsx or CSV again and import that.") from exc
    infos = zf.infolist()
    unzipped = sum(i.file_size for i in infos)
    if unzipped > _XLSX_MAX_UNZIPPED or unzipped > _XLSX_MAX_RATIO * max(1, len(data)):
        raise TableError("The spreadsheet is too large to read. Save the sheet as CSV and import that.")
    names = {i.filename for i in infos}
    if "xl/workbook.xml" not in names:
        raise TableError("This file isn't an Excel workbook. Import a .xlsx or CSV.")

    wb = _xml(zf, "xl/workbook.xml")
    sheets = wb.find(f"{_NS}sheets")
    if sheets is None or not len(sheets):
        raise TableError("The workbook has no sheets.")
    rid = sheets[0].get(f"{_REL_NS}id")
    target = "xl/worksheets/sheet1.xml"
    if "xl/_rels/workbook.xml.rels" in names and rid:
        rels = _xml(zf, "xl/_rels/workbook.xml.rels")
        for rel in rels.iter(f"{_PKG_REL_NS}Relationship"):
            if rel.get("Id") == rid:
                t = (rel.get("Target") or "").lstrip("/")
                target = t if t.startswith("xl/") else f"xl/{t}"
                break
    target = os.path.normpath(target).replace("\\", "/")
    if not target.startswith("xl/") or target not in names:
        raise TableError("The workbook's first sheet couldn't be found.")

    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for si in _xml(zf, "xl/sharedStrings.xml").iter(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))

    date_styles: set[int] = set()
    if "xl/styles.xml" in names:
        st = _xml(zf, "xl/styles.xml")
        custom: dict[int, bool] = {}
        nf = st.find(f"{_NS}numFmts")
        if nf is not None:
            for f in nf.iter(f"{_NS}numFmt"):
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", (f.get("formatCode") or "").lower())
                custom[int(f.get("numFmtId") or 0)] = bool(re.search(r"[dy]", code))
        xfs = st.find(f"{_NS}cellXfs")
        if xfs is not None:
            for idx, xf in enumerate(xfs.iter(f"{_NS}xf")):
                fid = int(xf.get("numFmtId") or 0)
                if fid in _DATE_FMT_IDS or custom.get(fid):
                    date_styles.add(idx)

    sheet = _xml(zf, target)
    data_el = sheet.find(f"{_NS}sheetData")
    out: list[tuple[int, list[str]]] = []
    if data_el is None:
        return out
    for row in data_el.iter(f"{_NS}row"):
        line = int(row.get("r") or len(out) + 1)
        cells: dict[int, str] = {}
        for c in row.iter(f"{_NS}c"):
            col = _col_index(c.get("r") or "")
            if col < 0:
                col = len(cells)
            if col >= MAX_COLUMNS:
                continue
            t = c.get("t")
            v = c.find(f"{_NS}v")
            text = v.text if v is not None and v.text is not None else ""
            if t == "s":
                try:
                    text = shared[int(text)]
                except (ValueError, IndexError):
                    text = ""
            elif t == "inlineStr":
                is_ = c.find(f"{_NS}is")
                text = "".join(x.text or "" for x in is_.iter(f"{_NS}t")) if is_ is not None else ""
            elif t == "b":
                text = "TRUE" if text == "1" else "FALSE"
            elif t in ("str", "e"):
                pass
            elif text:
                s = int(c.get("s") or 0)
                if s in date_styles:
                    try:
                        text = _excel_date(float(text))
                    except (ValueError, OverflowError):
                        pass
                else:
                    text = _num_text(text)
            cells[col] = text
        width = (max(cells) + 1) if cells else 0
        out.append((line, [cells.get(i, "") for i in range(width)]))
        if len(out) > MAX_ROWS + 50:
            break
    return out


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

_OTHER_CURRENCY = re.compile(r"€|£|¥|₹|\b(EUR|GBP|JPY|CNY|INR|CAD|AUD|CHF|SEK|MXN|SAR|AED)\b", re.I)


def parse_number(raw: str) -> Optional[float]:
    """'1,234.50', '$12', '12,5', '1.234,5' -> a float; '' -> None; else ValueError."""
    s = (raw or "").strip()
    if not s:
        return None
    s = re.sub(r"(?i)\$|\busd\b|\s|h\b|hrs?\b|hours?\b", "", s)
    if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+,\d+", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[-+]?\d+,\d{1,2}", s):
        s = s.replace(",", ".")
    v = float(s)
    if not math.isfinite(v):
        raise ValueError("not a finite number")
    return v


def parse_date(raw: str, order: str = "mdy") -> Optional[date]:
    """ISO, m/d/y or d/m/y (``order``), d.m.y, or an Excel serial -> a date."""
    s = (raw or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if "." in s or order == "dmy" or a > 12:
            d, mo = a, b
        else:
            mo, d = a, b
        return date(y, mo, d)
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        return date.fromisoformat(_excel_date(float(s)))
    raise ValueError("not a date")


def date_order_of(values: Iterable[str]) -> str:
    """'dmy' when some slash date can only be day-first, else 'mdy'."""
    for v in values:
        m = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", v or "")
        if m and int(m.group(1)) > 12:
            return "dmy"
    return "mdy"


_TEST_KINDS = {"test", "demo", "synthetic", "seed", "stand_in", "stand-in", "standin", "sample", "made up", "made-up", "fake"}
_KIND_MAP = {"actual": "actual", "job": "actual", "invoice": "invoice", "quote": "quote", "pilot": "pilot"}


def kind_of(raw: str) -> tuple[str, bool]:
    """(source_type, is_test) for a 'kind' cell."""
    v = (raw or "").strip().lower()
    if not v:
        return "actual", False
    if v in _TEST_KINDS or "test" in v or "made up" in v or "demo" in v:
        return "demo", True
    return _KIND_MAP.get(v, "actual"), False


# ---------------------------------------------------------------------------
# The organization's checked parts, and matching rows to them
# ---------------------------------------------------------------------------


@dataclass
class PartRef:
    key: str                              # mesh hash: the part's identity
    file_name: str
    record_id: str
    label: Optional[str] = None
    checked_at: Optional[str] = None
    material_class: Optional[str] = None
    pick: Optional[str] = None            # ScaleCAD's make-now pick on the newest record
    part_numbers: set[str] = field(default_factory=set)

    def public(self) -> dict:
        return {
            "key": self.key,
            "file_name": self.file_name,
            "label": self.label,
            "record_id": self.record_id,
            "checked_at": self.checked_at,
            "part_numbers": sorted(self.part_numbers),
        }


def _pn(v: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (v or "").strip()).upper()


def _name_keys(name: str) -> tuple[str, str]:
    base = os.path.basename((name or "").replace("\\", "/")).strip().lower()
    return base, os.path.splitext(base)[0]


class PartIndex:
    """Lookups over one organization's checked parts."""

    def __init__(self, parts: Iterable[PartRef]):
        self.parts: dict[str, PartRef] = {}
        self.by_base: dict[str, set[str]] = {}
        self.by_stem: dict[str, set[str]] = {}
        self.by_pn: dict[str, set[str]] = {}
        for p in parts:
            self.parts[p.key] = p
            base, stem = _name_keys(p.file_name)
            self.by_base.setdefault(base, set()).add(p.key)
            self.by_stem.setdefault(stem, set()).add(p.key)
            for n in p.part_numbers:
                if _pn(n):
                    self.by_pn.setdefault(_pn(n), set()).add(p.key)

    def by_hash(self, h: str) -> set[str]:
        h = (h or "").strip().lower()
        return {h} if h in self.parts else set()

    def by_name(self, name: str) -> set[str]:
        base, stem = _name_keys(name)
        if base in self.by_base:
            return set(self.by_base[base])
        return set(self.by_stem.get(stem, set()) | (self.by_stem.get(base, set()) if base != stem else set()))

    def by_number(self, number: str) -> set[str]:
        hits = set(self.by_pn.get(_pn(number), set()))
        if not hits:
            # A part number that is the file's name (BRK-001 -> BRK-001.step), as catalog runs match.
            base, stem = _name_keys(number)
            hits = set(self.by_stem.get(base, set()) | self.by_stem.get(stem, set()))
        return hits


@dataclass
class Match:
    status: str                       # matched | ambiguous | unmatched
    key: Optional[str] = None
    basis: Optional[str] = None       # file_hash | part_number | file_name | chosen
    candidates: list[str] = field(default_factory=list)
    reason: str = ""


def match_identity(ids: dict[str, str], index: PartIndex) -> Match:
    """Match one row's identifiers to a checked part. Never guesses.

    ``ids`` may carry ``file_hash``, ``part_number``, ``file_name`` and ``part``
    (a value that may be either). A file hash is exact. Several identifiers that
    agree narrow to their common part; identifiers that point to different parts,
    or one that fits several parts, come back ``ambiguous`` with the candidates.
    """
    file_hash = (ids.get("file_hash") or "").strip()
    number = (ids.get("part_number") or "").strip()
    name = (ids.get("file_name") or "").strip()
    either = (ids.get("part") or "").strip()
    if not (file_hash or number or name or either):
        return Match("unmatched", reason="No part number, file name or file hash in this row")

    found: list[tuple[str, set[str], str]] = []   # (basis, keys, what it was)
    missing: list[str] = []
    if file_hash:
        hits = index.by_hash(file_hash)
        if hits:
            found.append(("file_hash", hits, "this file hash"))
        else:
            missing.append("this file hash")
    if number:
        hits = index.by_number(number)
        if hits:
            found.append(("part_number", hits, f"part number {number}"))
        else:
            missing.append(f"part number {number}")
    if name:
        hits = index.by_name(name)
        if hits:
            found.append(("file_name", hits, f"file name {name}"))
        else:
            missing.append(f"file name {name}")
    if either:
        pn_hits = set(index.by_pn.get(_pn(either), set()))
        nm_hits = index.by_name(either)
        if pn_hits:
            found.append(("part_number", pn_hits, f"part number {either}"))
        elif nm_hits:
            found.append(("file_name", nm_hits, f"file name {either}"))
        else:
            missing.append(either)

    if not found:
        return Match("unmatched", reason=f"No checked part has {_join(missing)}")

    # A file hash is the part itself.
    hash_hit = next((f for f in found if f[0] == "file_hash"), None)
    if hash_hit is not None:
        key = next(iter(hash_hit[1]))
        others = [f for f in found if f[0] != "file_hash" and key not in f[1]]
        if others:
            cands = sorted({key} | set().union(*(f[1] for f in others)))
            return Match("ambiguous", candidates=cands,
                         reason=f"The file hash and {others[0][2]} point to different parts")
        return Match("matched", key=key, basis="file_hash")

    common = set.intersection(*(f[1] for f in found))
    if len(common) == 1:
        key = next(iter(common))
        basis = "part_number" if any(f[0] == "part_number" for f in found) else "file_name"
        return Match("matched", key=key, basis=basis)
    if not common:
        cands = sorted(set().union(*(f[1] for f in found)))
        return Match("ambiguous", candidates=cands,
                     reason=f"{_cap(found[0][2])} and {found[1][2]} point to different parts")
    what = found[0][2]
    return Match("ambiguous", candidates=sorted(common),
                 reason=f"{len(common)} checked parts have {what}")


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " or " + items[-1]


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


async def load_part_index(session: AsyncSession, org_id: str) -> PartIndex:
    """The caller org's checked parts: newest record per file hash, with part numbers."""
    from src.db.models import Batch, BatchItem, CostDecision, PartSignature

    rows = (await session.execute(
        select(CostDecision.mesh_hash, CostDecision.ulid, CostDecision.filename, CostDecision.label,
               CostDecision.created_at, CostDecision.make_now_process,
               CostDecision.result_json["material_class"].astext)
        .where(CostDecision.org_id == org_id)
        .distinct(CostDecision.mesh_hash)
        .order_by(CostDecision.mesh_hash, CostDecision.created_at.desc(), CostDecision.id.desc())
    )).all()
    parts: dict[str, PartRef] = {}
    for mesh_hash, ulid, filename, label, created_at, pick, material in rows:
        p = PartRef(key=mesh_hash, file_name=filename or "", record_id=ulid, label=label,
                    checked_at=created_at.isoformat() if created_at else None,
                    material_class=material or None, pick=pick)
        if label and label.strip():
            p.part_numbers.add(label.strip())
        parts[mesh_hash] = p

    for mesh_hash, declared in (await session.execute(
        select(PartSignature.mesh_hash, PartSignature.declared_part_id)
        .where(PartSignature.org_id == org_id, PartSignature.declared_part_id.isnot(None))
    )).all():
        if mesh_hash in parts and (declared or "").strip():
            parts[mesh_hash].part_numbers.add(declared.strip())

    # Part numbers given in a catalog run's parts list, per file of that run.
    for filename, mesh_hash, manifest in (await session.execute(
        select(BatchItem.filename, CostDecision.mesh_hash, Batch.manifest_json)
        .join(Batch, Batch.id == BatchItem.batch_id)
        .join(CostDecision, CostDecision.id == BatchItem.cost_decision_id)
        .where(Batch.org_id == org_id, CostDecision.org_id == org_id)
        .limit(20000)
    )).all():
        meta = ((manifest or {}).get("catalog") or {}).get("items") or {}
        pn = (meta.get(filename) or {}).get("part_number")
        if mesh_hash in parts and pn and str(pn).strip():
            parts[mesh_hash].part_numbers.add(str(pn).strip())
    return PartIndex(parts.values())


async def load_machines(session: AsyncSession, org_id: str) -> list[dict]:
    from src.db.models import MachineInstance

    rows = (await session.execute(
        select(MachineInstance.name, MachineInstance.process).where(MachineInstance.org_id == org_id)
    )).all()
    return [{"name": n, "process": p} for n, p in rows if n]


# ---------------------------------------------------------------------------
# Mapping + preview
# ---------------------------------------------------------------------------


@dataclass
class Mapping:
    columns: dict[str, int]
    hours_unit: str = "h"                  # h | min
    date_order: str = "mdy"                # mdy | dmy
    process_map: dict[str, str] = field(default_factory=dict)   # raw (lower) -> process | "pick"
    test: bool = False                     # every row is a test number (stand-in)

    @classmethod
    def from_json(cls, d: Optional[dict], table: Table) -> "Mapping":
        if not d:
            cols = guess_mapping(table.headers)
            hcol = cols.get("machine_hours", cols.get("machine_hours_total"))
            dcol = cols.get("date")
            return cls(
                columns=cols,
                hours_unit=hours_unit_of(table.headers[hcol]) if hcol is not None else "h",
                date_order=date_order_of(r[dcol] for r in table.rows) if dcol is not None else "mdy",
            )
        cols: dict[str, int] = {}
        for k, v in (d.get("columns") or {}).items():
            if k not in FIELDS or v is None or v == "":
                continue
            try:
                i = int(v)
            except (TypeError, ValueError):
                raise TableError(f"Column for {FIELDS[k].lower()} must be a column number.")
            if not 0 <= i < len(table.headers):
                raise TableError(f"Column {i + 1} for {FIELDS[k].lower()} isn't in the file.")
            cols[k] = i
        unit = d.get("hours_unit") or "h"
        order = d.get("date_order") or "mdy"
        pm = {}
        for k, v in (d.get("process_map") or {}).items():
            if v in KNOWN_PROCESSES or v == "pick":
                pm[str(k).strip().lower()] = v
        return cls(columns=cols, hours_unit=unit if unit in ("h", "min") else "h",
                   date_order=order if order in ("mdy", "dmy") else "mdy",
                   process_map=pm, test=bool(d.get("test")))

    def public(self) -> dict:
        return {"columns": self.columns, "hours_unit": self.hours_unit, "date_order": self.date_order,
                "process_map": self.process_map, "test": self.test}


def _cell(row: list[str], m: Mapping, key: str) -> str:
    i = m.columns.get(key)
    return row[i].strip() if i is not None and i < len(row) else ""


def process_values(table: Table, m: Mapping, machines: list[dict]) -> list[dict]:
    """Each distinct process value with its row count and the prefilled method."""
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}
    for row in table.rows:
        raw = _cell(row, m, "process")
        if not raw:
            mach = _machine_of(_cell(row, m, "machine"), machines)
            if mach:
                continue
        k = raw.lower()
        counts[k] = counts.get(k, 0) + 1
        shown.setdefault(k, raw)
    out = []
    for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        guess = guess_process(k) if k else None
        out.append({"value": shown[k], "key": k, "rows": n, "guess": guess,
                    "method": m.process_map.get(k, guess)})
    return out


def _machine_of(raw: str, machines: list[dict]) -> Optional[dict]:
    v = (raw or "").strip().lower()
    if not v:
        return None
    for mach in machines:
        if (mach.get("name") or "").strip().lower() == v:
            return mach
    return None


@dataclass
class RowResult:
    line: int
    status: str                          # matched | ambiguous | unmatched | error
    values: dict
    errors: list[str]
    warnings: list[str]
    match: Match
    part: Optional[PartRef] = None

    def public(self, index: PartIndex) -> dict:
        return {
            "line": self.line,
            "status": self.status,
            "values": self.values,
            "errors": self.errors,
            "warnings": self.warnings,
            "basis": self.match.basis,
            "reason": self.match.reason,
            "part": self.part.public() if self.part else None,
            "candidates": [index.parts[k].public() for k in self.match.candidates if k in index.parts],
        }


def evaluate_rows(table: Table, m: Mapping, index: PartIndex, machines: list[dict],
                  choices: Optional[dict] = None) -> list[RowResult]:
    """Parse and match every row. ``choices`` maps a line to a part key or 'skip'."""
    choices = {str(k): v for k, v in (choices or {}).items()}
    out: list[RowResult] = []
    for row, line in zip(table.rows, table.lines):
        errors: list[str] = []
        warnings: list[str] = []

        qty = None
        raw_q = _cell(row, m, "quantity")
        if "quantity" not in m.columns:
            errors.append("No quantity column")
        elif not raw_q:
            errors.append("No quantity")
        else:
            try:
                q = parse_number(raw_q)
                if q is None or q != int(q) or not 1 <= q <= 2_147_483_647:
                    raise ValueError
                qty = int(q)
            except ValueError:
                errors.append(f"Quantity '{raw_q}' isn't a whole number of 1 or more")

        hours = None
        hkey = "machine_hours" if "machine_hours" in m.columns else ("machine_hours_total" if "machine_hours_total" in m.columns else None)
        if hkey:
            raw_h = _cell(row, m, hkey)
            try:
                h = parse_number(raw_h)
                if h is not None:
                    if h <= 0:
                        raise ValueError
                    if m.hours_unit == "min":
                        h = h / 60.0
                    if hkey == "machine_hours_total":
                        h = h / qty if qty else None
                    hours = round(h, 6) if h is not None else None
            except ValueError:
                errors.append(f"Machine hours '{raw_h}' isn't a number above 0")

        cost = None
        ckey = "cost_each" if "cost_each" in m.columns else ("cost_total" if "cost_total" in m.columns else None)
        if ckey:
            raw_c = _cell(row, m, ckey)
            if raw_c and _OTHER_CURRENCY.search(raw_c):
                errors.append(f"Cost '{raw_c}' isn't in US dollars; ScaleCAD compares costs in US dollars")
            else:
                try:
                    c = parse_number(raw_c)
                    if c is not None:
                        if c <= 0:
                            raise ValueError
                        if ckey == "cost_total":
                            c = c / qty if qty else None
                        cost = round(c, 4) if c is not None else None
                except ValueError:
                    errors.append(f"Cost '{raw_c}' isn't an amount above 0")
        if hours is None and cost is None and not any(e.startswith(("Machine hours", "Cost")) for e in errors):
            errors.append("No machine hours or cost in this row")

        machine_raw = _cell(row, m, "machine")
        mach = _machine_of(machine_raw, machines)
        raw_p = _cell(row, m, "process")
        process = None
        method_from = None
        if raw_p:
            process = m.process_map.get(raw_p.lower(), guess_process(raw_p))
            method_from = "file"
            if process is None:
                errors.append(f"Process '{raw_p}' isn't one ScaleCAD knows; pick the method it means")
        elif mach:
            process = mach["process"]
            method_from = "machine"
        else:
            process = m.process_map.get("")
            method_from = "chosen" if process else None
            if process is None:
                errors.append("No process; pick the method for rows without one")

        when = None
        raw_d = _cell(row, m, "date")
        if raw_d:
            try:
                when = parse_date(raw_d, m.date_order)
            except (ValueError, OverflowError):
                warnings.append(f"Date '{raw_d}' couldn't be read; imported without a date")

        source_type, is_test = kind_of(_cell(row, m, "kind"))
        if m.test:
            source_type, is_test = "demo", True

        ids = {k: _cell(row, m, k) for k in IDENTITY_FIELDS if k in m.columns}
        match = match_identity(ids, index)
        chosen = choices.get(str(line))
        if chosen == "skip":
            match = Match("unmatched", reason="Skipped")
        elif chosen and chosen in index.parts and (match.status != "matched" or chosen != match.key):
            match = Match("matched", key=chosen, basis="chosen", candidates=match.candidates)
        part = index.parts.get(match.key) if match.key else None
        if process == "pick" and part is not None:
            process = part.pick
            method_from = "pick"
            if not process:
                errors.append("ScaleCAD has no pick for this part; pick the method")
        elif process == "pick":
            process = None

        values = {
            "part_number": ids.get("part_number") or _number_given(ids.get("part"), part),
            "file_name": ids.get("file_name") or None,
            "file_hash": ids.get("file_hash") or None,
            "quantity": qty,
            "hours_each": hours,
            "cost_each": cost,
            "process": process,
            "method_from": method_from,
            "machine": (mach or {}).get("name") or (machine_raw or None),
            "date": when.isoformat() if when else None,
            "reference": _cell(row, m, "reference") or None,
            "notes": _cell(row, m, "notes") or None,
            "source_type": source_type,
            "test": is_test,
        }
        status = "error" if errors else match.status
        out.append(RowResult(line=line, status=status, values=values, errors=errors,
                             warnings=warnings, match=match, part=part))
    return out


def _number_given(either: Optional[str], part: Optional[PartRef]) -> Optional[str]:
    """A 'part number or file name' value kept as the part number unless it is the file's name."""
    v = (either or "").strip()
    if not v:
        return None
    if part is not None:
        base, stem = _name_keys(part.file_name)
        if v.lower() in (base, stem):
            return None
    return v


def summarize(results: list[RowResult]) -> dict:
    n = {"rows": len(results), "matched": 0, "ambiguous": 0, "unmatched": 0, "error": 0, "test": 0}
    for r in results:
        n[r.status] = n.get(r.status, 0) + 1
        if r.values.get("test") and r.status == "matched":
            n["test"] += 1
    n["parts"] = len({r.part.key for r in results if r.status == "matched" and r.part})
    return n


async def preview(session: AsyncSession, org_id: str, filename: str, data: bytes,
                  mapping: Optional[dict], choices: Optional[dict]) -> dict:
    table = read_table(filename, data)
    m = Mapping.from_json(mapping, table)
    index = await load_part_index(session, org_id)
    machines = await load_machines(session, org_id)
    results = evaluate_rows(table, m, index, machines, choices)
    return {
        "file": {"name": filename, "kind": table.kind, "rows": len(table.rows), "notes": table.notes},
        "headers": table.headers,
        "sample": table.rows[:5],
        "fields": [{"key": k, "label": v} for k, v in FIELDS.items()],
        "mapping": m.public(),
        "process_values": process_values(table, m, machines),
        "parts_checked": len(index.parts),
        "summary": summarize(results),
        "rows": [r.public(index) for r in results],
    }


def to_payload(r: RowResult) -> dict:
    """A matched row as a ground-truth create payload (see groundtruth_service.ingest_record)."""
    v = r.values
    p = r.part
    from src.services.groundtruth_service import KNOWN_MATERIAL_CLASSES

    material = p.material_class if p and p.material_class in KNOWN_MATERIAL_CLASSES else "polymer"
    source = v.get("reference") or ""
    return {
        "part_id": p.file_name or p.key,
        "process": v["process"],
        "quantity": v["quantity"],
        "actual_unit_cost_usd": v.get("cost_each"),
        "actual_machine_hours": v.get("hours_each"),
        "material_class": material,
        "source": source[:500],
        "source_type": v.get("source_type") or "actual",
        "vendor_quote_id": (v.get("reference") or None),
        "invoice_date": v.get("date"),
        "evidence_sha256": p.key,
        "part_number": v.get("part_number"),
        "machine": v.get("machine"),
        "match_basis": r.match.basis,
        "notes": (v.get("notes") or "")[:2000],
        "stand_in": bool(v.get("test")),
    }


async def import_rows(session: AsyncSession, org_id: str, user_id: Optional[int], filename: str,
                      data: bytes, mapping: Optional[dict], choices: Optional[dict]) -> dict:
    """Import every matched row without errors; report the rest. Caller commits."""
    from src.services import groundtruth_service as gts

    table = read_table(filename, data)
    m = Mapping.from_json(mapping, table)
    index = await load_part_index(session, org_id)
    machines = await load_machines(session, org_id)
    results = evaluate_rows(table, m, index, machines, choices)
    ready = [r for r in results if r.status == "matched" and r.part is not None]
    imported = 0
    failed: list[dict] = []
    for r in ready:
        try:
            async with session.begin_nested():
                await gts.ingest_record(session, org_id, user_id, to_payload(r))
            imported += 1
        except (ValueError, KeyError) as exc:
            failed.append({"line": r.line, "reason": str(exc)})
    left = [
        {"line": r.line, "status": r.status, "reason": "; ".join(r.errors) or r.match.reason}
        for r in results if not (r.status == "matched" and r.part is not None)
    ]
    return {
        "imported": imported,
        "parts": len({r.part.key for r in ready}),
        "test": sum(1 for r in ready if r.values.get("test")),
        "not_imported": left + failed,
        "rows": len(results),
    }


__all__ = [
    "FIELDS", "Mapping", "PartIndex", "PartRef", "Table", "TableError", "evaluate_rows", "guess_mapping",
    "guess_process", "import_rows", "load_part_index", "match_identity", "parse_date", "parse_number",
    "preview", "read_table",
]
