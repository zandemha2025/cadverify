"""CNC Turning / Lathe."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.analysis.processes.checks import (
    check_build_volume,
    check_length_diameter_ratio,
    check_rotational_symmetry,
    check_wall_thickness,
)


@register
class CNCTurningAnalyzer:
    process = ProcessType.CNC_TURNING
    standards = [
        "Haas ST-20 specifications",
        "Sandvik Coromant Turning Guide (2024)",
    ]

    def analyze(self, ctx: GeometryContext) -> list[Issue]:
        i: list[Issue] = []
        i.extend(check_rotational_symmetry(ctx, self.process, tolerance=0.15))
        i.extend(check_length_diameter_ratio(ctx, 10.0, self.process))
        i.extend(check_wall_thickness(ctx, 1.0, self.process,
                 cite="Turning thin walls chatter; 1.0mm min."))
        i.extend(check_build_volume(ctx, (254, 254, 533), self.process,
                 cite="Haas ST-20 (10in chuck)."))
        return i
