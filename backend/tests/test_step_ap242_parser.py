"""Tests for STEP AP242 parser (STEP-01).

Tests cover validation, error handling, and temp-file discipline.
OCP-dependent tests are skipped when XDE modules are not available.
"""
from __future__ import annotations

import pytest

from src.parsers.step_ap242_parser import (
    is_ap242_supported,
    parse_ap242,
    parse_ap242_from_bytes,
    AP242Document,
)


def test_is_ap242_supported():
    """is_ap242_supported returns a bool regardless of environment."""
    result = is_ap242_supported()
    assert isinstance(result, bool)


def test_parse_ap242_missing_file():
    """parse_ap242 raises FileNotFoundError for nonexistent path."""
    if not is_ap242_supported():
        # Without XDE, RuntimeError fires before file check
        with pytest.raises(RuntimeError, match="OCP XDE modules"):
            parse_ap242("/nonexistent/file.step")
    else:
        with pytest.raises(FileNotFoundError, match="STEP file not found"):
            parse_ap242("/nonexistent/file.step")


def test_parse_ap242_wrong_extension(tmp_path):
    """parse_ap242 raises ValueError for non-STEP extensions."""
    bad_file = tmp_path / "model.stl"
    bad_file.write_bytes(b"solid test\nendsolid test\n")

    if not is_ap242_supported():
        with pytest.raises(RuntimeError, match="OCP XDE modules"):
            parse_ap242(bad_file)
    else:
        with pytest.raises(ValueError, match="Expected .step/.stp file"):
            parse_ap242(bad_file)


def test_parse_ap242_from_bytes_cleanup():
    """parse_ap242_from_bytes must unlink its temp file even on failure."""
    import glob
    import os
    import tempfile

    before = set(
        glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))
    ) | set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp")))

    try:
        parse_ap242_from_bytes(b"not a real step file", "test.step")
    except Exception:
        pass  # parse failure expected; asserting cleanup

    after = set(
        glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))
    ) | set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp")))

    assert after == before, f"Leaked temp files: {after - before}"


def test_parse_ap242_from_bytes_temp_mode(monkeypatch):
    """Temp file created by parse_ap242_from_bytes must be owner-only (0o600)."""
    import os
    import src.parsers.step_ap242_parser as ap242

    captured = {}

    original_parse = ap242.parse_ap242

    def fake_parse(path):
        captured["mode"] = os.stat(path).st_mode & 0o777
        raise ValueError("stop here")  # force finally block to run

    monkeypatch.setattr(ap242, "_HAS_XDE", True)
    monkeypatch.setattr(ap242, "parse_ap242", fake_parse)
    try:
        ap242.parse_ap242_from_bytes(b"ISO-10303-21;\nDUMMY;\n", "test.step")
    except ValueError:
        pass
    assert captured.get("mode") == 0o600, f"mode was {oct(captured.get('mode', 0))}"


@pytest.mark.skipif(
    not is_ap242_supported(), reason="OCP XDE not available"
)
def test_ap242_document_has_pmi_flag(tmp_path):
    """Parse a minimal STEP file and verify has_pmi is a bool."""
    # Create a minimal valid STEP file (AP214-like, no PMI)
    step_content = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((''), '2;1');\n"
        "FILE_NAME('test.step', '2024-01-01', (''), (''), '', '', '');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    )
    step_file = tmp_path / "test.step"
    step_file.write_text(step_content)

    result = parse_ap242(step_file)
    assert isinstance(result, AP242Document)
    assert isinstance(result.has_pmi, bool)


@pytest.mark.skipif(
    not is_ap242_supported(), reason="OCP XDE not available"
)
def test_ap214_fallback_no_pmi(tmp_path):
    """AP214 file parses successfully with has_pmi=False (no PMI in AP214)."""
    step_content = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((''), '2;1');\n"
        "FILE_NAME('test.step', '2024-01-01', (''), (''), '', '', '');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    )
    step_file = tmp_path / "ap214_model.step"
    step_file.write_text(step_content)

    result = parse_ap242(step_file)
    assert result.has_pmi is False
