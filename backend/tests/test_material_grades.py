"""A parts list's named material is the material priced (oo-08).

The engine used to price a listed "Inconel 718" shim in PLA on a filament
printer (the class fell back to the run's default), a "Delrin" pin in PLA, a
"PETG" cup in PLA and "4140" in mild steel: each listed material was reduced to
one of five classes and the class's cheapest grade priced. Now each route is
priced in the named grade where the engine has it for that route; a metal route
without it in the nearest grade of the same metal (the estimate names it); a
plastic route without it isn't priced. Never a metal as a plastic.
"""
from __future__ import annotations

import trimesh

import src.analysis.processes  # noqa: F401  populate registry
from src.analysis.base_analyzer import analyze_geometry, run_universal_checks
from src.analysis.context import GeometryContext
from src.analysis.models import AnalysisResult, ProcessType as PT
from src.analysis.processes import base as pbase
from src.analysis.processes.base import get_analyzer
from src.costing import EstimateOptions, estimate_decision
from src.costing.material_grades import engine_names_for, family_of_grade, grade_of, same_grade
from src.costing.rates import MATERIAL_FAMILY, build_rate_card
from src.costing.routing import select_material, select_sheet_material
from src.matcher.profile_matcher import rank_processes, score_process


def _analyze(mesh):
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    scores = [score_process(get_analyzer(p).analyze(ctx), geometry, p)
              for p in pbase._REGISTRY if get_analyzer(p)]
    result = AnalysisResult(filename="part.stl", file_type="stl", geometry=geometry,
                            segments=ctx.segments, universal_issues=run_universal_checks(mesh),
                            process_scores=scores)
    rank_processes(result)
    return result, mesh, ctx.features


def _materials(report) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for e in report.estimates:
        out.setdefault(e["process"], set()).add(e["material"])
    return out


def test_every_engine_material_has_a_grade_in_its_own_family():
    for name, family in MATERIAL_FAMILY.items():
        key = grade_of(name)
        assert key is not None, name
        assert family_of_grade(key) == family, (name, key)


def test_parts_list_words_name_engine_grades():
    assert engine_names_for("6061-T6 aluminum") == ["6061-T6 Aluminum"]
    assert engine_names_for("4140 steel") == ["AISI 4140"]
    assert set(engine_names_for("304 stainless")) == {"304 Stainless", "304 SS (Sheet)"}
    assert engine_names_for("Delrin") == ["Delrin (POM)"]
    assert engine_names_for("Inconel 718") == ["Inconel 718"]
    assert set(engine_names_for("ABS")) == {"ABS", "ABS (Molded)"}
    assert grade_of("17-4 PH") == "17-4ph"
    assert grade_of("EPDM") is None and grade_of("aluminum") is None
    assert same_grade("304 SS (Sheet)", "304 stainless")
    assert not same_grade("PLA", "PETG")


def test_route_takes_the_named_grade_or_says_it_cannot():
    rates = build_rate_card({})
    # The grade itself where the route runs it.
    assert select_material(PT.CNC_3AXIS, "steel", rates, prefer="4140").name == "AISI 4140"
    assert select_material(PT.FDM, "polymer", rates, prefer="PETG").name == "PETG"
    assert select_material(PT.CNC_3AXIS, "nickel", rates, prefer="Inconel 718").name == "Inconel 718"
    assert select_sheet_material("stainless", rates, prefer="304 stainless").name == "304 SS (Sheet)"
    # A metal route without the grade: the nearest grade of the same metal.
    sub = select_material(PT.CNC_TURNING, "stainless", rates, prefer="17-4 PH")
    assert sub is not None and MATERIAL_FAMILY[sub.name] == "stainless"
    # A plastic route without the plastic named isn't priced for it.
    assert select_material(PT.FDM, "polymer", rates, prefer="Delrin") is None
    assert select_material(PT.CNC_3AXIS, "polymer", rates, prefer="PLA") is None
    assert select_sheet_material("polymer", rates, prefer="Delrin") is None
    # No grade named: the class rule, unchanged.
    assert select_material(PT.FDM, "polymer", rates).name == select_material(PT.FDM, "polymer", rates, prefer=None).name


def test_named_plastic_is_priced_only_where_it_runs():
    result, mesh, feats = _analyze(trimesh.creation.cylinder(radius=5.0, height=40.0, sections=64))
    report = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[1, 1000], material_class="polymer", material_class_is_user=True, material_name="Delrin"))
    mats = _materials(report)
    assert mats, "a Delrin pin is priced somewhere"
    assert all(m == {"Delrin (POM)"} for m in mats.values()), mats
    assert "fdm" not in mats  # a filament printer doesn't print Delrin


def test_named_nickel_alloy_is_priced_as_itself_never_plastic():
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[300.0, 200.0, 0.81]))
    report = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[10], material_class="nickel", material_class_is_user=True, material_name="Inconel 718"))
    mats = _materials(report)
    assert mats
    for process, names in mats.items():
        for n in names:
            assert MATERIAL_FAMILY[n] == "nickel", (process, n)
    assert not ({"fdm", "sla", "sls", "mjf", "injection_molding"} & set(mats))


def test_named_steel_grade_is_priced_not_mild_steel():
    result, mesh, feats = _analyze(trimesh.creation.box(extents=[60.0, 40.0, 30.0]))
    report = estimate_decision(result, mesh, feats, EstimateOptions(
        quantities=[100], material_class="steel", material_class_is_user=True, material_name="4140 steel"))
    mats = _materials(report)
    assert mats.get("cnc_3axis") == {"AISI 4140"}
