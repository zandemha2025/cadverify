"""CAD source-unit handling (B5) — the units landmine defense.

STL carries no unit metadata; the engine has always interpreted vertex
coordinates as MILLIMETRES. An inch-authored STL therefore silently mis-costs by
25.4**3 (~16,387x) — a confidently-wrong number wrapped in a valid-looking band.
That is the worst failure mode for a pilot (one inch part and the tool looks
broken or dishonest). Two INDEPENDENT defenses live here:

  1. An EXPLICIT declaration: the caller states the source units (mm|inch) and
     the mesh is scaled into mm BEFORE any geometry/DFM/cost extraction runs. mm
     (default/unset) is a no-op (scale 1.0), so the mm path is byte-identical.

  2. An HONEST safety net, independent of the declaration: a plausibility check
     on the mm-interpreted geometry. If a single part reads as bigger than a
     ~1 m^3 envelope or smaller than a grain, we surface a structured WARNING
     telling the user to confirm mm vs inch. We never silently proceed with a
     ~16,000x-wrong number; the warning is the honest state, not a fabricated
     correction.
"""

from __future__ import annotations

SOURCE_UNITS = ("mm", "inch")
MM_PER_INCH = 25.4

# Plausibility envelope for ONE manufacturable part, in the engine's mm
# interpretation. Deliberately GENEROUS (egregious-only): the explicit unit
# declaration is the primary defense; this net exists to catch a catastrophic
# unit error, not to second-guess every unusual part. A false alarm on a real
# part is itself a credibility hit, so the bounds are wide. These are stated
# assumptions, not shop-validated thresholds.
PLAUSIBLE_MAX_VOLUME_CM3 = 1_000_000.0   # 1 m^3 — larger than any single part these processes make
PLAUSIBLE_MIN_VOLUME_CM3 = 1e-3          # 1 mm^3 — smaller than a grain; a real part is never this small
PLAUSIBLE_MAX_BBOX_MM = 5_000.0          # 5 m longest edge
PLAUSIBLE_MIN_BBOX_MM = 0.5              # half a mm longest edge


def unit_scale(units: str) -> float:
    """Linear scale factor from DECLARED source units into mm (the engine's unit).

    inch -> 25.4; anything else (mm / unset) -> 1.0 (byte-identical no-op)."""
    return MM_PER_INCH if units == "inch" else 1.0


def scale_mesh_to_mm(mesh, units: str):
    """Return a mesh whose vertices are in mm, given the DECLARED source units.

    mm (default) => the SAME mesh object, untouched => byte-identical. inch => a
    COPY scaled x25.4 on every axis, so volume (x25.4**3), area (x25.4**2), bbox
    and wall thickness all stay coherent — DFM, machine-fit and cost then read
    the one real part. This MUST run before geometry/DFM extraction so nothing
    downstream is left interpreting inch coordinates as mm."""
    if units == "inch":
        mesh = mesh.copy()
        mesh.apply_scale(MM_PER_INCH)
    return mesh


def implausible_volume_warning(volume_cm3, max_bbox_mm, assumed_units: str = "mm"):
    """Structured WARNING when the mm-interpreted geometry is implausible for a
    single part — the honest units safety net. Returns None when plausible.

    Provenance-honest: the volume/bbox are MEASURED from the CAD; the UNITS are
    ASSUMED. This never fabricates a corrected number — it flags that the assumed
    units may be wrong (mm vs inch) so the caller confirms rather than trusting a
    confidently-wrong band. Fires only on egregiously out-of-range geometry, so
    the default mm path on any real part is untouched.
    """
    v = float(volume_cm3 or 0.0)
    b = float(max_bbox_mm or 0.0)
    too_big = v > PLAUSIBLE_MAX_VOLUME_CM3 or b > PLAUSIBLE_MAX_BBOX_MM
    too_small = (0.0 < v < PLAUSIBLE_MIN_VOLUME_CM3) or (0.0 < b < PLAUSIBLE_MIN_BBOX_MM)
    if not (too_big or too_small):
        return None
    direction = "larger" if too_big else "smaller"
    if too_small:
        hint = ("If this part was authored in inches, declare units=inch so it is "
                "scaled x25.4 into mm — an inch STL read as mm mis-costs by "
                "~16,000x.")
    else:
        hint = ("If this part was authored in metres or another unit, re-export in "
                "mm or declare the correct source units.")
    return {
        "code": "IMPLAUSIBLE_VOLUME",
        "severity": "warning",
        "message": (
            f"Part volume {v:g} cm3 (longest edge {b:g} mm) is {direction} than a "
            f"plausible single part under the assumed units ({assumed_units}). "
            f"Confirm the CAD source units (mm vs inch). " + hint
        ),
        "measured": {"volume_cm3": round(v, 6), "max_bbox_mm": round(b, 4)},
        "assumed_units": assumed_units,
        # The volume/bbox are MEASURED; the units are an ASSUMPTION. This flag is
        # the honest state — never a corrected number.
        "provenance": "measured-geometry-vs-assumed-units",
    }
