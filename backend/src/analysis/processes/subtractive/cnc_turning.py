"""CNC Turning / Lathe."""

from src.analysis.context import GeometryContext
from src.analysis.models import Issue, ProcessType
from src.analysis.processes.base import register
from src.profiles.envelopes import common_envelope
from src.analysis.processes.checks import (
    check_build_volume,
    check_hole_depth_ratio,
    check_internal_shoulders,
    check_length_diameter_ratio,
    check_rotational_symmetry,
    check_sealed_voids,
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
        i.extend(check_sealed_voids(ctx, self.process))
        i.extend(check_rotational_symmetry(ctx, self.process, tolerance=0.15))
        i.extend(check_length_diameter_ratio(ctx, 10.0, self.process))
        # Bored holes on the lathe: past 8:1 the tool pecks (chip evacuation);
        # past 20:1 it is gun-drill/EDM territory. The costing layer turns the
        # measured ratio into a cycle-time penalty, so a ⌀2×55 bore (27:1)
        # never reads as a 2-minute, score-1.0 turn.
        i.extend(check_hole_depth_ratio(ctx, 8.0, self.process, severe_ratio=20.0))
        i.extend(check_internal_shoulders(ctx, self.process,
                 cite="Sandvik: turning inserts leave a nose radius; sharp bore "
                      "steps need a grooving tool or relief undercut."))
        i.extend(check_wall_thickness(ctx, 1.0, self.process,
                 cite="Turning thin walls chatter; 1.0mm min."))
        i.extend(check_build_volume(ctx, common_envelope(self.process), self.process,
                 cite="Common size; e.g. Haas ST-20 (10in chuck)."))
        return i
