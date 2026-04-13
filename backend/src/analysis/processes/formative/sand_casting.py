"""Sand Casting — big iron, heavy industrial."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_core_feasibility,
    check_draft_angles,
    check_fillet_requirements,
    check_shrinkage_risk,
    check_wall_uniformity,
)


@register
class SandCastingAnalyzer:
    process = ProcessType.SAND_CASTING
    standards = [
        "AFS Casting Design Handbook",
        "ASTM A536 — Ductile iron castings",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_draft_angles(ctx, 3.0, self.process,
                 cite="AFS: 3° min — rougher mold surface."))
        i.extend(check_wall_uniformity(ctx, 3.0, 100.0, 8.0, self.process,
                 cite="AFS: 3mm min gray iron, 5mm steel."))
        i.extend(check_fillet_requirements(ctx, 3.0, self.process,
                 cite="AFS: 3mm min fillet — hot tear prevention."))
        i.extend(check_shrinkage_risk(ctx, self.process, max_compactness=12.0))
        i.extend(check_core_feasibility(ctx, self.process))
        return i
