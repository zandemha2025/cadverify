"""Sheet Metal — bend, punch, laser cut."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_bends,
    check_sheet_gauge,
)


@register
class SheetMetalAnalyzer:
    process = ProcessType.SHEET_METAL
    standards = [
        "DIN 6935 — Cold bending of flat steel",
        "SMACNA Architectural Sheet Metal Manual §5",
        "Trumpf TruPunch design guidelines",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_sheet_gauge(ctx, self.process))
        i.extend(check_bends(ctx, self.process,
                 cite="DIN 6935: radius >= thickness."))
        i.extend(self._check_hole_placement(ctx))
        return i

    def _check_hole_placement(self, ctx: GeometryContext) -> list[Issue]:
        from src.analysis.features.base import FeatureKind
        holes = [f for f in ctx.features if f.kind == FeatureKind.CYLINDER_HOLE]
        if not holes:
            return []
        dims = sorted(ctx.info.bounding_box.dimensions)
        t = dims[0]
        issues: list[Issue] = []
        for h in holes:
            if h.radius and h.radius * 2 < t:
                issues.append(Issue(
                    code="SMALL_HOLE_SHEET",
                    severity=Severity.WARNING,
                    message=(
                        f"Hole Ø{h.radius * 2:.1f}mm < gauge {t:.1f}mm at "
                        f"({h.centroid[0]:.0f}, {h.centroid[1]:.0f}, {h.centroid[2]:.0f})."
                    ),
                    process=self.process,
                    region_center=h.centroid,
                    fix_suggestion=f"Hole diameter must be >= gauge ({t:.1f}mm). SMACNA §5.2.",
                ))
        return issues
