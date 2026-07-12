"""Production routing regressions for ProofShape-generated template geometry."""
from __future__ import annotations

from io import BytesIO

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.features import detect_all
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


def test_generated_l_bracket_never_routes_to_turning():
    drivers = _drivers(
        _generated_mesh(
            {
                "kind": "bracket",
                "width_mm": 80,
                "depth_mm": 50,
                "height_mm": 60,
                "thickness_mm": 6,
            }
        )
    )

    recommendation = recommend_routing(drivers, "aluminum")
    assert drivers.rotational is False
    assert recommendation.archetype != "rotational"
    assert recommendation.process != "cnc_turning"


def test_generated_open_enclosure_routes_as_thin_wall_not_turning():
    drivers = _drivers(
        _generated_mesh(
            {
                "kind": "enclosure",
                "width_mm": 80,
                "depth_mm": 50,
                "height_mm": 60,
                "wall_thickness_mm": 3,
            }
        )
    )

    recommendation = recommend_routing(drivers, "polymer")
    assert drivers.rotational is False
    assert recommendation.archetype == "thin_wall_enclosure"
    assert recommendation.process != "cnc_turning"


def test_real_cylinder_keeps_positive_turning_evidence():
    mesh = trimesh.creation.cylinder(radius=20, height=60, sections=64)
    drivers = _drivers(mesh)

    recommendation = recommend_routing(drivers, "aluminum")
    assert drivers.rotational is True
    assert recommendation.archetype == "rotational"
    assert recommendation.process == "cnc_turning"
