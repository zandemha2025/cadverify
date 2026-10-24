"""Engine text a buyer reads, in plain words, and the routes it implies (round 6).

W12: a titanium plate was priced as "5052 Aluminum (Sheet)". M22: a solid
plastic block read "no dominant ... prismatic signature". C9: an open cup with
square walls was "a cover/enclosure with draft". M19: the material assumption
said "these are polymer automotive parts". C1/C4/C6/C2: notes named API flags
(strict_dfm=True), engine ids (cnc_3axis, bulk_solid), "make-as-is pick",
ALL-CAPS provenance tags and MEASURED-geometry × USER-declared.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import AnalysisResult, ProcessType
from src.analysis.processes import get_analyzer
from src.costing import EstimateOptions, estimate_decision
from src.matcher.profile_matcher import score_process

ENGINE_ID = re.compile(r"\b(?:" + "|".join(p.value for p in ProcessType if "_" in p.value)
                       + r"|bulk_solid|prismatic_block|thin_wall_enclosure|sheet_panel|long_prismatic_bar)\b")


def _report(mesh, material_class="polymer", **kw):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_all(ctx.mesh)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p) for p in ProcessType]
    result = AnalysisResult(filename="part.stl", file_type="stl", geometry=geometry, segments=[],
                            universal_issues=[], process_scores=scores, analysis_time_ms=0.0)
    options = EstimateOptions(quantities=[1, 100, 10000], material_class=material_class,
                              material_class_is_user=material_class != "polymer", **kw)
    return estimate_decision(result, mesh, ctx.features, options)


def _cup():
    outer = trimesh.creation.box(extents=[40, 40, 30])
    inner = trimesh.creation.box(extents=[39, 39, 30])
    inner.apply_translation([0, 0, 0.5 + 0.0])
    return trimesh.boolean.difference([outer, inner], engine="manifold")


@pytest.fixture(scope="module")
def plate_reports():
    plate = trimesh.creation.box(extents=[100, 60, 3])
    return {cls: _report(plate, cls) for cls in ("titanium", "stainless", "polymer")}


def test_titanium_plate_is_not_priced_as_aluminum_sheet(plate_reports):
    ti = plate_reports["titanium"]
    assert not [e for e in ti.estimates if e["process"] == "sheet_metal"]
    (row,) = [f for f in ti.engine_feasibility if f["process"] == "sheet_metal"]
    assert row["cost_exclusion_reason"] == ("No titanium sheet stock is on file, so this part isn't "
                                            "priced as sheet metal in titanium.")
    assert row["cost_exclusion_reason"] in ti.notes


def test_stainless_and_default_plates_still_get_a_sheet_price(plate_reports):
    ss = [e for e in plate_reports["stainless"].estimates if e["process"] == "sheet_metal"]
    assert ss and all("Aluminum" not in e["material"] for e in ss)
    # no material given: sheet metal is never plastic, so the estimate names its metal
    assert [e for e in plate_reports["polymer"].estimates if e["process"] == "sheet_metal"]


def test_a_solid_plastic_block_is_a_prismatic_block():
    report = _report(trimesh.creation.box(extents=[30, 30, 30]))
    assert report.routing["archetype"] == "prismatic_block"
    assert "prismatic signature" not in report.routing["reasoning"]
    assert "plastic stock" in report.routing["reasoning"]


def test_a_square_walled_cup_is_not_said_to_have_draft():
    report = _report(_cup())
    assert report.routing["archetype"] == "thin_wall_enclosure"
    assert "draft" not in report.routing["reasoning"]


def test_material_assumption_says_what_is_assumed():
    report = _report(trimesh.creation.box(extents=[30, 30, 30]))
    (src,) = [a.source for a in report.assumptions if a.name == "material_class"]
    assert src == ("No material was given, so prices assume plastic. Set the material to price it "
                   "in metal or another plastic.")
    declared = _report(trimesh.creation.box(extents=[30, 30, 30]), "aluminum")
    (src,) = [a.source for a in declared.assumptions if a.name == "material_class"]
    assert src == "priced in aluminum, as you set it"


@pytest.mark.parametrize("material_class", ["polymer", "aluminum"])
def test_notes_assumptions_and_decision_read_as_sentences(material_class):
    for mesh in (trimesh.creation.box(extents=[30, 30, 30]), _cup()):
        report = _report(mesh, material_class)
        texts = [*report.notes, report.decision.note if report.decision else "",
                 report.routing["reasoning"] if report.routing else "",
                 *(a.source for a in report.assumptions)]
        joined = "\n".join(texts)
        assert "strict_dfm" not in joined and "make-as-is" not in joined
        assert "(DEFAULT" not in joined and "automotive" not in joined
        assert "not shop-validated" not in joined
        assert not ENGINE_ID.search(joined), ENGINE_ID.search(joined)
        assert not re.search(r"reads as a '", joined)


def test_machine_fit_note_drops_provenance_tags():
    from src.costing.estimate import _serialize_verification

    verdict = SimpleNamespace(per_route={}, verdict="unknown", best_machine=None, resource=None, gap=[])
    note = _serialize_verification(verdict, SimpleNamespace(inventory=(), service_environment=None))["note"]
    assert "MEASURED" not in note and "USER" not in note and "not_makeable" not in note
    assert note.startswith("Machine fit compares the part's measured size and features")
