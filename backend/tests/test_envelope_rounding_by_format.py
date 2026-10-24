"""A part at a larger machine's exact size takes that machine from an STL too.

A binary STL stores float32 coordinates, so the engine pads the part's
enclosing box by that rounding (a few hundredths of a micron on a 400 mm cube).
The fallback "it fits a larger machine ScaleCAD knows" compared the padded box
with the machine as an exact limit: the STL of a 400 mm cube read "larger than
any metal powder printing (DMLS) machine ScaleCAD knows" (can't as drawn) while
the STEP of the same cube fit the 400 x 400 x 400 mm EOS M 400-4.
"""
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType, Severity
from src.analysis.processes.base import get_analyzer
from src.parsers.stl_parser import parse_stl_from_bytes


def _envelope_issues(mesh, process):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    return [i for i in get_analyzer(process).analyze(ctx) if "BUILD" in i.code or "ENVELOPE" in i.code]


def test_a_400mm_cube_fits_the_400mm_metal_printer_from_stl_and_exact_coordinates():
    exact = trimesh.creation.box(extents=(400.0, 400.0, 400.0))
    exact.apply_translation((200.0, 200.0, 200.0))
    stl = parse_stl_from_bytes(exact.export(file_type="stl"), "cube400.stl")
    assert stl.metadata["coordinate_error"] > 0
    answers = []
    for mesh in (exact, stl):
        issues = _envelope_issues(mesh, ProcessType.DMLS)
        assert [i.code for i in issues] == ["EXCEEDS_BUILD_VOLUME"]
        assert issues[0].severity == Severity.WARNING
        assert "It fits a larger metal powder printing (DMLS) machine" in issues[0].message
        answers.append(issues[0].message)
    assert answers[0] == answers[1]
