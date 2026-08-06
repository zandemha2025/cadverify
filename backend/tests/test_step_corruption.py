"""Regression: corrupted/malformed STEP rejection + temp-file cleanup.

Covers CORE-01 (temp-file cleanup) and CORE-07 (magic-byte defense) from
the Phase-1 hardening plan. All checks run without the optional cadquery parser.
"""
from __future__ import annotations

import glob
import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_corrupted_step_returns_400(client):
    """A STEP file with valid magic but garbage body returns 400 (not 500, not hang)."""
    bad = b"ISO-10303-21;\nHEADER;\nTHIS IS NOT VALID STEP AT ALL\x00\x01"
    r = client.post(
        "/api/v1/validate",
        files={"file": ("bad.step", bad, "application/octet-stream")},
    )
    # Acceptable: 400 (parse failed), 501 (cadquery not installed)
    assert r.status_code in (400, 501), f"unexpected {r.status_code}: {r.text[:200]}"
    assert "message" in r.json()


def test_non_step_magic_with_step_extension_returns_400(client):
    """A JPEG renamed to .step must fail at magic-byte check (pre-parse)."""
    r = client.post(
        "/api/v1/validate",
        files={
            "file": (
                "photo.step",
                b"\xff\xd8\xff\xe0JFIF\x00" + b"\x00" * 32,
                "application/octet-stream",
            ),
        },
    )
    assert r.status_code == 400
    msg = r.json()["message"].lower()
    # Message should reference STEP / ISO-10303 magic, not a generic parse error
    assert "step" in msg or "iso-10303" in msg or "magic" in msg


def test_truncated_step_returns_400(client):
    """A STEP file cut off mid-header must not hang or 500."""
    truncated = b"ISO-10303-21;\nHE"  # magic-pass but structurally broken
    r = client.post(
        "/api/v1/validate",
        files={"file": ("trunc.stp", truncated, "application/octet-stream")},
    )
    assert r.status_code in (400, 501)


def test_step_parse_leaves_no_temp_files(monkeypatch):
    """CORE-01: parse_step_from_bytes cleans up even when its parser fails."""
    import src.parsers.step_parser as step_parser

    opened: list[str] = []

    def fail_after_open(path, linear_deflection=0.1):
        assert os.path.isfile(path)
        assert os.stat(path).st_mode & 0o777 == 0o600
        opened.append(str(path))
        raise ValueError("forced parse failure")

    monkeypatch.setattr(step_parser, "parse_step", fail_after_open)

    tmp_dir = tempfile.gettempdir()
    before = set(
        glob.glob(os.path.join(tmp_dir, "tmp*.step"))
        + glob.glob(os.path.join(tmp_dir, "tmp*.stp"))
    )
    try:
        step_parser.parse_step_from_bytes(
            b"ISO-10303-21;\nnot a real step", "test.step"
        )
    except Exception:
        # Expected — we want to confirm the failure path cleans up.
        pass
    after = set(
        glob.glob(os.path.join(tmp_dir, "tmp*.step"))
        + glob.glob(os.path.join(tmp_dir, "tmp*.stp"))
    )
    leaked = after - before
    assert opened, "test must reach the parser with a real owner-only temp file"
    assert not leaked, f"Leaked temp files: {leaked}"


def test_empty_step_returns_400(client):
    """Empty-body upload is rejected by _read_capped before reaching the parser."""
    r = client.post(
        "/api/v1/validate",
        files={"file": ("empty.step", b"", "application/octet-stream")},
    )
    assert r.status_code == 400
