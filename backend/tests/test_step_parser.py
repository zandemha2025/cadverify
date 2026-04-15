"""Tests for STEP parser temp-file handling (CORE-01).

These tests must run even when cadquery is not installed — they assert
filesystem discipline (cleanup, permissions), not parse correctness.
"""
from __future__ import annotations


def test_step_parse_leaves_no_temp_files(tmp_path, monkeypatch):
    """parse_step_from_bytes must unlink its temp file even on parse failure."""
    import glob, os, tempfile
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))) \
           | set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp")))
    from src.parsers.step_parser import parse_step_from_bytes
    try:
        parse_step_from_bytes(b"not a real step file", "test.step")
    except Exception:
        pass  # parse failure is expected; we're asserting cleanup
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.step"))) \
          | set(glob.glob(os.path.join(tempfile.gettempdir(), "tmp*.stp")))
    assert after == before, f"Leaked temp files: {after - before}"


def test_step_temp_file_mode_is_0o600(monkeypatch):
    """Temp file created by parse_step_from_bytes must be owner-only (0o600)."""
    # Patch parse_step to capture the path before cleanup.
    import os
    import src.parsers.step_parser as sp

    captured = {}
    def fake_parse_step(path, linear_deflection=0.1):
        captured["mode"] = os.stat(path).st_mode & 0o777
        raise ValueError("stop here")  # force finally block to run
    monkeypatch.setattr(sp, "parse_step", fake_parse_step)
    try:
        sp.parse_step_from_bytes(b"ISO-10303-21;\nDUMMY;\n", "test.step")
    except ValueError:
        pass
    assert captured.get("mode") == 0o600, f"mode was {oct(captured.get('mode', 0))}"
