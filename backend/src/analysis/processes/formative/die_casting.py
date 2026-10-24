"""Die Casting — zinc, aluminum, magnesium."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_draft_angles,
    check_fillet_requirements,
    check_undercuts_molding,
    check_wall_uniformity,
)


@register
class DieCastingAnalyzer:
    process = ProcessType.DIE_CASTING
    standards = [
        "NADCA Product Specification Standards §3",
        "NADCA Die Casting Design Guide (2024)",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_draft_angles(ctx, 1.0, self.process,
                 cite="NADCA §3: 1° min external, 2° internal."))
        i.extend(check_wall_uniformity(ctx, 0.8, 12.0, 3.0, self.process,
                 cite="NADCA: 0.8–12mm, uniform preferred."))
        i.extend(check_fillet_requirements(ctx, 1.0, self.process,
                 cite="NADCA: 1mm min fillet at internal corners."))
        i.extend(check_undercuts_molding(ctx, self.process,
                 cite="Slides required — adds tooling cost."))
        return i
