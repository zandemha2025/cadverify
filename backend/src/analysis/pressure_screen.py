"""The pressure-retaining wall screen — ASME BPVC VIII-1 UG-27, clause-anchored.

WHAT THIS IS: a geometry screen that joins three already-measured quantities
(the verified revolution axis + outer diameter, the largest coaxial bore, and
the ray-cast minimum wall thickness) with a caller-declared rated pressure and
material grade, then computes the UG-27 required thickness and compares.

WHAT THIS IS NOT (and says so in every message): an ASME certification. The
joint is unknown, so E = 0.70 (UW-12, Type 1 butt joint, no radiography) is
ASSUMED, conservatively. The allowable is computed on the Section II-D basis
(lesser of 2/3·Sy and 1/3.5·Su) from the material file's declared
room-temperature properties — it is NOT a Section II-D table lookup and
carries NO temperature derating. Outside UG-27's validity domain the screen
declines (Appendix 1-1 thick-wall formulas are not implemented here).

Every constant below is either the clause itself or a stated assumption;
none is a tuned number. Sources:
  - ASME BPVC Section VIII Division 1, UG-27(c)(1)/(c)(2) thickness formulas
    and their validity limits (t <= 0.5R or P <= 0.385·S·E).
  - ASME BPVC Section VIII Division 1, UW-12 joint efficiencies (Type 1 butt
    joints: full RT 1.00, spot 0.85, none 0.70 — the screen assumes none).
  - ASME Section II Part D allowable-stress basis (lesser of 2/3 yield and
    1/3.5 ultimate) as the stated computation basis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.analysis.features.base import FeatureKind
from src.analysis.models import Citation, Issue, Severity

# UW-12, Type 1 (full-penetration butt) joint, no radiography: E = 0.70.
# Nothing about a random uploaded part's joints is known, so the lowest
# ordinary butt-joint value is assumed and stated — never silently upgraded.
JOINT_EFFICIENCY_ASSUMED = 0.70

# Axis-alignment tolerance for calling a bore coaxial with the verified
# revolution axis: within 10 degrees (|cos| >= cos(10°) = 0.9848).
_COAXIAL_MIN_ABS_COS = 0.9848

# Section II-D basis as arithmetic: S = min(2/3 * yield, ultimate / 3.5).
_BASIS_TWO_THIRDS_YIELD = 2.0 / 3.0
_BASIS_UTS_OVER = 3.5


@dataclass(frozen=True)
class PressureScreenInput:
    """Everything the screen needs that geometry cannot provide."""

    rated_pressure_bar: float          # caller-declared design pressure
    material_grade: str                # caller-declared grade, e.g. "316L"
    yield_mpa: Optional[float]         # material file's declared room-temp yield
    tensile_mpa: Optional[float]       # material file's declared room-temp UTS


def allowable_stress_mpa(yield_mpa: Optional[float], tensile_mpa: Optional[float]):
    """S on the Section II-D basis from declared room-temperature properties.

    Returns ``(S, basis_words)``; ``(None, why)`` when neither property is on
    file. This is the stated basis, not a Section II-D table value: no
    temperature derating, no product form credit.
    """
    candidates = []
    if yield_mpa is not None and yield_mpa > 0:
        candidates.append((_BASIS_TWO_THIRDS_YIELD * yield_mpa, "2/3·Sy"))
    if tensile_mpa is not None and tensile_mpa > 0:
        candidates.append((tensile_mpa / _BASIS_UTS_OVER, "Su/3.5"))
    if not candidates:
        return None, "no declared yield or tensile strength on file"
    s, basis = min(candidates, key=lambda c: c[0])
    words = "lesser of " + " and ".join(f"{b} = {v:.1f} MPa" for v, b in candidates)
    words += " (ASME Section II Part D basis, computed from declared room-temperature properties; not a table lookup; no temperature derating)"
    return s, words


def ug27_required_thickness_mm(p_mpa: float, r_inside_mm: float, s_mpa: float, e: float):
    """(t_circumferential, t_longitudinal) per UG-27(c)(1) and (c)(2), MPa/mm.

    UG-27(c)(1): t = P·R / (S·E − 0.6·P)   — circumferential (hoop) stress,
    longitudinal joints; valid for t <= 0.5R or P <= 0.385·S·E.
    UG-27(c)(2): t = P·R / (2·S·E + 0.4·P) — longitudinal stress,
    circumferential joints; valid for t <= 0.5R or P <= 1.25·S·E.
    """
    t_circ = p_mpa * r_inside_mm / (s_mpa * e - 0.6 * p_mpa)
    t_long = p_mpa * r_inside_mm / (2.0 * s_mpa * e + 0.4 * p_mpa)
    return t_circ, t_long


def _bore_radius_mm(ctx) -> tuple[Optional[float], Optional[object]]:
    """Largest CYLINDER_HOLE coaxial with the part's verified revolution axis.

    The bore radius is what UG-27's R means (inside radius), so a bore found
    off-axis is ignored rather than averaged in.
    """
    axis = _verified_axis(ctx)
    if axis is None:
        return None, None
    best = None
    for f in ctx.features:
        if getattr(f, "kind", None) != FeatureKind.CYLINDER_HOLE:
            continue
        radius = getattr(f, "radius", None)
        f_axis = getattr(f, "axis", None)
        if not radius or f_axis is None:
            continue
        cos = abs(float(np.dot(np.asarray(f_axis, dtype=float), axis)))
        if cos < _COAXIAL_MIN_ABS_COS:
            continue
        if best is None or radius > best.radius:
            best = f
    return (float(best.radius) if best else None), best


def _verified_axis(ctx):
    """The axis the turning measurements use, so bore and outer diameter are
    read along ONE axis (roundness-verified, not an inertia guess)."""
    try:
        from src.analysis.features.base import verified_revolution_axis

        return verified_revolution_axis(ctx.mesh, ctx.features)
    except Exception:
        return None


def _outer_diameter_mm(ctx) -> Optional[float]:
    try:
        from src.analysis.features.base import turning_dimensions

        dims = turning_dimensions(ctx.mesh, ctx.features)
        if dims is None:
            return None
        _length, diameter, _roundness = dims
        return float(diameter) if diameter and diameter > 0 else None
    except Exception:
        return None


def _measured_min_wall_mm(ctx) -> tuple[Optional[float], Optional[float]]:
    """(measured minimum finite wall, its proved upper bound) in mm.

    The upper bound is the honest companion: the true wall at the thinnest
    spot is at most this, even under source-coordinate error.
    """
    wt = getattr(ctx, "wall_thickness", None)
    if wt is None:
        return None, None
    finite = np.isfinite(wt)
    if not finite.any():
        return None, None
    upper = getattr(ctx, "wall_thickness_upper", None)
    upper_min = float(np.min(upper[finite])) if upper is not None else None
    return float(np.min(wt[finite])), upper_min


def run_pressure_screen(ctx, screen_in: PressureScreenInput) -> list[Issue]:
    """The whole screen. Returns [] when it cannot run, plus one issue that
    says WHY it cannot — never a silent skip when the caller asked for it.

    Emits exactly one issue: PASS (INFO), FAIL (ERROR), or a decline
    (WARNING) with the reason. All carry the clause citations and the
    not-a-certification boundary in the message.
    """
    boundary = (
        "Geometry screen per ASME VIII-1 UG-27 — not a certification. "
        f"E = {JOINT_EFFICIENCY_ASSUMED:.2f} assumed (UW-12, un-radiographed butt joint). "
        "Allowable computed on the Section II-D basis from declared room-temperature "
        "properties; no temperature derating."
    )
    p_mpa = screen_in.rated_pressure_bar / 10.0

    def decline(reason: str) -> list[Issue]:
        return [Issue(
            code="PRESSURE_SCREEN_UNAVAILABLE",
            severity=Severity.WARNING,
            message=f"Pressure screen could not run: {reason}. {boundary}",
            process=None,
            citation=Citation(
                standard="ASME BPVC Section VIII Division 1",
                clause="UG-27",
                text="Required-thickness formulas for cylindrical shells under internal pressure.",
            ),
        )]

    od = _outer_diameter_mm(ctx)
    if od is None:
        return decline("no verified revolution axis — the part does not read as a cylinder of revolution")
    bore_r, _bore_feature = _bore_radius_mm(ctx)
    if bore_r is None:
        return decline("no coaxial bore found — R (inside radius) is unknown, so UG-27 cannot be evaluated")
    s_mpa, s_basis = allowable_stress_mpa(screen_in.yield_mpa, screen_in.tensile_mpa)
    if s_mpa is None:
        return decline(f"material '{screen_in.material_grade}' has {s_basis}")

    nominal_wall = (od - 2.0 * bore_r) / 2.0
    if nominal_wall <= 0:
        return decline("bore is as large as the outer diameter — no pressure wall exists")

    # UG-27(c)(1) validity: t <= 0.5R or P <= 0.385·S·E. Outside it the
    # screen declines rather than applying the thin-shell formula where the
    # code does not (Appendix 1-1 is not implemented here).
    if nominal_wall > 0.5 * bore_r and p_mpa > 0.385 * s_mpa * JOINT_EFFICIENCY_ASSUMED:
        return decline(
            f"outside UG-27(c) validity domain (nominal wall {nominal_wall:.2f}mm > 0.5R "
            f"= {0.5 * bore_r:.2f}mm and P {p_mpa:.2f}MPa > 0.385·S·E) — thick-wall "
            "Appendix 1-1 formulas are not implemented"
        )

    t_circ, t_long = ug27_required_thickness_mm(p_mpa, bore_r, s_mpa, JOINT_EFFICIENCY_ASSUMED)
    t_required = max(t_circ, t_long)  # circumferential governs unless degenerate

    measured_min, upper_min = _measured_min_wall_mm(ctx)
    tol = None
    try:
        from src.analysis.context import wall_thickness_tolerance

        tol = wall_thickness_tolerance(ctx.mesh, ctx.scale_eps)
    except Exception:
        tol = None

    breakdown = [
        {"label": "bore_radius_R_mm", "value": round(bore_r, 3), "clause": "UG-27"},
        {"label": "outer_diameter_mm", "value": round(od, 3)},
        {"label": "nominal_wall_mm", "value": round(nominal_wall, 3)},
        {"label": "required_t_circumferential_mm",
         "value": round(t_circ, 3), "clause": "UG-27(c)(1)"},
        {"label": "required_t_longitudinal_mm",
         "value": round(t_long, 3), "clause": "UG-27(c)(2)"},
        {"label": "allowable_S_mpa", "value": round(s_mpa, 1),
         "basis": s_basis, "clause": "Section II Part D basis"},
        {"label": "joint_efficiency_E", "value": JOINT_EFFICIENCY_ASSUMED,
         "basis": "UW-12 Type 1 butt joint, no radiography (assumed)", "clause": "UW-12"},
    ]
    if measured_min is not None:
        breakdown.append({"label": "measured_min_wall_mm", "value": round(measured_min, 3)})
        if upper_min is not None:
            breakdown.append({"label": "measured_min_wall_upper_bound_mm",
                              "value": round(upper_min, 3)})

    cite_ug27 = Citation(
        standard="ASME BPVC Section VIII Division 1",
        clause="UG-27(c)(1)",
        text="t = P·R/(S·E − 0.6·P) for circumferential stress; UG-27(c)(2) "
             "t = P·R/(2·S·E + 0.4·P) for longitudinal stress.",
    )

    if measured_min is None:
        return decline("wall thickness could not be measured on this mesh")

    if measured_min < t_required - (tol or 0.0):
        return [Issue(
            code="PRESSURE_SCREEN_FAIL",
            severity=Severity.ERROR,
            message=(
                f"Measured minimum wall {measured_min:.2f}mm is below the UG-27 required "
                f"{t_required:.2f}mm at {screen_in.rated_pressure_bar:g} bar for "
                f"{screen_in.material_grade}. {boundary}"
            ),
            process=None,
            measured_value=measured_min,
            required_value=t_required,
            measurement_unit="mm",
            breakdown=breakdown,
            citation=cite_ug27,
            fix_suggestion=(
                "Increase wall thickness, reduce rated pressure, declare a stronger "
                "grade, or have the joint radiographed (E rises per UW-12) — then "
                "confirm with a certified vessel calculation."
            ),
        )]

    unresolved = tol is not None and (measured_min - t_required) < tol
    severity = Severity.WARNING if unresolved else Severity.INFO
    code = "PRESSURE_SCREEN_MARGIN_UNRESOLVED" if unresolved else "PRESSURE_SCREEN_PASS"
    margin = measured_min - t_required
    ratio = measured_min / t_required if t_required > 0 else float("inf")
    lead = (
        f"Measured minimum wall {measured_min:.2f}mm vs UG-27 required {t_required:.2f}mm "
        f"({ratio:.2f}×) at {screen_in.rated_pressure_bar:g} bar for {screen_in.material_grade}."
    )
    if unresolved:
        lead = (
            f"Measured minimum wall {measured_min:.2f}mm is within measuring precision "
            f"({tol:.2f}mm) of the UG-27 required {t_required:.2f}mm — the screen cannot "
            f"resolve the margin at {screen_in.rated_pressure_bar:g} bar."
        )
    return [Issue(
        code=code,
        severity=severity,
        message=f"{lead} {boundary}",
        process=None,
        measured_value=measured_min,
        required_value=t_required,
        measurement_unit="mm",
        breakdown=breakdown,
        citation=cite_ug27,
    )]
