"""Metric fastener standards catalog + catalog-checkable identification.

WHAT THIS IS
------------
A REAL reference table of published ISO/DIN metric-fastener dimensions, and a
matcher that takes a MEASURED across-flats width (from ``features.across_flats``)
and identifies the standard fastener envelope it corresponds to — e.g.
"M12 hex nut · ISO 4032 / DIN 934, across-flats 18.0 mm (standard) vs 18.1 mm
(measured)".

HONESTY / PROVENANCE
--------------------
Every dimension below is a PUBLISHED STANDARD value quoted from the referenced ISO/
DIN standard — it is NOT measured by CadVerify. Sources:
  * Hex nuts — ISO 4032 (metric hexagon regular nuts, style 1), width across flats
    ``s`` and thickness ``m`` (max). Equivalent legacy norm: DIN 934. Where ISO
    reduced the across-flats vs the older DIN 934 (M10, M12, M14) we take the ISO
    4032 value as CANONICAL and record the legacy DIN across-flats in ``din_af_mm``.
    Verified against fasteners.eu/standards/iso/4032 and wermac.org ISO-4032 tables.
  * Hex-head bolts/screws — ISO 4014 (partially threaded) / ISO 4017 (fully
    threaded), head width across flats ``s``. Equivalent legacy norms: DIN 931 /
    DIN 933 (which keep the older larger M10/M12/M14 across-flats — recorded in
    ``din_af_mm``).
  * Socket-head cap screws — ISO 4762, head diameter ``dk`` (max) and hex-key size
    ``s`` (the internal drive across-flats). Equivalent legacy norm: DIN 912.
  * Coarse thread pitch — ISO 261 / ISO 262 coarse-series pitch (mm).

These are STANDARD ENVELOPES, not SKUs: they identify which standard a part
conforms to, never a grade/class/material (8.8, A2-70, …) or a manufacturer part
number — none of which geometry can determine.
"""

from __future__ import annotations

from typing import Any, Optional

# ── ISO 261 / ISO 262 coarse-series thread pitch (mm) ───────────────────────────
_COARSE_PITCH_MM: dict[str, float] = {
    "M1.6": 0.35, "M2": 0.40, "M2.5": 0.45, "M3": 0.50, "M4": 0.70,
    "M5": 0.80, "M6": 1.00, "M8": 1.25, "M10": 1.50, "M12": 1.75,
    "M14": 2.00, "M16": 2.00, "M20": 2.50, "M24": 3.00,
}

# ── ISO 4032 hex nuts (≈ DIN 934) ───────────────────────────────────────────────
# (nominal, across_flats_mm [ISO 4032], thickness_mm [m max], din_af_mm | None)
# din_af_mm is set only where the legacy DIN 934 across-flats differs from ISO 4032.
_ISO_4032_NUTS: list[tuple[str, float, float, Optional[float]]] = [
    ("M1.6", 3.20, 1.30, None),
    ("M2",   4.00, 1.60, None),
    ("M2.5", 5.00, 2.00, None),
    ("M3",   5.50, 2.40, None),
    ("M4",   7.00, 3.20, None),
    ("M5",   8.00, 4.70, None),
    ("M6",  10.00, 5.20, None),
    ("M8",  13.00, 6.80, None),
    ("M10", 16.00, 8.40, 17.00),   # ISO 4032 reduced 17 -> 16 vs DIN 934
    ("M12", 18.00, 10.80, 19.00),  # ISO 4032 reduced 19 -> 18 vs DIN 934
    ("M14", 21.00, 12.80, 22.00),  # ISO 4032 reduced 22 -> 21 vs DIN 934
    ("M16", 24.00, 14.80, None),
    ("M20", 30.00, 18.00, None),
    ("M24", 36.00, 21.50, None),
]

# ── ISO 4014 / ISO 4017 hex-head bolts & screws (≈ DIN 931 / DIN 933) ───────────
# Head width across flats mirrors ISO 4032 for these sizes; legacy DIN 931/933 keep
# the older larger M10/M12/M14 across-flats (recorded in din_af_mm).
# (nominal, head_across_flats_mm, din_af_mm | None)
_ISO_4014_BOLTS: list[tuple[str, float, Optional[float]]] = [
    ("M3",   5.50, None),
    ("M4",   7.00, None),
    ("M5",   8.00, None),
    ("M6",  10.00, None),
    ("M8",  13.00, None),
    ("M10", 16.00, 17.00),
    ("M12", 18.00, 19.00),
    ("M14", 21.00, 22.00),
    ("M16", 24.00, None),
    ("M20", 30.00, None),
    ("M24", 36.00, None),
]

