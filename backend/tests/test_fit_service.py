from __future__ import annotations

import numpy as np
import pytest
import trimesh

from src.services.fit_service import FitGeometryError, analyze_fit


def test_exact_boolean_collision_and_payload_region():
    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[10, 10, 10])
    b.apply_translation([9.9, 0, 0])
    out = analyze_fit(a, b)
    assert out["collision"]["intersects"] is True
    assert out["collision"]["volume_mm3"] == pytest.approx(10.0, abs=1e-5)
    assert out["collision"]["region"]["region_center"][0] == pytest.approx(4.95, abs=1e-5)
    assert out["collision"]["region"]["part_a_faces"]
    assert out["collision"]["region"]["part_b_faces"]
    assert out["clearance"]["closest_sampled_gap_mm"] == 0.0


def test_sampled_clearance_is_exact_for_parallel_cube_faces(monkeypatch):
    monkeypatch.setenv("FIT_CLEARANCE_SAMPLES", "1000")
    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[10, 10, 10])
    b.apply_translation([10.2, 0, 0])
    out = analyze_fit(a, b)
    assert out["collision"]["intersects"] is False
    assert out["clearance"]["closest_sampled_gap_mm"] == pytest.approx(0.2, abs=1e-6)
    assert out["clearance"]["tight_zone"]["region_center"] is not None


def test_non_watertight_refuses_collision_instead_of_estimating():
    mesh = trimesh.creation.box()
    mesh.update_faces(np.arange(len(mesh.faces) - 1))
    with pytest.raises(FitGeometryError, match="not watertight"):
        analyze_fit(mesh, trimesh.creation.box())


def test_obj_pair_format_parser_keeps_shared_coordinates():
    from src.services.fit_service import parse_supplementary_mesh
    source = trimesh.creation.box(extents=[2, 3, 4])
    parsed = parse_supplementary_mesh(source.export(file_type="obj").encode(), "part.obj")
    assert parsed.extents.tolist() == pytest.approx([2, 3, 4])


def test_proximity_target_keeps_source_face_locator_mapping():
    from src.services.fit_service import _proximity_target
    mesh = trimesh.creation.icosphere(subdivisions=3)
    proxy, source_faces = _proximity_target(mesh, budget=100)
    assert len(proxy.faces) == 100
    assert len(source_faces) == 100
    assert int(source_faces[-1]) == len(mesh.faces) - 1


def test_pair_face_admission_refuses_before_geometry_work(monkeypatch):
    monkeypatch.setenv("FIT_MAX_PAIR_FACES", "1000")
    a = trimesh.creation.icosphere(subdivisions=3)
    b = trimesh.creation.icosphere(subdivisions=3)
    with pytest.raises(FitGeometryError, match="2560 triangle faces, above the 1000 fit-check limit"):
        analyze_fit(a, b)


def test_near_zero_volume_is_refused():
    flat = trimesh.Trimesh(vertices=[[0,0,0],[1,0,0],[0,1,0]], faces=[[0,1,2]], process=False)
    with pytest.raises(FitGeometryError, match="near-zero enclosed volume|not watertight"):
        analyze_fit(flat, trimesh.creation.box())


def test_closest_memory_error_maps_to_fit_refusal(monkeypatch):
    from src.services import fit_service
    a = trimesh.creation.box()
    b = trimesh.creation.box(); b.apply_translation([2,0,0])
    def boom(*_args, **_kwargs):
        raise MemoryError("bounded probe")
    monkeypatch.setattr(trimesh.proximity, "closest_point", boom)
    with pytest.raises(FitGeometryError, match="bounded memory budget"):
        fit_service.analyze_fit(a, b)


def test_large_target_discloses_proximity_proxy(monkeypatch):
    monkeypatch.setenv("FIT_MAX_PAIR_FACES", "100000")
    large = trimesh.creation.icosphere(subdivisions=6)
    small = trimesh.creation.box(); small.apply_translation([3,0,0])
    # Avoid expensive geometry; this test owns response provenance only.
    monkeypatch.setattr("src.services.fit_service._collision", lambda *_: (0.0, None))
    monkeypatch.setattr("src.services.fit_service._closest", lambda *_: (np.zeros((1,3)), np.zeros((1,3)), np.array([1.0]), np.array([0]), np.array([0])))
    out = analyze_fit(large, small)
    assert any("true tightest spot may be smaller" in line and "25,000-face proxy" in line for line in out["limits"])
