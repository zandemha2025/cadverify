"""Forging — impression die, hot / cold."""

from src.analysis.process_names import process_phrase
from src.analysis.context import GeometryContext
from src.analysis.serialization import format_measurement
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_draft_angles,
    check_fillet_requirements,
    check_setup_access,
    check_wall_thickness,
)


@register
class ForgingAnalyzer:
    process = ProcessType.FORGING
    standards = [
        "Forging Industry Association Design Guide (2024)",
        "ASTM A788 — Steel forgings",
        "API 6A — Wellhead equipment (oil & gas forgings)",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_draft_angles(ctx, 5.0, self.process,
                 cite="FIA: 5° external, 7-10° internal."))
        i.extend(check_fillet_requirements(ctx, 3.0, self.process,
                 cite="FIA: 3mm min corner radius for die life."))
        i.extend(check_setup_access(ctx, self.process,
                 cite="For forging, confirm die pull direction, parting line and core removal."))
        i.extend(check_wall_thickness(ctx, 3.0, self.process,
                 cite="FIA: 3mm min web thickness."))
        i.extend(self._check_rib_aspect(ctx))
        return i

    def _check_rib_aspect(self, ctx: GeometryContext) -> list[Issue]:
        """Rib height:thickness must be <= 6:1 for forging.

        Measured on detected ribs (``ctx.ribs``: thin plates standing out
        from the part along one root), not on the bounding box: a flat plate
        has no rib.
        """
        limit = 6.0
        tall = [r for r in ctx.ribs if r["height_mm"] / r["thickness_mm"] > limit]
        if not tall:
            return []
        worst = tall[0]
        ratio = worst["height_mm"] / worst["thickness_mm"]
        where = ", ".join(f"{c:.0f}" for c in worst["center"])
        return [Issue(
            code="HIGH_RIB_RATIO",
            measurement_unit="ratio",
            severity=Severity.WARNING,
            message=(
                f"Rib at ({where}) is {format_measurement(worst['height_mm'])}mm tall and "
                f"{format_measurement(worst['thickness_mm'])}mm thick: {format_measurement(ratio, limit)}:1 "
                f"exceeds the 6:1 rib height:thickness limit for {process_phrase(self.process)}"
                + (f" ({len(tall)} ribs over it)." if len(tall) > 1 else ".")
            ),
            process=self.process,
            region_center=worst["center"],
            measured_value=ratio,
            required_value=limit,
            fix_suggestion="Reduce rib height or thicken the rib. FIA §4.2.",
        )]
