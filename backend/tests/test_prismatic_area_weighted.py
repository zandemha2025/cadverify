"""check_prismatic must weight by surface AREA, not face count (F12).

Face-count weighting made the NOT_PRISMATIC verdict flip with mesh
density on identical geometry: a 100x100x5 plate with a 2mm 45-deg
chamfer along one top edge is 98.71% prismatic by area at any mesh
density, but 87.5% prismatic by face count when the chamfer is one
segment and 80.1% when it is 200 segments. Area weighting makes the
verdict a function of geometry, not tessellation.
"""
from pathlib import Path

import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext
from src.analysis.models import ProcessType
from src.analysis.processes.checks import check_prismatic

CORPUS = Path(__file__).parent / "corpus-v3"


def _verdict(mesh):
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    return check_prismatic(ctx, ProcessType.WIRE_EDM)


def test_plain_plate_is_prismatic():
    assert _verdict(trimesh.creation.box(extents=(100, 100, 5))) == []


def test_chamfered_plate_passes_area_weighted():
    # 98.71% prismatic by area; the 2mm chamfer is 1.3% of the surface.
    assert _verdict(trimesh.load_mesh(CORPUS / "trap-chamfered-plate-prismatic.stl")) == []


def test_verdict_invariant_to_tessellation_density():
    # Same logical part, chamfer tessellated at 200 vs 1 segments.
    fine = _verdict(trimesh.load_mesh(CORPUS / "trap-chamfered-plate-prismatic.stl"))
    coarse = _verdict(trimesh.load_mesh(CORPUS / "trap-chamfered-plate-prismatic-coarse.stl"))
    assert fine == coarse == []


def test_genuinely_non_prismatic_parts_still_trip():
    # 45-deg pyramidal top: sloped faces dominate the area.
    issues = _verdict(trimesh.load_mesh(CORPUS / "trap-pyramid-top-nonprismatic.stl"))
    assert [i.code for i in issues] == ["NOT_PRISMATIC"]
    assert issues[0].severity.value == "error"


def test_filleted_plate_still_trips_area_weighted():
    # r4 fillets on a 60x60x5 plate are 27.3% of the surface area:
    # genuinely non-prismatic, correctly rejected by wire EDM.
    issues = _verdict(trimesh.load_mesh(CORPUS / "trap-filleted-plate-prismatic.stl"))
    assert [i.code for i in issues] == ["NOT_PRISMATIC"]


def test_sphere_trips():
    issues = _verdict(trimesh.creation.icosphere(subdivisions=3, radius=10))
    assert [i.code for i in issues] == ["NOT_PRISMATIC"]
