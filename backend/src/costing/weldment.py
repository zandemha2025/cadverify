"""Weldment fabrication costing — cut-list members plus weld deposition.

The GEOMETRY this consumes is measured upstream (``src.analysis.part_types``):
stock profiles with section areas, member lengths, cut-list grouping, and a
weld-length estimate from contact-patch outlines. This module turns that into
dollars with every constant carrying either a named source or an explicit
UNCALIBRATED label — nothing tuned, nothing silent.

Cited:
  - Minimum fillet leg by the thicker member joined: AWS D1.1 Table 5.7
    (renumbered Table 7.7 in AWS D1.1:2020+:2025), structural steel.
  - Equal-leg 90° fillet cross-section = leg²/2 (geometry).
  - Steel density 7850 kg/m³ (standard carbon-steel value).
  - Cost methodology: labor&overhead $/hr ÷ (deposition rate × operator
    factor) + consumables $/kg — the standard welding-cost formulation
    (Lincoln Electric, "Determining the Cost of Welding" / Procedure
    Handbook of Arc Welding cost chapters).

UNCALIBRATED (defaults; governed shop rate cards and the quote-back flywheel
tighten them — a weldment share link's vendor quotes land as ground truth
with process ``weldment_fab``):
  deposition rate, operator factor, weld-station $/hr, consumables $/kg,
  saw area-removal rate, setup/handling/min-charge/lot.

The band is the house's widest assumption tier (±60%, matching the stated
DED band for deposition-rate models: "coarse + shop-specific"), stated as an
assumption band through the same ``ConfidenceInterval`` honesty the per-part
engine uses: never ``validated`` until real ground truth backs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# ── CITED ────────────────────────────────────────────────────────────────────

# AWS D1.1 Table 5.7 (2025: Table 7.7): minimum fillet weld size by the
# thickness of the THICKER part joined (mm breakpoints → mm leg).
_AWS_D1_1_T5_7_MIN_FILLET: tuple[tuple[float, float], ...] = (
    (6.0, 3.0),      # base metal ≤ 6mm            → 3mm leg
    (12.0, 5.0),     # over 6 to 12mm              → 5mm
    (20.0, 6.0),     # over 12 to 20mm             → 6mm
    (38.0, 8.0),     # over 20 to 38mm             → 8mm
    (63.0, 10.0),    # over 38 to 63mm             → 10mm
    (float("inf"), 13.0),  # over 63mm             → 13mm
)

STEEL_DENSITY_KG_M3 = 7850.0          # standard carbon steel
_KG_PER_MM3 = STEEL_DENSITY_KG_M3 * 1e-9


def min_fillet_leg_mm(thicker_member_mm: float) -> float:
    """AWS D1.1 Table 5.7 minimum fillet leg for the thicker member joined."""
    if thicker_member_mm <= 0:
        raise ValueError("thicker_member_mm must be positive")
    for limit, leg in _AWS_D1_1_T5_7_MIN_FILLET:
        if thicker_member_mm <= limit:
            return leg
    return 13.0  # unreachable; inf row above catches everything


def weld_metal_mass_kg(weld_length_mm: float, leg_mm: float) -> float:
    """Deposited weld metal for an equal-leg 90° fillet of this length:
    cross-section leg²/2 × length × steel density (the overweld-free minimum
    the table leg implies; real shops deposit more, which the band carries)."""
    if weld_length_mm < 0 or leg_mm <= 0:
        raise ValueError("weld_length_mm >= 0 and leg_mm > 0 required")
    return weld_length_mm * (leg_mm * leg_mm / 2.0) * _KG_PER_MM3


# ── UNCALIBRATED DEFAULTS (each named in PROVENANCE below) ──────────────────

@dataclass(frozen=True)
class WeldmentRates:
    """The weldment fabrication rates. Defaults are UNCALIBRATED; every field
    is overridable per shop once governed rate cards carry weldment rows."""

    deposition_kg_per_arc_hr: float = 1.8     # 4 lb/h — low end of published
    operator_factor: float = 0.35             # published typical 30–40%
    weld_station_usd_hr: float = 85.0         # published calculator example
    consumables_usd_kg: float = 6.0           # wire + gas, order-of-magnitude
    saw_cut_mm2_min: float = 1935.0           # 3 in²/min A36 structural family
    setup_hr: float = 0.75
    handling_hr_per_member: float = 0.05
    min_charge_usd: float = 75.0
    lot_size: float = 25.0


# Machine-readable provenance: every constant, its status, and its source.
# The CI gate (tests/test_weldment_costing.py) asserts this table covers
# every WeldmentRates field — a new rate without a row fails the build.
PROVENANCE: dict[str, dict[str, str]] = {
    "deposition_kg_per_arc_hr": {
        "status": "uncalibrated",
        "source": ("4 lb/h: low end of the 4–8.5 lb/h GMAW semi-automatic "
                   "range in published welding-cost worked examples on the "
                   "Lincoln Electric cost methodology (Deposition Rate = "
                   "13.1·D²·WFS·EE). Conservative: low rate → longer time."),
    },
    "operator_factor": {
        "status": "uncalibrated",
        "source": ("0.35: the published typical 30–40% arc-on share for "
                   "manual/semi-automatic GMAW (Lincoln Electric cost "
                   "methodology; Sheet Metal Welding Guide)."),
    },
    "weld_station_usd_hr": {
        "status": "uncalibrated",
        "source": ("$85/hr: a published MIG fillet-weld cost calculator's "
                   "shop labor+overhead example. Shop-specific by nature; a "
                   "shop's rate card overrides."),
    },
    "consumables_usd_kg": {
        "status": "uncalibrated",
        "source": ("~$6/kg wire+gas order-of-magnitude from published "
                   "welding-cost calculators; filler/spec changes it."),
    },
    "saw_cut_mm2_min": {
        "status": "uncalibrated",
        "source": ("3 in²/min (1935 mm²/min): area-removal order for A36 "
                   "structural on bi-metal band saw per LENOX speed-chart "
                   "family (A36 structural ≈ 250 ft/min blade speed); a "
                   "shop's SawCalc output overrides."),
    },
    "setup_hr": {"status": "uncalibrated",
                 "source": "fixture + program + first-article; shop-specific."},
    "handling_hr_per_member": {"status": "uncalibrated",
                               "source": "load/align/tack per member."},
    "min_charge_usd": {"status": "uncalibrated",
                       "source": "fabrication floor, mirrors the sheet row."},
    "lot_size": {"status": "uncalibrated",
                 "source": "learning-curve batch reference."},
}

# The band: the house's widest stated assumption tier — the same ±60% the
# DED family carries for deposition-rate models ("coarse + shop-specific").
WELDMENT_ASSUMPTION_BAND_PCT = 60.0


@dataclass
class MemberCut:
    """One cut-list row's cutting work: the blade sweeps the member's section."""
    section_area_mm2: float
    copies: int = 1


def weldment_breakdown(
    *,
    weld_length_mm: float,
    thicker_member_mm: float,
    members: Sequence[MemberCut],
    material_usd: float,
    cut_blanks_usd: float = 0.0,
    quantities: Sequence[int] = (1,),
    rates: Optional[WeldmentRates] = None,
) -> dict:
    """Dollars for one weldment: member stock + cutting + weld deposition.

    Fillet sizing is CITED (AWS D1.1 Table 5.7 off the file's thickest member
    — conservative for mixed-thickness frames: a bigger leg on every joint).
    Rates are the uncalibrated defaults unless overridden. The confidence is
    an ASSUMPTION band (±60%), never validated, until real quotes exist.
    """
    r = rates or WeldmentRates()
    if weld_length_mm < 0:
        raise ValueError("weld_length_mm >= 0 required")

    leg = min_fillet_leg_mm(thicker_member_mm) if thicker_member_mm > 0 else None
    weld_mass = weld_metal_mass_kg(weld_length_mm, leg) if leg else None
    if weld_mass is not None:
        arc_hr = weld_mass / r.deposition_kg_per_arc_hr
        weld_clock_hr = arc_hr / r.operator_factor
        weld_labor_usd = weld_clock_hr * r.weld_station_usd_hr
        weld_consumables_usd = weld_mass * r.consumables_usd_kg
    else:
        arc_hr = weld_clock_hr = weld_labor_usd = weld_consumables_usd = None

    cut_area_mm2 = sum(m.section_area_mm2 * max(1, int(m.copies)) for m in members)
    # saw_cut_mm2_min is an AREA-PER-MINUTE rate; the station rate is hourly.
    cut_hr = cut_area_mm2 / r.saw_cut_mm2_min / 60.0 if cut_area_mm2 > 0 else 0.0
    cut_usd = cut_hr * r.weld_station_usd_hr if cut_hr else None
    handling_usd = (len(members) and
                    sum(max(1, int(m.copies)) for m in members)
                    * r.handling_hr_per_member * r.weld_station_usd_hr)
    setup_usd = r.setup_hr * r.weld_station_usd_hr

    one_off = (material_usd + cut_blanks_usd + (cut_usd or 0.0)
               + (weld_labor_usd or 0.0) + (weld_consumables_usd or 0.0)
               + handling_usd + setup_usd)

    per_qty: dict[str, dict] = {}
    for q in quantities:
        q = max(1, int(q))
        # Learning on repetition: the HOUSE curve (rate-card learning_rate/
        # floor globals, their own stated assumptions) on TOUCH LABOR only —
        # cut + weld labor + handling. Material and consumables scale with
        # mass, never learn. Setup amortizes across the batch.
        from src.costing.learning import lot_average_factor
        from src.costing.rates import build_rate_card

        rc = build_rate_card()
        touch_usd = (cut_usd or 0.0) + (weld_labor_usd or 0.0) + handling_usd
        if q > r.lot_size:
            lf = lot_average_factor(rc.g("learning_rate") or 0.9,
                                    r.lot_size, rc.g("learning_floor") or 0.7, q)
            touch_usd *= lf
        total = (material_usd + cut_blanks_usd
                 + (weld_consumables_usd or 0.0)) * q + touch_usd * q + setup_usd
        total = max(total, r.min_charge_usd)
        from src.costing.confidence import ConfidenceInterval

        ci = ConfidenceInterval(
            low_usd=total * (1 - WELDMENT_ASSUMPTION_BAND_PCT / 100.0),
            high_usd=total * (1 + WELDMENT_ASSUMPTION_BAND_PCT / 100.0),
            point_usd=total, level=0.80,
            method="assumption-band", validated=False, n_samples=0,
            basis=(f"±{WELDMENT_ASSUMPTION_BAND_PCT:.0f}% assumption band "
                   "(the stated wide tier for deposition-rate models); rates "
                   "are UNCALIBRATED reference defaults — see provenance"),
            label="assumption-based, not yet validated",
        )
        per_qty[str(q)] = {
            "unit_cost_usd": round(total, 2),
            "confidence": ci.to_dict(),
        }

    lines = [
        {"line": "member stock (list $/kg)", "usd": round(material_usd, 2),
         "provenance": "measured stock × list price"},
        {"line": "plate blanks (sheet route)", "usd": round(cut_blanks_usd, 2),
         "provenance": "sheet-metal route"},
        {"line": "member cutting (saw)", "usd": None if cut_usd is None else round(cut_usd, 2),
         "provenance": "uncalibrated: " + PROVENANCE["saw_cut_mm2_min"]["source"]},
        {"line": "welding labor", "usd": None if weld_labor_usd is None else round(weld_labor_usd, 2),
         "provenance": "uncalibrated: " + PROVENANCE["weld_station_usd_hr"]["source"]},
        {"line": "weld consumables", "usd": None if weld_consumables_usd is None else round(weld_consumables_usd, 2),
         "provenance": "uncalibrated: " + PROVENANCE["consumables_usd_kg"]["source"]},
        {"line": "handling + setup", "usd": round(handling_usd + setup_usd, 2),
         "provenance": "uncalibrated: shop-specific"},
    ]
    return {
        "fillet_leg_mm": leg,
        "fillet_citation": ("AWS D1.1 Table 5.7 (2025: Table 7.7) minimum "
                            f"fillet for the thicker member ≤ {thicker_member_mm:g}mm"),
        "weld_metal_kg": None if weld_mass is None else round(weld_mass, 3),
        "weld_clock_hr": None if weld_clock_hr is None else round(weld_clock_hr, 3),
        "member_cut_area_mm2": round(cut_area_mm2, 1),
        "lines": lines,
        "totals": per_qty,
        "one_off_usd": round(one_off, 2),
        "basis": "uncalibrated_reference_rates",
        "review": "unreviewed_by_practitioner",
    }


def calibration_summary(quote_rows: int) -> dict:
    """The honest calibration state for the payload: quotes accumulate under
    process ``weldment_fab`` (share-link quote-back lands them as ground
    truth); the band stays the wide assumption tier until prediction↔quote
    pairing is wired and n ≥ 3 REAL quotes exist."""
    return {
        "status": "uncalibrated" if quote_rows < 3 else "quotes_accruing",
        "weldment_quotes_on_file": quote_rows,
        "words": (
            "Rates are uncalibrated reference defaults; the band is the wide "
            "assumption tier. Vendor quotes on a weldment's share link land as "
            "ground truth (process weldment_fab) and tighten this once "
            "prediction↔quote pairing ships and ≥3 real quotes exist."
        ),
    }
