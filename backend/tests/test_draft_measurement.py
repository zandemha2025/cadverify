"""INSUFFICIENT_DRAFT reports the draft the part actually has, not only the limit."""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType, Severity
from src.analysis.processes.checks import _shown_draft, check_draft_angles, draft_sidewalls
from src.analysis.serialization import serialize_issue

ASSETS = Path(__file__).parent / "assets"


def _tapered_box(width: float, depth: float, height: float, draft_deg: float) -> trimesh.Trimesh:
    """A block whose four sides lean inward by ``draft_deg`` from the base up."""
    inset = height * math.tan(math.radians(draft_deg))
    w, d = width / 2.0, depth / 2.0
    points = [(x, y, 0.0) for x in (-w, w) for y in (-d, d)]
    points += [(x, y, height) for x in (-w + inset, w - inset) for y in (-d + inset, d - inset)]
    return trimesh.convex.convex_hull(np.array(points))


def _ctx(mesh: trimesh.Trimesh, *, features: bool = True) -> GeometryContext:
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    if features:
        ctx.features = detect_all(ctx.mesh)
    return ctx


def _draft(ctx, limit, process=ProcessType.INJECTION_MOLDING):
    issues = check_draft_angles(ctx, limit, process, cite="Protolabs: 1° min external, 2° internal.")
    assert len(issues) <= 1
    return issues[0] if issues else None


def test_straight_walled_box_measures_zero_draft():
    issue = _draft(_ctx(trimesh.creation.box(extents=[40.0, 30.0, 25.0])), 1.0)
    assert issue is not None
    assert issue.code == "INSUFFICIENT_DRAFT" and issue.severity == Severity.ERROR
    assert issue.measured_value == 0.0 and math.copysign(1.0, issue.measured_value) == 1.0
    assert issue.required_value == 1.0 and issue.measurement_unit == "deg"
    assert issue.message.endswith("Smallest draft: 0.0°. The tool opens along the file's +Z.")
    out = serialize_issue(issue)
    assert out["measured_value"] == 0.0 and out["required_value"] == 1.0
    assert out["measurement_unit"] == "deg"


def test_two_degree_taper_passes_one_degree_and_fails_three_with_its_angle():
    ctx = _ctx(_tapered_box(60.0, 40.0, 20.0, 2.0))
    assert _draft(ctx, 1.0) is None
    issue = _draft(ctx, 3.0, ProcessType.SAND_CASTING)
    assert issue is not None
    assert issue.measured_value == pytest.approx(2.0, abs=1e-9)
    assert issue.required_value == 3.0
    assert "below 3.0° draft for sand casting. Smallest draft: 2.0°." in issue.message
    assert len(issue.affected_faces) == 8  # four leaning sides, two triangles each


def test_message_keeps_the_sentence_the_screens_already_read():
    issue = _draft(_ctx(_tapered_box(60.0, 40.0, 20.0, 0.4)), 1.0)
    # derive.ts blockerSentence / tooling.ts draftOf / shared-derive firstClause
    legacy = re.compile(r"([0-9]+) sidewall faces \(([0-9.]+)% of sidewall area\) below ([0-9.]+)° draft")
    assert legacy.match(issue.message)
    assert re.search(r"below ([0-9]+(?:\.[0-9]+)?)\s*°\s*draft", issue.message).group(1) == "1.0"
    first = re.split(r"(?<=\.)\s", issue.message)[0]
    assert first == "8 sidewall faces (100.0% of sidewall area) below 1.0° draft for injection molding."
    assert issue.measured_value == 0.4


def test_shown_draft_rounds_to_a_tenth_but_never_up_to_the_limit():
    assert _shown_draft(1.99999997, 3.0) == 2.0
    assert _shown_draft(0.96, 1.0) == 0.9
    assert _shown_draft(0.04, 1.0) == 0.0
    assert _shown_draft(2.97, 3.0) == 2.9
    assert _shown_draft(1e-9, 0.05) == 0.0


def test_no_features_keeps_the_single_value():
    issue = _draft(_ctx(trimesh.creation.box(extents=[20.0, 15.0, 10.0]), features=False), 1.0)
    # The single value, then the pull direction the check assumed.
    assert issue.message.endswith("Smallest draft: 0.0°. The tool opens along the file's +Z.")


