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


@pytest.mark.parametrize("units", ["mm", "inch"])
@pytest.mark.parametrize("thickness", [.499, .5, .501])
def test_binary_wall_and_feature_limits_keep_real_defects(units, thickness):
    from src.analysis.additive_analyzer import check_small_features as legacy_check
    from src.analysis.processes.checks import check_small_features, check_wall_thickness, check_wall_uniformity
    mesh = trimesh.creation.box(extents=[30., 20., thickness])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.71, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    if units == "inch":
        mesh.apply_scale(1 / 25.4)
    parsed = scale_mesh_to_mm(parse_stl_from_bytes(mesh.export(file_type="stl")), units)
    ctx = GeometryContext.build(parsed, analyze_geometry(parsed))
    wall = check_wall_thickness(ctx, .5, ProcessType.MJF)
    molding = check_wall_uniformity(ctx, .5, 6., 2., ProcessType.INJECTION_MOLDING)
    feature = check_small_features(ctx, .5, ProcessType.BINDER_JET)
    assert any(i.code == "THIN_WALL" for i in wall) is (thickness < .5)
    assert any(i.code == "THIN_WALL_MOLDING" for i in molding) is (thickness < .5)
    assert any(i.code == "SMALL_FEATURES" for i in feature) is (thickness < .5)
    assert any(i.code == "SMALL_FEATURES" for i in legacy_check(parsed, ProcessType.BINDER_JET)) is (thickness < .5)
    if thickness == .5:
        assert any("PRECISION" in i.code for i in wall)
        assert any("PRECISION" in i.code for i in molding)
        assert any("PRECISION" in i.code for i in feature)


@pytest.mark.parametrize("thickness", [5.999, 6., 6.001])
def test_binary_molding_maximum_keeps_real_thick_sections(thickness):
    from src.analysis.processes.checks import check_wall_uniformity
    mesh = trimesh.creation.box(extents=[30., 20., thickness])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.71, [1, 2, 3]))
    mesh.apply_translation([100, -200, 300])
    parsed = parse_stl_from_bytes(mesh.export(file_type="stl"))
    ctx = GeometryContext.build(parsed, analyze_geometry(parsed))
    issues = check_wall_uniformity(ctx, .5, 6., 2., ProcessType.INJECTION_MOLDING)
    assert any(i.code == "THICK_WALL" for i in issues) is (thickness > 6.)
    if thickness == 6.:
        assert any("PRECISION" in i.code for i in issues)


def test_binary_bounds_cover_analytic_boxes_without_erasing_clear_defects():
    import numpy as np
    from src.analysis.processes.checks import check_wall_thickness
    rng = np.random.default_rng(163)
    for _ in range(20):
        thickness = rng.uniform(.2, .45)
        mesh = trimesh.creation.box(extents=[30., 20., thickness])
        mesh.apply_transform(trimesh.transformations.rotation_matrix(rng.uniform(-3, 3), rng.normal(size=3)))
        mesh.apply_translation(rng.uniform(-300, 300, size=3))
        parsed = parse_stl_from_bytes(mesh.export(file_type="stl"))
        ctx = GeometryContext.build(parsed, analyze_geometry(parsed))
        assert thickness <= ctx.wall_thickness_upper.min() < thickness + .001
        assert any(i.code == "THIN_WALL" for i in check_wall_thickness(ctx, .5, ProcessType.MJF))


