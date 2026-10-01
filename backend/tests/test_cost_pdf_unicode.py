"""Regression coverage for exact, readable governance text in cost PDFs."""
from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.services.cost_pdf_service import _render_cost_pdf_sync, render_cost_html


SPECIAL_NOTE = (
    "QA edit α/β — “quoted” <tag> & gears ⚙️\n"
    "Line 2: $3.80/unit; path C:\\fixtures\\cube.step"
)


def _decision():
    return SimpleNamespace(
        ulid="01TESTCOSTPDFUNICODE0000000",
        filename="unicode.step",
        file_type="step",
        label=None,
        created_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        engine_version="test",
        mesh_hash="a" * 64,
        result_json={},
        approval_status="approved",
        approved_by_user_id=42,
        approved_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        approval_note=SPECIAL_NOTE,
        user_disposition="outside",
        disposition_note=f"Disposition: {SPECIAL_NOTE}",
        disposition_updated_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        disposition_updated_by_user_id=42,
        stale_at=None,
        stale_reason=None,
    )


def test_cost_pdf_keeps_special_note_symbols_inline(tmp_path):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        pytest.skip("pdftotext is required for PDF glyph-position regression coverage")

    decision = _decision()
    html = render_cost_html(decision)
    assert "QA edit α/β — “quoted” &lt;tag&gt; &amp; gears ⚙" in html
    assert "⚙️" not in html
    assert "Disposition: QA edit α/β — “quoted” &lt;tag&gt; &amp; gears ⚙" in html

    pdf_path = tmp_path / "unicode-governance.pdf"
    pdf_path.write_bytes(_render_cost_pdf_sync(decision, html))
    extracted = subprocess.run(
        [pdftotext, str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    lines = [line.strip() for line in extracted.splitlines() if line.strip()]

    assert "QA edit α/β — “quoted” <tag> & gears ⚙" in lines
    assert "Line 2: $3.80/unit; path C:\\fixtures\\cube.step" in lines
    assert "Disposition: QA edit α/β — “quoted” <tag> & gears ⚙" in lines
    assert "⚙" not in lines, "the symbol must not float onto its own PDF line"


def test_cost_pdf_explains_asymptotic_split_and_repeats_table_headers(tmp_path):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        pytest.skip("pdftotext is required for PDF pagination regression coverage")

    decision = _decision()
    decision.result_json = {"estimates": [{
        "process": "mjf", "material": "PP", "quantity": 50,
        "unit_cost_usd": 3.8, "fixed_cost_usd": 0, "variable_cost_usd": 3.48,
        "line_items": {"material": 0.01, "machine": 0.61, "labor": 2.83, "setup": 0.35},
    }] * 100}
    html = render_cost_html(decision)
    assert "Unit cost = fixed (amortized) + variable" not in html
    assert "One-time $" in html and "Long-run $/unit" in html
    pdf_path = tmp_path / "paginated-cost.pdf"
    pdf_path.write_bytes(_render_cost_pdf_sync(decision, html))
    pages = subprocess.run(
        [pdftotext, "-layout", str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout.split("\f")
    assert "mjf" in pages[1]
    assert "One-time $" in pages[1], "continuation pages must repeat estimate headings"
    line_item_pages = [p for p in pages if "2.83" in p]
    assert len(line_item_pages) >= 2
    assert all("Σ unit" in p for p in line_item_pages), "repeat line-item headings too"


def test_cost_pdf_full_line_item_matrix_stays_inside_page(tmp_path):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        pytest.skip("pdftotext is required for PDF column-boundary regression coverage")

    decision = _decision()
    decision.result_json = {"estimates": [{
        "process": "injection_molding", "material": "PP (Polypropylene)",
        "quantity": 10000, "unit_cost_usd": 6000,
        "line_items": {
            "nre": 0, "labor": 1.75, "machine": 0.42, "material": 0.01,
            "inspection": 0, "consumables": 0, "amortized_fixed": 5997.82,
            "min_charge_floor": 0,
        },
    }]}
    pdf_path = tmp_path / "wide-line-items.pdf"
    pdf_path.write_bytes(_render_cost_pdf_sync(decision))
    bounds = subprocess.run(
        [pdftotext, "-bbox", str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    pages = ET.fromstring(bounds).findall(".//x:page", ns)
    assert pages
    for page in pages:
        words = page.findall(".//x:word", ns)
        assert words
        # A4's 1.4cm margins are ~40pt. Allow glyph overhang, not clipping.
        for word in words:
            assert 35 <= float(word.attrib["xMin"]), word.text
            assert float(word.attrib["xMax"]) <= float(page.attrib["width"]) - 35, word.text
