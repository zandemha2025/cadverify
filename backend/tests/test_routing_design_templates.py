"""Production routing regressions for ProofShape-generated template geometry."""
from __future__ import annotations

from io import BytesIO
import warnings

import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.features import detect_all
from src.analysis.models import ProcessType
from src.analysis.processes import get_analyzer
from src.analysis.processes.checks import check_rotational_symmetry
from src.costing.drivers import extract_drivers
from src.costing.routing import recommend_routing
from src.designs.generator import generate_design_artifacts


def _generated_mesh(plan: dict) -> trimesh.Trimesh:
    artifacts = generate_design_artifacts(plan)
    mesh = trimesh.load_mesh(BytesIO(artifacts.stl_bytes), file_type="stl", process=True)
    assert isinstance(mesh, trimesh.Trimesh)
    return mesh


def _drivers(mesh: trimesh.Trimesh):
    geometry = analyze_geometry(mesh)
    return extract_drivers(geometry, mesh, detect_all(mesh))


def _turning_issue_codes(mesh: trimesh.Trimesh) -> set[str]:
    geometry = analyze_geometry(mesh)
    context = GeometryContext.build(mesh, geometry)
    context.features = detect_all(context.mesh)
    return {
        issue.code
        for issue in get_analyzer(ProcessType.CNC_TURNING).analyze(context)
    }


def test_generated_l_bracket_never_routes_to_turning():
    mesh = _generated_mesh(
            {
                "kind": "bracket",
                "width_mm": 80,
                "depth_mm": 50,
                "height_mm": 60,
                "thickness_mm": 6,
            }
        )
    drivers = _drivers(mesh)

    recommendation = recommend_routing(drivers, "aluminum")
    assert drivers.rotational is False
    assert recommendation.archetype != "rotational"
    assert recommendation.process != "cnc_turning"
    assert "NOT_ROTATIONALLY_SYMMETRIC" in _turning_issue_codes(mesh)


def test_generated_open_enclosure_routes_as_thin_wall_not_turning():
    mesh = _generated_mesh(
            {
                "kind": "enclosure",
                "width_mm": 80,
                "depth_mm": 50,
                "height_mm": 60,
                "wall_thickness_mm": 3,
            }
        )
    drivers = _drivers(mesh)

    recommendation = recommend_routing(drivers, "polymer")
    assert drivers.rotational is False
    assert recommendation.archetype == "thin_wall_enclosure"
    assert recommendation.process != "cnc_turning"
    assert "NOT_ROTATIONALLY_SYMMETRIC" in _turning_issue_codes(mesh)


def test_real_cylinder_keeps_positive_turning_evidence():
    mesh = trimesh.creation.cylinder(radius=20, height=60, sections=64)
    drivers = _drivers(mesh)

    recommendation = recommend_routing(drivers, "aluminum")
    assert drivers.rotational is True
    assert recommendation.archetype == "rotational"
    assert recommendation.process == "cnc_turning"
    assert "NOT_ROTATIONALLY_SYMMETRIC" not in _turning_issue_codes(mesh)


def test_open_mesh_skips_mass_properties_without_runtime_warning():
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    mesh.update_faces(list(range(10)))  # remove one side from the 12-face box
    mesh.remove_unreferenced_vertices()
    geometry = analyze_geometry(mesh)
    context = GeometryContext.build(mesh, geometry)

    assert geometry.is_watertight is False
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        issues = check_rotational_symmetry(context, ProcessType.CNC_TURNING)
    assert issues == []


@pytest.mark.parametrize("material", ["aluminum", "steel", "stainless"])
def test_metal_routing_never_promotes_polymer_processes(material):
    from dataclasses import replace
    from src.costing.rates import build_rate_card
    from src.costing.routing import select_material

    drivers = replace(_drivers(trimesh.creation.box(extents=[40, 30, 25])),
                      volume_cm3=6, nominal_wall_mm=9, rotational=False)
    # SLS passes geometry-only DFM, but cannot manufacture this declared metal.
    recommendation = recommend_routing(
        drivers, material, dfm_failed={ProcessType.CNC_3AXIS},
        dfm_clean=["sls", "cnc_5axis", "waam"],
    )
    assert recommendation is not None
    assert recommendation.process == "cnc_5axis"
    for name in [recommendation.process, *recommendation.alternatives]:
        assert select_material(ProcessType(name), material, build_rate_card()) is not None
    assert "make-vs-buy crossover" not in recommendation.reasoning


def test_metal_enclosure_and_unavailable_routes():
    mesh = _generated_mesh({"kind": "enclosure", "width_mm": 80,
                            "depth_mm": 50, "height_mm": 60, "wall_thickness_mm": 3})
    drivers = _drivers(mesh)
    recommendation = recommend_routing(drivers, "aluminum")
    assert recommendation is not None
    assert recommendation.process == "dmls"
    assert "mjf" not in recommendation.alternatives
    assert "sheet_metal" not in recommendation.alternatives
    assert recommend_routing(drivers, "aluminum", dfm_failed=set(ProcessType)) is None


def test_report_routing_uses_actual_eligible_routes():
    from src.analysis.models import AnalysisResult, ProcessScore
    from src.costing import EstimateOptions, estimate_decision

    mesh = trimesh.creation.box(extents=[40, 30, 25])
    result = AnalysisResult(filename="routing.stl", file_type="stl",
                            geometry=analyze_geometry(mesh), process_scores=[
        ProcessScore(ProcessType.CNC_3AXIS, 0, "fail"),
        ProcessScore(ProcessType.SLS, 1, "pass"),
        ProcessScore(ProcessType.WAAM, 1, "pass"),
    ])
    options = EstimateOptions(quantities=[1], material_class="aluminum")
    report = estimate_decision(result, mesh, detect_all(mesh), options)
    assert report.routing["recommended_process"] == "waam"
    assert "cnc_5axis" not in report.routing["alternatives"]  # not evaluated
    assert "modeled for 3D printing" not in " ".join(report.notes)
    options.service_environment = {"sour_service": True}
    assert estimate_decision(result, mesh, detect_all(mesh), options).routing is None
    options.service_environment = None
    result.process_scores[-1].verdict = "fail"
    report = estimate_decision(result, mesh, detect_all(mesh), options)
    assert report.routing is None
    assert any("No eligible DFM-ready geometric route" in note for note in report.notes)