# ── ISO 4762 socket-head cap screws (≈ DIN 912) ─────────────────────────────────
# (nominal, head_diameter_dk_mm [max], hex_key_across_flats_mm)
# NOTE: the EXTERNAL head is CYLINDRICAL, so an external across-flats caliper reads
# the head DIAMETER dk (matched here), NOT a hex — the hex is the internal drive.
_ISO_4762_SHCS: list[tuple[str, float, float]] = [
    ("M3",   5.50, 2.5),
    ("M4",   7.00, 3.0),
    ("M5",   8.50, 4.0),
    ("M6",  10.00, 5.0),
    ("M8",  13.00, 6.0),
    ("M10", 16.00, 8.0),
    ("M12", 18.00, 10.0),
    ("M14", 21.00, 12.0),
    ("M16", 24.00, 14.0),
    ("M20", 30.00, 17.0),
    ("M24", 36.00, 19.0),
]

# Standard designation per kind (ISO first, legacy DIN in parens).
_KIND_STANDARD = {
    "nut":  ("ISO 4032", "hex nut", "ISO 4032 / DIN 934"),
    "bolt": ("ISO 4014", "hex-head bolt", "ISO 4014 / ISO 4017 (≈ DIN 931 / DIN 933)"),
    "screw": ("ISO 4017", "hex-head screw", "ISO 4017 / ISO 4014 (≈ DIN 933 / DIN 931)"),
    "socket_head_cap_screw": (
        "ISO 4762", "socket-head cap screw", "ISO 4762 (≈ DIN 912)"),
}

# Which kinds are matched on an EXTERNAL HEX across-flats (so a hex ratio is
# expected). Socket-head cap screws are matched on a round head diameter instead.
_HEX_KINDS = {"nut", "bolt", "screw"}

# Largest across-flats residual (mm) we will call a match at all. Beyond this the
# measurement is not near ANY standard size, so we honestly return None.
_MATCH_TOLERANCE_MM = 1.2


def _pitch_for(nominal: str) -> Optional[float]:
    return _COARSE_PITCH_MM.get(nominal)


def _nut_thickness(nominal: str) -> Optional[float]:
    for n, _af, m, _din in _ISO_4032_NUTS:
        if n == nominal:
            return m
    return None


def match_by_across_flats(af_mm: float, kind: str) -> Optional[dict[str, Any]]:
    """Match a MEASURED across-flats (mm) to the closest standard fastener.

    Args:
        af_mm: measured across-flats (for hex kinds) or head diameter (for a
            socket-head cap screw), in mm.
        kind: one of {"nut", "bolt", "screw", "socket_head_cap_screw"}.

    Returns the closest standard entry with the AF residual, or None if nothing is
    within a sane tolerance (``_MATCH_TOLERANCE_MM``). Keys:
        nominal, standard_id, designation, pitch_coarse_mm, af_nominal_mm,
        residual_mm, din_af_mm (legacy DIN across-flats where it differs, else None),
        measured_dimension ("across_flats" | "head_diameter").
    """
    try:
        af = float(af_mm)
    except (TypeError, ValueError):
        return None
    if af <= 0:
        return None

    if kind == "socket_head_cap_screw":
        table = [(n, dk, None) for (n, dk, _key) in _ISO_4762_SHCS]
        measured_dimension = "head_diameter"
    elif kind == "nut":
        table = [(n, af_n, din) for (n, af_n, _m, din) in _ISO_4032_NUTS]
        measured_dimension = "across_flats"
    elif kind in ("bolt", "screw"):
        table = list(_ISO_4014_BOLTS)
        measured_dimension = "across_flats"
    else:
        return None

    std_id, kind_label, designation_std = _KIND_STANDARD[kind]

    best = None
    best_residual = None
    for nominal, af_nominal, din_af in table:
        residual = abs(af - af_nominal)
        if best_residual is None or residual < best_residual:
            best_residual = residual
            best = (nominal, af_nominal, din_af)

    if best is None or best_residual > _MATCH_TOLERANCE_MM:
        return None

    nominal, af_nominal, din_af = best
    return {
        "nominal": nominal,
        "standard_id": std_id,
        "kind_label": kind_label,
        "designation_std": designation_std,
        "pitch_coarse_mm": _pitch_for(nominal),
        "af_nominal_mm": round(float(af_nominal), 3),
        "residual_mm": round(float(best_residual), 3),
        "din_af_mm": din_af,
        "measured_dimension": measured_dimension,
    }


