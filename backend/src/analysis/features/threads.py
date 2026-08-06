"""Tapped-hole INFERENCE — not a geometric thread detector.

A triangle mesh exported from CAD essentially never carries actual helical
thread geometry (threads are almost always suppressed/simplified for
manufacturing exports, or represented as a plain cylindrical bore). So we
cannot and do not *detect* a thread here. What we can honestly do is flag
that a hole's diameter happens to match a standard ISO metric tap-drill
size closely enough that it is plausibly meant to be tapped.

This is attached as metadata on the existing CYLINDER_HOLE feature — the
hole's ``kind`` is never changed, and no ``FeatureKind.THREAD`` feature is
ever emitted by this module. Downstream code must read
``metadata["possibly_tapped"]`` as "possibly tapped (inferred from
diameter)", never as "thread detected".
"""

from __future__ import annotations

from src.analysis.features.base import Feature, FeatureKind

# tap-drill diameter (mm) -> nominal metric thread size.
# Coarse-pitch ISO metric tap drills (common shop reference values).
_TAP_DRILL_TO_THREAD_MM: dict[float, str] = {
    2.5: "M3",
    3.3: "M4",
    4.2: "M5",
    5.0: "M6",
    6.8: "M8",
    8.5: "M10",
    10.2: "M12",
}

_MATCH_TOLERANCE_MM = 0.25


def infer_tapped_holes(
    features: list[Feature], tolerance_mm: float = _MATCH_TOLERANCE_MM
) -> list[Feature]:
    """Tag CYLINDER_HOLE features whose diameter matches a standard tap-drill size.

    Mutates and returns the same list. For each CYLINDER_HOLE feature whose
    diameter (2*radius) is within ``tolerance_mm`` of a standard metric
    tap-drill diameter, sets on that feature's ``metadata``:
        possibly_tapped: True
        nearest_thread: e.g. "M6"
        tap_drill_diameter_mm: the matched standard diameter
        tap_drill_diameter_delta_mm: measured diameter minus the standard one

    Holes with no close match are left untouched (no ``possibly_tapped``
    key at all — absence, not ``False``, so callers can't accidentally read
    a negative result as a positive one about untouched features from
    before this function existed).
    """
    for f in features:
        if f.kind is not FeatureKind.CYLINDER_HOLE:
            continue
        if f.radius is None or f.radius <= 0:
            continue
        diameter = 2.0 * f.radius

        best_match: tuple[float, str] | None = None
        best_delta = tolerance_mm
        for tap_drill_dia, thread in _TAP_DRILL_TO_THREAD_MM.items():
            delta = abs(diameter - tap_drill_dia)
            if delta <= best_delta:
                best_delta = delta
                best_match = (tap_drill_dia, thread)

        if best_match is not None:
            tap_drill_dia, thread = best_match
            f.metadata["possibly_tapped"] = True
            f.metadata["nearest_thread"] = thread
            f.metadata["tap_drill_diameter_mm"] = tap_drill_dia
            f.metadata["tap_drill_diameter_delta_mm"] = diameter - tap_drill_dia

    return features
