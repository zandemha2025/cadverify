"""Layer A part identity — real standard-fastener catalog identification.

Covers three honest claims:
  1. The ISO/DIN standards catalog is self-consistent and matches by across-flats.
  2. The across-flats MEASUREMENT is real geometry (validated on a synthetic hex of
     known AF and on the REAL AS1 nut).
  3. Identification is honest: a clean hex is identified with confidence; a shape
     that is NOT a clean hex (the idealized AS1 nut / bolt) returns None so the
     existing approximate size is kept — never a fabricated ID.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh

from src.analysis.fastener_standards import (
    _ISO_4032_NUTS,
    _COARSE_PITCH_MM,
    identify_standard_fastener,
    match_by_across_flats,
)
from src.analysis.features.across_flats import HEX_AC_AF_RATIO, measure_across_flats
from src.parsers.step_mesher import is_step_supported

_needs_gmsh = pytest.mark.skipif(
    not is_step_supported(), reason="gmsh/STEP path unavailable"
)


def _hex_prism(af_mm: float, height: float = 10.0) -> trimesh.Trimesh:
    """A regular hexagonal prism of a given across-flats — a synthetic hex nut/head.
    circumradius R = AF / sqrt(3); trimesh's 6-section cylinder uses circumradius."""
    R = af_mm / np.sqrt(3.0)
    return trimesh.creation.cylinder(radius=R, height=height, sections=6)


# ── 1. Catalog ──────────────────────────────────────────────────────────────
def test_match_by_across_flats_m12_nut():
    m = match_by_across_flats(19.0, "nut")
    assert m is not None
    assert m["nominal"] == "M12"
    assert m["standard_id"] == "ISO 4032"
    # ISO 4032 M12 across-flats is 18.0 (canonical); 19.0 is the legacy DIN width.
    assert m["af_nominal_mm"] == 18.0
    assert m["din_af_mm"] == 19.0
    assert m["pitch_coarse_mm"] == 1.75


def test_match_by_across_flats_exact_iso_values():
    # An exact ISO 4032 across-flats matches its own nominal with zero residual.
    assert match_by_across_flats(18.0, "nut")["nominal"] == "M12"
    assert match_by_across_flats(18.0, "nut")["residual_mm"] == 0.0
    assert match_by_across_flats(10.0, "nut")["nominal"] == "M6"
    assert match_by_across_flats(13.0, "nut")["nominal"] == "M8"
    assert match_by_across_flats(16.0, "nut")["nominal"] == "M10"
    assert match_by_across_flats(24.0, "nut")["nominal"] == "M16"
    assert match_by_across_flats(30.0, "nut")["nominal"] == "M20"


def test_match_nonsense_returns_none():
    assert match_by_across_flats(99.0, "nut") is None
    assert match_by_across_flats(0.5, "nut") is None
    assert match_by_across_flats(19.0, "not_a_kind") is None
    assert match_by_across_flats(-3.0, "nut") is None


def test_catalog_self_consistent():
    # Across-flats strictly increase with nominal; every size has a coarse pitch;
    # each ISO across-flats round-trips to its own nominal.
    afs = [af for (_n, af, _m, _d) in _ISO_4032_NUTS]
    assert afs == sorted(afs)
    assert all(a < b for a, b in zip(afs, afs[1:]))  # strictly increasing
    for nominal, af, thickness, din in _ISO_4032_NUTS:
        assert nominal in _COARSE_PITCH_MM, nominal
        assert thickness > 0
        assert match_by_across_flats(af, "nut")["nominal"] == nominal
        if din is not None:
            assert din != af  # DIN recorded only where it actually differs


def test_bolt_and_shcs_kinds_match():
    assert match_by_across_flats(24.0, "bolt")["nominal"] == "M16"
    assert match_by_across_flats(13.0, "screw")["nominal"] == "M8"
    # Socket-head cap screw is matched on the round head diameter dk.
    m = match_by_across_flats(18.0, "socket_head_cap_screw")
    assert m["nominal"] == "M12"
    assert m["measured_dimension"] == "head_diameter"


# ── 2. Across-flats measurement (real geometry) ───────────────────────────────
def test_measure_synthetic_hex():
    meas = measure_across_flats(_hex_prism(19.0), features=None)
    assert abs(meas["across_flats_mm"] - 19.0) < 0.2
    assert abs(meas["ac_af_ratio"] - HEX_AC_AF_RATIO) < 0.02
    assert meas["hex_consistent"] is True


def test_identify_synthetic_hex_high_confidence():
    # AF = 18.0 is the exact ISO 4032 M12 across-flats -> HIGH, hex confirmed.
    part = SimpleNamespace(mesh=_hex_prism(18.0))
    ident = identify_standard_fastener(part, "nut", features=None)
    assert ident is not None
    assert ident["nominal"] == "M12"
    assert ident["standard_id"] == "ISO 4032"
    assert ident["hex_confirmed"] is True
    assert ident["confidence"] == "high"
    assert ident["residual_mm"] <= 0.6
    assert "M12 hex nut" in ident["designation"]
    # Honesty: coarse pitch is ASSUMED and no grade is claimed.
    assert "assumed" in ident["thread"]
    assert any("Grade" in c or "grade" in c for c in ident["caveats"])
    assert any("SKU" in c for c in ident["caveats"])


def test_identify_nonhex_shape_returns_none():
    # A 15x20 rectangular block is NOT a clean hex -> no false identification.
    box = trimesh.creation.box(extents=[15.0, 20.0, 4.0])
    part = SimpleNamespace(mesh=box)
    assert identify_standard_fastener(part, "nut", features=None) is None


# ── 3. The REAL AS1 nut (honest outcome) ─────────────────────────────────────
def _as1_bytes() -> bytes:
    for c in (
        Path(__file__).resolve().parents[2] / "data/real-corpus/as1-tu-203.stp",
        Path("/home/user/cadverify/data/real-corpus/as1-tu-203.stp"),
    ):
        if c.exists():
            return c.read_bytes()
    pytest.skip("AS1 real assembly file not available")


@_needs_gmsh
def test_as1_nut_measured_honestly():
    """The idealized AS1 nut is a 15x20 rectangular cross-section, NOT a hexagon.
    We measure its real across-flats and HONESTLY decline to identify it as a hex
    fastener (identity None), keeping the approximate size. This is the correct
    outcome for geometry that cannot support a clean hex identification."""
    from src.analysis.features import detect_all
    from src.parsers.assembly_mesher import extract_assembly_from_bytes

    model = extract_assembly_from_bytes(_as1_bytes(), "as1-tu-203.stp")
    nut = next(p for p in model.parts if p.name == "nut")
    feats = detect_all(nut.mesh)

    meas = measure_across_flats(nut.mesh, features=feats)
    assert meas is not None
    # Real measured across-flats of the idealized nut ~15mm (its short cross-section
    # side), across-corners ~25mm (the rectangle diameter).
    assert 14.0 <= meas["across_flats_mm"] <= 16.0
    assert meas["across_corners_mm"] > meas["across_flats_mm"]
    # NOT a clean hexagon: ratio far from 1.155.
    assert meas["hex_consistent"] is False
    assert meas["ac_af_ratio"] > 1.3

    # Honest identification outcome: not a confident hex match -> None.
    ident = identify_standard_fastener(nut, "nut", features=feats)
    assert ident is None
