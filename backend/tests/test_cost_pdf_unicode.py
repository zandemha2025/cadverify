"""Regression coverage for exact, readable governance text in cost PDFs."""
from __future__ import annotations

import shutil
import subprocess
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
    assert "⚙" not in lines, "the symbol must not float onto its own PDF line"
