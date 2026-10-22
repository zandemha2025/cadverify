"""Every CSV ScaleCAD exports: a cell is data, never a formula, and stays one cell.

One helper for every writer (the batch results, the catalog board, the cost
decision and cost-input tables, the RFQ line items, the audit log):

* ``safe_cell`` neutralizes formula-capable text with the conventional
  apostrophe prefix: at the start of the cell, and at the start of every line
  inside it, so a reader that splits rows on a bare line break never meets a
  live formula either.
* ``csv_field`` renders one cell for a row joined by hand, quoted exactly as
  the csv module's excel dialect quotes it: when it holds a comma, a quote, a
  carriage return or a line feed. (A writer using ``csv.writer`` passes each
  cell through ``safe_cell``; the module quotes it the same way.)
"""
from __future__ import annotations

import re

_FORMULA_START = ("=", "+", "-", "@")
# A line break, then optional spaces or tabs, then a character a spreadsheet
# reads as the start of a formula.
_FORMULA_AFTER_BREAK = re.compile(r"([\r\n])([ \t]*[=+\-@])")
_NEEDS_QUOTES = (",", '"', "\r", "\n")


def safe_cell(value):
    """``value`` with formula-capable text neutralized; anything but a non-empty string unchanged.

    Spreadsheet programs may run a cell that begins with =, +, - or @, also
    after leading whitespace or a control character. Users still see the text;
    the imported cell is data. Numbers stay numbers.
    """
    if not isinstance(value, str) or not value:
        return value
    if value[0] in "\t\r\n" or value.lstrip(" \t\r\n").startswith(_FORMULA_START):
        value = "'" + value
    if "\r" in value or "\n" in value:
        value = _FORMULA_AFTER_BREAK.sub(r"\1'\2", value)
    return value


def csv_field(value) -> str:
    """One CSV cell, made safe (``safe_cell``) and quoted as the csv module would."""
    if value is None or value == "":
        return ""
    text = str(safe_cell(value))
    if any(c in text for c in _NEEDS_QUOTES):
        return '"' + text.replace('"', '""') + '"'
    return text
