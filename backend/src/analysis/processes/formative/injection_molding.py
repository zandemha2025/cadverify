"""Injection Molding — the money maker."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType, Severity
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_draft_angles,
    check_undercuts_molding,
    check_wall_uniformity,
)
from src.analysis.features.base import FeatureKind


@register
class InjectionMoldingAnalyzer:
    process = ProcessType.INJECTION_MOLDING
    standards = [
        "Protolabs Injection Molding Design Guide (2024)",
        "DFMPro — IM rules engine",
        "GE Plastics Design Guide — wall thickness",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_draft_angles(ctx, 1.0, self.process,
                 cite="Protolabs: 1° min external, 2° internal."))
        i.extend(check_wall_uniformity(ctx, 0.5, 6.0, 2.5, self.process,
                 cite="GE Plastics: 0.5–6mm, ideal 2.5mm for ABS."))
        i.extend(check_undercuts_molding(ctx, self.process,
                 cite="Side actions add $5–15K tooling."))
        i.extend(self._check_rib_rules(ctx))
        i.extend(self._check_boss_rules(ctx))
        return i

    def _check_rib_rules(self, ctx: GeometryContext) -> list[Issue]:
        """Ribs: thickness <= 0.6x adjacent wall, height <= 3x wall."""
        issues: list[Issue] = []
        for f in ctx.features:
            if f.kind != FeatureKind.FLAT or f.area is None:
                continue
            # Rib detection is best-effort via feature aspect ratio
        # Simplified: flag as guidance
        if ctx.info.face_count > 200:
            issues.append(Issue(
                code="RIB_RULES_CHECK",
                severity=Severity.INFO,
                message=(
                    "Ribs should be <= 0.6x adjacent wall thickness with "
                    "0.5° draft per side. Height <= 3x wall."
                ),
                process=self.process,
                fix_suggestion="Verify ribs per Protolabs IM guide §4.3.",
            ))
        return issues

    def _check_boss_rules(self, ctx: GeometryContext) -> list[Issue]:
        bosses = [f for f in ctx.features if f.kind == FeatureKind.CYLINDER_BOSS]
        if not bosses:
            return []
        issues: list[Issue] = []
        for b in bosses:
            if b.radius and b.radius < 1.5:
                issues.append(Issue(
                    code="THIN_BOSS",
                    severity=Severity.WARNING,
                    message=(
                        f"Boss at ({b.centroid[0]:.0f}, {b.centroid[1]:.0f}, "
                        f"{b.centroid[2]:.0f}) has {b.radius * 2:.1f}mm OD — "
                        "wall may be too thin for molding."
                    ),
                    process=self.process,
                    region_center=b.centroid,
                    fix_suggestion="Boss OD should be >= 2x ID. Add gussets.",
                ))
        return issues
