"""Investment Casting — lost-wax process."""

from src.analysis.context import GeometryContext
from src.analysis.models import Citation, Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
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
        i = [Issue(
            code="PATTERN_TOOLING_REVIEW",
            severity=Severity.INFO,
            message="Investment casting has no universal minimum draft angle; pattern and core tooling need separate review.",
            process=self.process,
            fix_suggestion=(
                "Confirm wax-pattern and ceramic-core release with the foundry. "
                "Some tooling geometries need draft even though the casting shell is broken away."
            ),
            citation=Citation(
                standard="Impro Precision",
                text="Draft Angles in Investment Casting — https://www.improprecision.com/draft-angles-investment-casting/",
            ),
        )]
        i.extend(check_wall_uniformity(ctx, 1.0, 50.0, 5.0, self.process,
                 cite="ICI: 1mm min wall achievable."))
        i.extend(check_fillet_requirements(ctx, 0.5, self.process,
                 cite="ICI: 0.5mm min fillet."))
        i.extend(check_shrinkage_risk(ctx, self.process, max_compactness=15.0))
        return i