def test_interpolated_faces_do_not_inherit_a_thin_wall_proof():
    import numpy as np
    from src.analysis.context import _compute_wall_thickness_sampled
    mesh = trimesh.creation.box(extents=[30., 20., .4])
    for _ in range(5):
        mesh = mesh.subdivide()
    upper = np.full(len(mesh.faces), np.inf)
    values = _compute_wall_thickness_sampled(mesh, mesh.face_normals, mesh.triangles_center,
                                             .001, len(mesh.faces), upper)
    sampled = np.arange(0, len(mesh.faces), len(mesh.faces) // 5000)
    unsampled = np.ones(len(mesh.faces), dtype=bool); unsampled[sampled] = False
    assert np.isfinite(values[unsampled]).all()
    assert np.isinf(upper[unsampled]).all()
    assert np.isfinite(upper[sampled]).any()


def test_decimation_and_closed_rims_disclose_unknown_precision(monkeypatch):
    import numpy as np
    import src.analysis.context as context
    from src.analysis.processes.checks import check_small_features, check_wall_thickness, check_wall_uniformity
    rim = parse_stl_from_bytes(trimesh.creation.annulus(r_min=.2, r_max=2, height=4).export(file_type="stl"))
    ctx = GeometryContext.build(rim, analyze_geometry(rim))
    issues = check_small_features(ctx, .5, ProcessType.BINDER_JET)
    assert any(i.code == "FEATURE_SIZE_PRECISION" for i in issues)
    assert not any(i.code == "SMALL_FEATURES" for i in issues)
    part = parse_stl_from_bytes(trimesh.creation.box(extents=[.4, 20, 30]).export(file_type="stl"))
    monkeypatch.setattr(context, "_maybe_decimate", lambda m: (m, {"succeeded": True}))
    ctx = GeometryContext.build(part, analyze_geometry(part))
    assert np.isinf(ctx.wall_thickness_upper).all()
    assert np.isinf(ctx.edge_length_precision).all()
    assert not any(i.code == "THIN_WALL" for i in check_wall_thickness(ctx, .5, ProcessType.MJF))
    assert not any(i.code in {"THIN_WALL_MOLDING", "THICK_WALL", "NON_UNIFORM_WALLS"}
                   for i in check_wall_uniformity(ctx, .5, .1, .2, ProcessType.INJECTION_MOLDING))


def test_unstable_sharp_edge_threshold_is_unknown():
    import numpy as np
    from src.analysis.context import manufacturing_edge_measurements
    mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [10, 0, 0], [0, 10, 0],
                                    [0, -10 * np.cos(np.pi / 6), 10 * np.sin(np.pi / 6)]],
                           faces=[[0, 1, 2], [1, 0, 3]], process=False)
    parsed = parse_stl_from_bytes(mesh.export(file_type="stl"))
    _, precision, stable = manufacturing_edge_measurements(parsed)
    assert not stable
    assert not np.isfinite(precision).any()


def test_findings_report_the_measurement_that_proves_the_defect():
    import numpy as np
    from src.analysis.processes.checks import check_wall_uniformity
    part = trimesh.creation.box(extents=[1., 1., 1.])
    ctx = GeometryContext.build(part, analyze_geometry(part))
    ctx.wall_thickness[:] = .4; ctx.wall_thickness_upper[:] = .41
    ctx.wall_thickness[0] = .01; ctx.wall_thickness_upper[0] = np.inf
    ctx.maximum_inscribed_diameter = 1.
    issues = check_wall_uniformity(ctx, .5, 6, 2, ProcessType.INJECTION_MOLDING)
    assert next(i for i in issues if i.code == "THIN_WALL_MOLDING").measured_value == .4
    assert next(i for i in issues if i.code == "NON_UNIFORM_WALLS").measured_value == 2.5


def test_persistent_hit_keeps_its_measurement_when_nearer_hit_is_ambiguous(monkeypatch):
    import numpy as np
    from src.analysis.context import _cast_inward_rays_batched
    # One inward ray, an edge hit on a nearer triangle, and a stable interior
    # hit on a farther triangle. The bound must retain the farther distance.
    triangles = np.array([[[-2, -2, 0], [2, -2, 0], [0, 2, 0]],
                          [[0, 0, -.01], [2, 0, -.01], [0, 2, -.01]],
                          [[-2, -2, -.4], [2, -2, -.4], [0, 2, -.4]]])
    mesh = trimesh.Trimesh(vertices=triangles.reshape((-1, 3)), faces=np.arange(9).reshape((-1, 3)), process=False)
    mesh.metadata['coordinate_error'] = 1e-6
    monkeypatch.setattr(mesh.ray, 'intersects_location', lambda **kw:
                        (np.array([[0, 0, -.01], [0, 0, -.4]]), np.array([0, 0]), np.array([1, 2])))
    upper = np.array([np.inf])
    value = _cast_inward_rays_batched(mesh, np.array([[0, 0, .001]]), np.array([[0, 0, -1.]]),
                                      .001, np.array([0]), source_points=np.array([[0, 0, 0.]]), upper_bounds=upper)
    assert value[0] == .4
    assert .4 < upper[0] < .401