def test_bored_block_reports_zero_draft_for_walls_and_bore():
    """The approved find-and-fix sample: a 20 × 15 × 10 mm block with a vertical bore."""
    from src.api.routes import _parse_mesh, _run_cost_engine

    path = ASSETS / "bored-block-mm.iges"
    mesh, _suffix = _parse_mesh(path.read_bytes(), path.name)
    result, _mesh, _features = _run_cost_engine(mesh, path.name)
    scores = {s.process: s for s in result.process_scores}
    seen = {}
    # Molding, die casting and forging ask more of the bore (an inside wall: the
    # part shrinks onto the core there) than of the outside walls; sand casting has one rule.
    for process, outside, inside in ((ProcessType.INJECTION_MOLDING, 1.0, 2.0), (ProcessType.DIE_CASTING, 1.0, 2.0),
                                     (ProcessType.FORGING, 5.0, 7.0)):
        issue = next(i for i in scores[process].issues if i.code == "INSUFFICIENT_DRAFT")
        assert issue.measured_value == 0.0 and issue.required_value == inside
        assert issue.message.endswith(
            f"Smallest draft: 0.0° (outside walls 0.0°, need {outside:g}°; inside walls 0.0°, need {inside:g}°). "
            "The tool opens along the file's +Z.")
        assert [(b["walls"], b["need_deg"]) for b in issue.breakdown] == [("outside", outside), ("inside", inside)]
        assert issue.cad_face_count == 5  # four outside walls and the bore, as a CAD tool counts them
        seen[process] = issue
    issue = next(i for i in scores[ProcessType.SAND_CASTING].issues if i.code == "INSUFFICIENT_DRAFT")
    assert issue.measured_value == 0.0 and issue.required_value == 3.0 and issue.breakdown is None
    assert issue.message.endswith("Smallest draft: 0.0° (outer walls 0.0°, bore 0.0°). The tool opens along the file's +Z.")
    # The bore's facets spread 0–0.8° from tessellation; the reading is still 0.0.
    assert len(seen[ProcessType.INJECTION_MOLDING].affected_faces) > 100_000


def test_rule_packs_and_alternatives_keep_the_measured_draft():
    from src.analysis.rules import get_rule_pack
    from src.fixes.fix_suggester import ALTERNATIVE_PROCESS_MAP

    issue = _draft(_ctx(trimesh.creation.box(extents=[40.0, 30.0, 25.0])), 1.0)
    for name, process in (("automotive", ProcessType.INJECTION_MOLDING), ("oil_gas", ProcessType.FORGING)):
        issue.process = process
        (out,) = [i for i in get_rule_pack(name).apply([issue], process) if i.code == "INSUFFICIENT_DRAFT"]
        assert out.severity == Severity.ERROR
        assert out.measured_value == 0.0 and out.required_value == 1.0
        assert f"[{name}]" in out.fix_suggestion
    assert "INSUFFICIENT_DRAFT" in ALTERNATIVE_PROCESS_MAP


# ── de-09 / de-02: a correct drafted model passes; inside walls get the inside rule ──

def _drafted_open_box_step(path: Path, draft_deg: float, *, boss: bool = False) -> Path:
    """An 80 × 60 × 40 mm open box, 2.5 mm walls, every side wall drafted ``draft_deg`` (planar faces).

    Lofted from rectangles, as a CAD tool's draft leaves them: outside walls lean in
    going up, inside walls lean out (the cavity opens upward). ``boss``: a 3°-drafted
    round boss (a cone) stands on the floor inside.
    """
    import gmsh

    t = math.tan(math.radians(draft_deg))
    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("drafted-box")
        occ = gmsh.model.occ

        def wire(x0, y0, x1, y1, z):
            p = [occ.addPoint(x0, y0, z), occ.addPoint(x1, y0, z), occ.addPoint(x1, y1, z), occ.addPoint(x0, y1, z)]
            return occ.addWire([occ.addLine(p[i], p[(i + 1) % 4]) for i in range(4)])

        def loft(x0, y0, x1, y1, z0, z1, inset):
            out = occ.addThruSections([wire(x0, y0, x1, y1, z0),
                                       wire(x0 + inset, y0 + inset, x1 - inset, y1 - inset, z1)],
                                      makeSolid=True, makeRuled=True)
            return [e for e in out if e[0] == 3]

        h = 40.0
        outer = loft(0, 0, 80, 60, 0, h, h * t)
        # Cavity: 2.5 mm walls at the top, narrower at the floor (z = 2.5), open above.
        top_inset = 2.5 + h * t
        bottom_inset = top_inset + (h - 2.5) * t
        cavity = loft(bottom_inset, bottom_inset, 80 - bottom_inset, 60 - bottom_inset, 2.5, h + 1.0,
                      -(h + 1.0 - 2.5) * t)
        body, _ = occ.cut(outer, cavity)
        if boss:
            r0 = 6.0
            cone = occ.addCone(40, 30, 2.4, 0, 0, 15, r0, r0 - 15 * math.tan(math.radians(3.0)))
            occ.fuse(body, [(3, cone)])
        occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def _step_ctx(path: Path) -> GeometryContext:
    from src.api.routes import _parse_mesh

    mesh, _suffix = _parse_mesh(path.read_bytes(), path.name)
    return _ctx(mesh)


