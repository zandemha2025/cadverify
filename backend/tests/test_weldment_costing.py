"""Weldment fabrication costing — known-answer arithmetic and honesty rails.

Every constant is either cited (AWS D1.1 Table 5.7; geometry; steel density)
or labeled UNCALIBRATED with its source family. These tests pin:
  * the fillet table exactly as the standard states it;
  * the deposited-mass arithmetic digit-for-digit;
  * the PROVENANCE gate — a new rate field without a provenance row fails;
  * the uncalibrated band gate — the breakdown can never claim validated;
  * the end shape on the existing welded_frame fixture (cut-list members,
    weld length estimate in, dollars + not_priced shrunk to finishing).
"""
from __future__ import annotations

import dataclasses
import math

import pytest

from src.costing import weldment
from src.costing.weldment import (
    MemberCut,
    WeldmentRates,
    calibration_summary,
    min_fillet_leg_mm,
    weld_metal_mass_kg,
    weldment_breakdown,
)


class TestAwsD11FilletTable:
    """AWS D1.1 Table 5.7 (2025: Table 7.7) — minimum fillet by the THICKER
    member, exactly the published breakpoints in mm."""

    @pytest.mark.parametrize("thicker_mm,leg_mm", [
        (3.0, 3.0),      # 40x40x3 tube wall — the fixture frame
        (6.0, 3.0),      # ≤ 6 inclusive
        (6.1, 5.0),
        (12.0, 5.0),
        (12.7, 6.0),     # 1/2" plate
        (20.0, 6.0),
        (25.0, 8.0),
        (38.0, 8.0),
        (50.0, 10.0),
        (63.0, 10.0),
        (80.0, 13.0),
    ])
    def test_breakpoints(self, thicker_mm, leg_mm):
        assert min_fillet_leg_mm(thicker_mm) == leg_mm

    def test_rejects_nonpositive(self):
        with pytest.raises(ValueError):
            min_fillet_leg_mm(0.0)


class TestWeldMetalArithmetic:
    def test_equal_leg_fillet_mass_is_geometry_times_density(self):
        # 1 m of 3mm fillet: section 3²/2 = 4.5 mm², volume 4500 mm³,
        # mass 4500 mm³ × 7.85e-6 kg/mm³ = 0.035325 kg.
        assert weld_metal_mass_kg(1000.0, 3.0) == pytest.approx(0.035325, rel=1e-9)

    def test_known_frame_weld_mass(self):
        # The welded_frame fixture's band: 4 joints × ~140–170 mm ≈ 560–680 mm
        # of 3mm fillet (its tube wall is 3mm → 3mm leg by Table 5.7).
        mass = weld_metal_mass_kg(640.0, 3.0)
        assert mass == pytest.approx(640.0 * 4.5 * 7.85e-6, rel=1e-9)

    def test_rejects_bad_leg(self):
        with pytest.raises(ValueError):
            weld_metal_mass_kg(100.0, 0.0)


class TestProvenanceGate:
    def test_every_rate_field_has_a_provenance_row(self):
        """A rate without provenance is an invented number; the build fails."""
        fields = {f.name for f in dataclasses.fields(WeldmentRates)}
        assert fields == set(weldment.PROVENANCE.keys()), (
            "every WeldmentRates field must have a PROVENANCE entry: "
            f"missing {fields - set(weldment.PROVENANCE)}, "
            f"extra {set(weldment.PROVENANCE) - fields}"
        )

    def test_every_provenance_row_names_a_source(self):
        for name, row in weldment.PROVENANCE.items():
            assert row.get("status") in ("cited", "uncalibrated"), name
            assert row.get("source", "").strip(), f"{name} names no source"


