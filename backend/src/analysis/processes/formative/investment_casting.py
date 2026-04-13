"""Investment Casting — lost-wax process."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_draft_angles,
    check_fillet_requirements,
    check_shrinkage_risk,
    check_wall_uniformity,
)


@register
class InvestmentCastingAnalyzer:
    process = ProcessType.INVESTMENT_CASTING
    standards = [
        "AMS 2175 — Investment casting acceptance",
        "ASTM A732 — Steel castings",
        "Investment Casting Institute design guide",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_draft_angles(ctx, 0.5, self.process,
                 cite="ICI: 0.5° min — less than other casting methods."))
        i.extend(check_wall_uniformity(ctx, 1.0, 50.0, 5.0, self.process,
                 cite="ICI: 1mm min wall achievable."))
        i.extend(check_fillet_requirements(ctx, 0.5, self.process,
                 cite="ICI: 0.5mm min fillet."))
        i.extend(check_shrinkage_risk(ctx, self.process, max_compactness=15.0))
        return i
