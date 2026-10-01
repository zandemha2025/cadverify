"""Binary STL roundoff must not turn a rotated flat sheet into a different part."""
import pytest
import trimesh

from src.analysis.base_analyzer import analyze_geometry
from src.analysis.context import GeometryContext, flat_sheet_dimensions
from src.analysis.models import ProcessType
from src.analysis.processes.base import get_analyzer
from src.costing.drivers import extract_drivers
from src.costing.makeability import MachineCap, fit_machine, part_req_from_drivers
from src.costing.units import scale_mesh_to_mm
from src.parsers.mesh_cache import MeshParseCache
from src.parsers.stl_parser import parse_stl, parse_stl_from_bytes
import src.analysis.processes  # noqa: F401


@pytest.mark.parametrize("units", ["mm", "inch"])
@pytest.mark.parametrize("thickness", [.4, .499, .5, .8, 5.])
def test_binary_sheet_rounding_preserves_gauge_and_real_limit_failures(units, thickness):
    mesh = trimesh.creation.box(extents=[30., 20., thickness])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.71, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    if units == "inch":
        mesh.apply_scale(1 / 25.4)
    parsed = parse_stl_from_bytes(mesh.export(file_type="stl"))
    parsed = scale_mesh_to_mm(parsed, units)
    dims = flat_sheet_dimensions(parsed)
    assert dims is not None
    assert dims == pytest.approx((thickness, 20., 30.), abs=.0001)
    ctx = GeometryContext.build(parsed, analyze_geometry(parsed))
    issues = get_analyzer(ProcessType.SHEET_METAL).analyze(ctx)
    assert any(i.code == "TOO_THIN_SHEET" for i in issues) == (thickness < .4999)
    assert any(i.code == "SHEET_GAUGE_PRECISION" for i in issues)
    assert not any(i.code == "SHEET_GAUGE_UNVERIFIED" for i in issues)
    assert extract_drivers(analyze_geometry(parsed), parsed).sheet_like


def test_binary_precision_survives_file_cache_copy_and_unit_conversion(tmp_path):
    mesh = trimesh.creation.box(extents=[30, 20, .5]); mesh.apply_translation([100, 200, 300])
    raw = mesh.export(file_type="stl")
    # A binary STL header can legitimately begin with "solid".
    raw = b"solid binary" + raw[12:]
    path = tmp_path / "source.stl"; path.write_bytes(raw)
    parsed = parse_stl(path)
    error = parsed.metadata["coordinate_error"]
    assert 0 < error < .0001
    cache = MeshParseCache(); cache.put(("control", ".stl"), parsed)
    copy = cache.get(("control", ".stl"))
    scaled = scale_mesh_to_mm(copy, "inch")
    assert scaled.metadata["coordinate_error"] == pytest.approx(error * 25.4)
    assert parsed.metadata["coordinate_error"] == copy.metadata["coordinate_error"] == error
    ascii_mesh = parse_stl_from_bytes(mesh.export(file_type="stl_ascii").encode())
    assert not ascii_mesh.metadata.get("coordinate_error")


def test_real_step_in_sheet_profile_is_not_excused_as_export_roundoff():
    from shapely.geometry import Polygon
    profile = Polygon([(0, 0), (30, 0), (30, .5), (20, .5),
                       (20, .51), (10, .51), (10, .5), (0, .5)])
    mesh = trimesh.creation.extrude_polygon(profile, 20)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.71, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    assert flat_sheet_dimensions(parse_stl_from_bytes(mesh.export(file_type="stl"))) is None


@pytest.mark.parametrize("bed,expected", [(30., "unknown"), (30.001, "pass"), (29.999, "fail")])
def test_machine_fit_does_not_claim_certainty_inside_source_roundoff(bed, expected):
    mesh = trimesh.creation.box(extents=[30., 20., .8])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.71, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    mesh = parse_stl_from_bytes(mesh.export(file_type="stl"))
    drivers = extract_drivers(analyze_geometry(mesh), mesh)
    assert drivers.sheet_like
    req = part_req_from_drivers("sheet_metal", drivers, "Aluminum 6061", "standard")
    machine = MachineCap(process="sheet_metal", name="Control", capabilities={"bed_x": bed, "bed_y": 20.001})
    failures = [f for f in fit_machine(req, machine).failures if f.gate == "envelope"]
    actual = "pass" if not failures else "unknown" if all(f.have is None for f in failures) else "fail"
    assert actual == expected


@pytest.mark.parametrize("limit,expected", [(.8, "unknown"), (.801, "pass"), (.799, "fail")])
def test_machine_thickness_limit_uses_source_precision(limit, expected):
    mesh = trimesh.creation.box(extents=[30., 20., .8])
    mesh.apply_translation([100, -200, 300])
    mesh = parse_stl_from_bytes(mesh.export(file_type="stl"))
    req = part_req_from_drivers("sheet_metal", extract_drivers(analyze_geometry(mesh), mesh),
                                "Aluminum 6061", "standard")
    machine = MachineCap(process="sheet_metal", name="Control", capabilities={"bed_x": 40, "bed_y": 30},
                         material_thickness_map={"Aluminum 6061": limit})
    failures = [f for f in fit_machine(req, machine).failures if f.gate == "thickness"]
    actual = "pass" if not failures else "unknown" if all(f.have is None for f in failures) else "fail"
    assert actual == expected


def test_saved_artifact_calibration_loader_preserves_precision(tmp_path):
    from src.costing.cli import _run_engine
    mesh = trimesh.creation.box(extents=[30, 20, .5])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.71, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    path = tmp_path / "artifact.stl"
    path.write_bytes(mesh.export(file_type="stl"))
    result, parsed, _ = _run_engine(str(path))
    assert parsed.metadata["coordinate_error"] > 0
    sheet = next(s for s in result.process_scores if s.process == ProcessType.SHEET_METAL)
    assert any(i.code == "SHEET_GAUGE_PRECISION" for i in sheet.issues)
    assert not any(i.code == "SHEET_GAUGE_UNVERIFIED" for i in sheet.issues)


@pytest.mark.parametrize("diameter", [.499, .5, .501])
def test_sheet_hole_comparison_keeps_real_violation_without_roundoff_failure(diameter):
    from src.analysis.features.base import Feature, FeatureKind
    mesh = trimesh.creation.box(extents=[30, 20, .5])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.1, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    mesh = parse_stl_from_bytes(mesh.export(file_type="stl"))
    ctx = GeometryContext.build(mesh, analyze_geometry(mesh))
    ctx.features = [Feature(kind=FeatureKind.CYLINDER_HOLE, face_indices=[],
                            centroid=(100, -200, 300), radius=diameter / 2)]
    issues = get_analyzer(ProcessType.SHEET_METAL).analyze(ctx)
    assert any(i.code == "SMALL_HOLE_SHEET" for i in issues) == (diameter < .5)