class TestBreakdown:
    def test_frame_breakdown_math_and_honest_labels(self):
        # welded_frame: 4 members of 40x40x3 tube. Section area of the cut:
        # the blade sweeps the tube's material = perimeter×wall ≈ 4×40×3 =
        # 480 mm² per cut (the stock reader measures it; we pin the math on
        # a stated 480).
        out = weldment_breakdown(
            weld_length_mm=640.0,
            thicker_member_mm=3.0,
            members=[MemberCut(section_area_mm2=480.0, copies=4)],
            material_usd=42.0,
            cut_blanks_usd=0.0,
            quantities=(1, 10),
        )
        # Cited sizing
        assert out["fillet_leg_mm"] == 3.0
        assert "AWS D1.1 Table 5.7" in out["fillet_citation"]
        # Deposition math, hand-checked: mass 640×4.5×7.85e-6 = 0.022584 kg;
        # arc 0.022584/1.8 = 0.012547 h; clock ÷0.35 = 0.035848 h; labor
        # ×85 = $3.047; consumables ×6 = $0.1355.
        assert out["weld_metal_kg"] == pytest.approx(0.0226, abs=5e-4)  # rounded to 3dp in the payload
        assert out["weld_clock_hr"] == pytest.approx(0.03585, abs=5e-4)  # rounded to 3dp
        weld_labor = next(l for l in out["lines"] if l["line"] == "welding labor")
        assert weld_labor["usd"] == pytest.approx(3.05, abs=0.02)
        assert weld_labor["provenance"].startswith("uncalibrated")
        # Cut math: 4×480 = 1920 mm² ÷ 1935 mm²/min = 0.9922 min ≈ 0.01654 h ×85 = $1.406
        cut = next(l for l in out["lines"] if l["line"] == "member cutting (saw)")
        assert cut["usd"] == pytest.approx(1.41, abs=0.02)
        # Honesty rails
        assert out["basis"] == "uncalibrated_reference_rates"
        assert out["review"] == "unreviewed_by_practitioner"
        for q, tot in out["totals"].items():
            ci = tot["confidence"]
            assert ci["method"] == "assumption-band"
            assert ci["validated"] is False
            assert ci["half_width_pct"] == pytest.approx(60.0, abs=0.1)
            assert "UNCALIBRATED" in ci["basis"]
        # Qty10 ≥ qty1 (never a volume discount below the floor)
        assert out["totals"]["10"]["unit_cost_usd"] >= out["totals"]["1"]["unit_cost_usd"]

    def test_min_charge_floor_applies(self):
        out = weldment_breakdown(
            weld_length_mm=10.0, thicker_member_mm=3.0,
            members=[MemberCut(section_area_mm2=10.0, copies=1)],
            material_usd=0.5, quantities=(1,),
        )
        assert out["totals"]["1"]["unit_cost_usd"] == 75.0  # WeldmentRates.min_charge_usd

    def test_zero_weld_length_still_prices_members(self):
        out = weldment_breakdown(
            weld_length_mm=0.0, thicker_member_mm=3.0,
            members=[MemberCut(section_area_mm2=480.0, copies=2)],
            material_usd=10.0, quantities=(1,),
        )
        assert out["weld_metal_kg"] == 0.0
        assert out["totals"]["1"]["unit_cost_usd"] > 10.0

    def test_overridable_rates_change_the_answer(self):
        """The shop-override path: a governed rate card's rows flow through."""
        cheap = WeldmentRates(weld_station_usd_hr=40.0, saw_cut_mm2_min=3870.0)
        base = weldment_breakdown(
            weld_length_mm=640.0, thicker_member_mm=3.0,
            members=[MemberCut(section_area_mm2=480.0, copies=4)],
            material_usd=42.0, quantities=(1,))
        tuned = weldment_breakdown(
            weld_length_mm=640.0, thicker_member_mm=3.0,
            members=[MemberCut(section_area_mm2=480.0, copies=4)],
            material_usd=42.0, quantities=(1,), rates=cheap)
        assert tuned["totals"]["1"]["unit_cost_usd"] < base["totals"]["1"]["unit_cost_usd"]


class TestCalibrationSummary:
    def test_uncalibrated_until_three_quotes(self):
        assert calibration_summary(0)["status"] == "uncalibrated"
        assert calibration_summary(2)["status"] == "uncalibrated"
        assert calibration_summary(3)["status"] == "quotes_accruing"
        assert "ground truth" in calibration_summary(0)["words"]


class TestBandCoverageGate:
    """No reality to cover yet (zero weldment quotes anywhere) — so the gate
    inverts: the breakdown MUST present the wide assumption band and MUST NOT
    claim validation. The day paired quotes exist, this test flips to
    demanding coverage; the honest interim is enforced instead."""

    def test_unvalidated_never_claims_coverage(self):
        out = weldment_breakdown(
            weld_length_mm=640.0, thicker_member_mm=3.0,
            members=[MemberCut(section_area_mm2=480.0, copies=4)],
            material_usd=42.0, quantities=(1,))
        ci = out["totals"]["1"]["confidence"]
        assert ci["n_samples"] == 0
        assert ci["method"] == "assumption-band"
        assert ci["label"] == "assumption-based, not yet validated"
