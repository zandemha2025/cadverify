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
from src.analysis.processes.checks import _shown_draft, check_draft_angles
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
    for process, limit in ((ProcessType.INJECTION_MOLDING, 1.0), (ProcessType.DIE_CASTING, 1.0),
                           (ProcessType.SAND_CASTING, 3.0), (ProcessType.FORGING, 5.0)):
        issue = next(i for i in scores[process].issues if i.code == "INSUFFICIENT_DRAFT")
        assert issue.measured_value == 0.0 and issue.required_value == limit
        assert issue.message.endswith("Smallest draft: 0.0° (outer walls 0.0°, bore 0.0°). The tool opens along the file's +Z.")
        seen[process] = issue
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