def identify_standard_fastener(part, kind: str, features=None) -> Optional[dict[str, Any]]:
    """Identify the standard fastener a COTS part conforms to — MEASURED + CATALOG.

    Measures the part's real across-flats (reusing the cylinder detector for the bore
    axis when ``features`` are supplied), matches it to the ISO/DIN catalog, and
    returns an honest identity block ONLY when confident (high/medium). Returns None
    when the geometry does not cleanly match a standard — in which case the caller
    keeps the existing APPROXIMATE ``nominal_size`` rather than overwriting it with a
    false identification.

    HONESTY: never claims grade/class/material (8.8, A2-70), never claims fine vs
    coarse pitch (coarse is ASSUMED and labelled so), never claims a manufacturer
    SKU — it identifies the standard ENVELOPE only.
    """
    from src.analysis.features.across_flats import measure_across_flats

    mesh = getattr(part, "mesh", None)
    if mesh is None or len(getattr(mesh, "faces", [])) == 0:
        return None

    meas = measure_across_flats(mesh, features=features)
    if meas is None:
        return None

    af_measured = meas["across_flats_mm"]
    ratio = meas["ac_af_ratio"]
    hex_kind = kind in _HEX_KINDS

    # For a socket-head cap screw the external caliper reads the round head diameter,
    # so the AC/AF ratio is ~1 (never a hex) — that is expected, not a demerit. Both
    # hex and round kinds match on the minimum caliper width (across-flats / head ø).
    match = match_by_across_flats(af_measured, kind)
    if match is None:
        return None

    residual = match["residual_mm"]
    hex_consistent = meas["hex_consistent"]

    # Confidence gate.
    #   HIGH   : AF within 0.6mm of a standard AND (for a hex kind) the shape is
    #            hex-consistent (ratio ~1.10-1.22).
    #   MEDIUM : AF within 0.6mm but shape not hex-confirmed, OR AF within 1.0mm
    #            with a hex-consistent shape.
    #   LOW    : neither -> return None (keep the approximate size).
    if hex_kind:
        hex_confirmed = hex_consistent
        if residual <= 0.6 and hex_confirmed:
            confidence = "high"
        elif residual <= 0.6 and not hex_confirmed:
            confidence = "medium"
        elif residual <= 1.0 and hex_confirmed:
            confidence = "medium"
        else:
            confidence = "low"
    else:
        # Socket-head cap screw: matched on head diameter (round), no hex claim.
        hex_confirmed = False
        confidence = "high" if residual <= 0.6 else ("medium" if residual <= 1.0 else "low")

    if confidence == "low":
        return None

    nominal = match["nominal"]
    pitch = match["pitch_coarse_mm"]
    kind_label = match["kind_label"]
    thread = (
        f"{nominal} × {pitch:g} (coarse, assumed)" if pitch is not None else
        f"{nominal} (coarse pitch assumed)"
    )
    designation = f"{nominal} {kind_label} ({match['designation_std']})"

    caveats = [
        "Pitch assumed coarse (ISO 261 coarse series) — fine-pitch variants share "
        "this across-flats envelope and are not distinguishable from geometry.",
        "Grade / material / property class (e.g. 8.8, A2-70) is NOT determinable "
        "from geometry.",
        "Identifies the standard ENVELOPE, not a specific manufacturer SKU.",
    ]
    if hex_kind and not hex_confirmed:
        caveats.insert(0, (
            f"Cross-section is not a clean hexagon (across-corners / across-flats "
            f"= {ratio:.3f}, a regular hex is ~1.155) — the across-flats matches the "
            f"standard size but the hex form is NOT confirmed from geometry."
        ))
    if match.get("din_af_mm") is not None:
        caveats.append(
            f"ISO {match['standard_id'].split()[-1]} across-flats "
            f"{match['af_nominal_mm']:g} mm taken as canonical; legacy DIN "
            f"across-flats for this size is {match['din_af_mm']:g} mm."
        )

    provenance = (
        f"MEASURED (across-flats, axis via {meas['axis_source']}) + "
        f"CATALOG ({match['standard_id']})"
    )

    return {
        "standard_id": match["standard_id"],
        "designation": designation,
        "nominal": nominal,
        "thread": thread,
        "across_flats_mm_measured": af_measured,
        "across_flats_mm_standard": match["af_nominal_mm"],
        "residual_mm": residual,
        "across_corners_mm_measured": meas["across_corners_mm"],
        "ac_af_ratio": ratio,
        "hex_confirmed": bool(hex_confirmed),
        "confidence": confidence,
        "provenance": provenance,
        "measured_dimension": match["measured_dimension"],
        "axis_source": meas["axis_source"],
        "caveats": caveats,
    }
