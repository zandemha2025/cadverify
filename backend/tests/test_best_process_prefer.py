"""A tie at the top DFM score goes to the process the cost route named.

The assembly check passes the make-now process and the routing pick as the
preference. Both are often the same process (["cnc_turning", "cnc_turning"]),
and the duplicate collapsed the preference so the named process ranked level
with every unnamed one: a bolt whose milling and turning both scored 1.0 read
"best: 3-axis milling" though its route said turning.
"""
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.models import AnalysisResult, ProcessScore, ProcessType
from src.matcher.profile_matcher import best_process_for_material


def _result():
    mesh = trimesh.creation.cylinder(radius=5, height=40)
    scores = [ProcessScore(process=p, score=1.0, verdict="pass")
              for p in (ProcessType.CNC_3AXIS, ProcessType.CNC_5AXIS, ProcessType.CNC_TURNING)]
    return AnalysisResult(filename="bolt.step", file_type="step", geometry=analyze_geometry(mesh),
                          process_scores=scores)


def test_a_repeated_preference_still_wins_the_tie():
    result = _result()
    assert best_process_for_material(result, "aluminum", prefer=["cnc_turning", "cnc_turning"]) == ProcessType.CNC_TURNING
    assert best_process_for_material(result, "aluminum", prefer=["cnc_5axis", "cnc_turning"]) == ProcessType.CNC_5AXIS
    assert best_process_for_material(result, "aluminum") == ProcessType.CNC_3AXIS
