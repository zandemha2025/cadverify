"""Forging — impression die, hot / cold."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_draft_angles,
    check_fillet_requirements,
    check_undercuts_from_z,
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
        i.extend(check_undercuts_from_z(ctx, self.process,
                 cite="Forging: no undercuts — die cannot open."))
        i.extend(check_wall_thickness(ctx, 3.0, self.process,
                 cite="FIA: 3mm min web thickness."))
        i.extend(self._check_rib_aspect(ctx))
        return i

    def _check_rib_aspect(self, ctx: GeometryContext) -> list[Issue]:
        """Rib height:width must be <= 6:1 for forging."""
        # Approximate via bounding box min dimension (web) vs max (rib height)
        dims = sorted(ctx.info.bounding_box.dimensions)
        if dims[0] < 0.1:
            return []
        ratio = dims[2] / dims[0]
        if ratio <= 6.0:
            return []
        return [Issue(
            code="HIGH_RIB_RATIO",
            severity=Severity.WARNING,
            message=(
                f"Aspect ratio {ratio:.1f}:1 exceeds 6:1 max rib "
                f"height:width for {self.process.value}."
            ),
            process=self.process,
            measured_value=ratio,
            required_value=6.0,
            fix_suggestion="Reduce rib height or increase web thickness. FIA §4.2.",
        )]
