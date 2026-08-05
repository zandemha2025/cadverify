"""Shared locators for CAD fixtures distributed by pinned test dependencies."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


AS1_SHA256 = "d40db2ed6f741d2955329f9751c7e3e0a14cbfeb4e11d8338cf110765b9042f9"


def as1_fixture_path() -> Path:
    """Return Gmsh's canonical AS1 assembly, failing on absence or drift.

    Gmsh 4.15.2 is pinned in the production lock and installs this GPLv2+
    example under ``sys.prefix/share``.  We consume that dependency-owned copy
    in tests instead of vendoring a second licensed binary into this repository.
    An explicit override is useful for distro packages with a different layout.
    """
    override = os.getenv("CADVERIFY_AS1_FIXTURE")
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(override).expanduser() if override else None,
        repo_root / "data" / "real-corpus" / "as1-tu-203.stp",
        Path(sys.prefix) / "share" / "doc" / "gmsh" / "examples" / "api"
        / "as1-tu-203.stp",
        Path(sys.prefix) / "share" / "doc" / "gmsh" / "examples" / "boolean"
        / "as1-tu-203.stp",
    ]
    checked: list[str] = []
    for candidate in candidates:
        if candidate is None:
            continue
        checked.append(str(candidate))
        if not candidate.is_file():
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest != AS1_SHA256:
            raise AssertionError(
                f"AS1 fixture checksum drift at {candidate}: {digest}"
            )
        return candidate
    raise FileNotFoundError(
        "Pinned Gmsh AS1 fixture is missing; checked: " + ", ".join(checked)
    )


def as1_fixture_bytes() -> bytes:
    return as1_fixture_path().read_bytes()