def test_exact_draft_in_a_step_is_read_from_the_brep_not_its_triangles(tmp_path):
    """de-09: every side face drawn at exactly 3.0° meets sand casting's 3° (it read 2.9°)."""
    from src.analysis.context import cad_face_count

    ctx = _step_ctx(_drafted_open_box_step(tmp_path / "revB.step", 3.0, boss=True))
    assert ctx.wall_draft.exact and cad_face_count(ctx.mesh) > 0
    # The triangles alone read the 3° boss (a cone) as low as ~2.6°: their reading would fail it.
    _faces, triangle_draft = draft_sidewalls(ctx.angles_from_up_deg)
    assert float(triangle_draft.min()) < 2.95
    assert _draft(ctx, 3.0, ProcessType.SAND_CASTING) is None
    assert _draft(ctx, 1.0, ProcessType.INJECTION_MOLDING) is None
    issue = check_draft_angles(ctx, 5.0, ProcessType.FORGING, internal_deg=7.0)[0]
    assert issue.measured_value == 3.0 and issue.required_value == 7.0


def test_a_short_draft_still_fails_with_its_angle(tmp_path):
    ctx = _step_ctx(_drafted_open_box_step(tmp_path / "short.step", 2.5))
    issue = _draft(ctx, 3.0, ProcessType.SAND_CASTING)
    assert issue is not None and issue.measured_value == 2.5 and issue.required_value == 3.0
    assert "Smallest draft: 2.5°" in issue.message


def test_inside_walls_get_the_inside_rule(tmp_path):
    """de-02: 1.5° everywhere meets molding's 1° outside but not its 2° inside."""
    from src.analysis.processes.base import get_analyzer
    import src.analysis.processes  # noqa: F401  (registers the analyzers)

    ctx = _step_ctx(_drafted_open_box_step(tmp_path / "onehalf.step", 1.5))
    (issue,) = [i for i in get_analyzer(ProcessType.INJECTION_MOLDING).analyze(ctx) if i.code == "INSUFFICIENT_DRAFT"]
    assert issue.required_value == 2.0 and issue.measured_value == 1.5
    outside, inside = issue.breakdown
    assert (outside["walls"], outside["faces"], outside["need_deg"]) == ("outside", 0, 1.0)
    assert (inside["walls"], inside["need_deg"], inside["measured_deg"], inside["cad_faces"]) == ("inside", 2.0, 1.5, 4)
    assert issue.cad_face_count == 4
    assert "below 2.0° draft on inside walls for injection molding" in issue.message
    assert issue.fix_suggestion.startswith("Add >= 2.0° draft to the inside walls along the pull direction")


def _cone_stl(draft_deg: float, segments: int = 24) -> trimesh.Trimesh:
    """A drafted round boss as a CAD tool's STL exports it: facets through the cone's generators."""
    h, r0 = 20.0, 10.0
    r1 = r0 - h * math.tan(math.radians(draft_deg))
    a = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    low = np.c_[r0 * np.cos(a), r0 * np.sin(a), np.zeros(segments)]
    high = np.c_[r1 * np.cos(a), r1 * np.sin(a), np.full(segments, h)]
    return trimesh.convex.convex_hull(np.vstack([low, high]))


def test_a_tessellated_cone_gets_the_benefit_of_its_facets_lean():
    """An STL can't carry the B-rep: its facets read a 3° cone at 2.97°; their lean is bounded."""
    ctx = _ctx(_cone_stl(3.0))
    _faces, triangle_draft = draft_sidewalls(ctx.angles_from_up_deg)
    assert float(triangle_draft.max()) < 2.99  # every facet reads under the true 3°
    assert _draft(ctx, 3.0, ProcessType.SAND_CASTING) is None
    issue = _draft(_ctx(_cone_stl(2.5)), 3.0, ProcessType.SAND_CASTING)
    assert issue is not None and issue.measured_value == 2.5
