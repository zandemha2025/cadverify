import importlib

import pytest
import trimesh
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000")
    import main
    importlib.reload(main)
    return TestClient(main.app)


def test_fit_endpoint_is_dark_without_flag(client, cube_10mm, stl_bytes_of):
    data = stl_bytes_of(cube_10mm)
    response = client.post("/api/v1/validate/fit", files={
        "part_a": ("a.stl", data, "application/octet-stream"),
        "part_b": ("b.stl", data, "application/octet-stream"),
    })
    assert response.status_code == 404


def test_fit_endpoint_returns_real_collision(client, cube_10mm, stl_bytes_of, monkeypatch):
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    a = cube_10mm.copy()
    b = cube_10mm.copy()
    b.apply_translation([9.9, 0, 0])
    response = client.post("/api/v1/validate/fit", files={
        "part_a": ("a.stl", stl_bytes_of(a), "application/octet-stream"),
        "part_b": ("b.stl", stl_bytes_of(b), "application/octet-stream"),
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["collision"]["volume_mm3"] == pytest.approx(10.0, abs=2e-5)
    assert body["collision"]["method"] == "manifold3d_boolean_intersection"
    renderer = body["collision"]["region"]["render_geometry"]
    assert renderer["available"] is True
    assert renderer["exact_intersection_shell"] is True
    assert renderer["media_type"] == "model/gltf-binary"
    assert body["clearance"]["method"] == "bidirectional_sampled_point_to_triangle"
    assert body["timing_ms"]["pair_total"] >= body["timing_ms"]["collision_boolean"]


@pytest.mark.parametrize("mode,unmatched,nudge,accepted,shift,gap,volume", [
    ("shared_frame", False, 0, True, 0, 20, 0),
    ("shared_frame", False, 5, True, 5, 25, 0),
    ("auto", False, 0, True, -30, 0, 1000),
    ("auto", False, 20, True, -10, 10, 0),
    ("auto", True, 0, False, 0, 15, 0),
    ("auto", True, -10, False, -10, 5, 0),
])
def test_fit_seating_provenance_matches_measured_placement(
    client, monkeypatch, stl_bytes_of, mode, unmatched, nudge, accepted, shift, gap, volume,
):
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    a = trimesh.creation.box(extents=[10, 10, 10])
    b = trimesh.creation.box(extents=[20, 5, 3] if unmatched else [10, 10, 10])
    b.apply_translation([30, 0, 0])
    response = client.post(f"/api/v1/validate/fit?seating={mode}&nudge_x_mm={nudge}", files={
        "part_a": ("part.stl", stl_bytes_of(a)),
        "part_b": ("assembly.stl", stl_bytes_of(b)),
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["coordinate_frame"] == "part_a_source_frame"
    assert result["seating"]["accepted"] is accepted
    assert result["seating"]["transform"][0][3] == pytest.approx(shift)
    assert result["clearance"]["closest_sampled_gap_mm"] == pytest.approx(gap, abs=1e-6)
    assert result["collision"]["volume_mm3"] == pytest.approx(volume, abs=1e-6)
    limits = " ".join(result["limits"])
    if mode == "shared_frame":
        assert "same assembly coordinate frame" in limits
    elif accepted:
        assert "bounded surface alignment" in limits
        assert "does not verify assembly constraints" in limits
        assert "same assembly coordinate frame" not in limits
    else:
        assert "original file coordinates were retained" in limits
    assert ("Manual XYZ offset" in limits) is bool(nudge)


@pytest.mark.parametrize("kind", ["stl", "obj", "3mf"])
def test_fit_and_preview_share_per_file_units_and_mm_nudge(client, monkeypatch, kind):
    import io
    import numpy as np

    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    unit_cube = trimesh.creation.box()
    # 3MF has embedded millimeters, so a conflicting declaration must be ignored.
    if kind == "3mf":
        unit_cube.apply_scale(25.4)
    data = unit_cube.export(file_type=kind)
    if isinstance(data, str):
        data = data.encode()
    partner = trimesh.creation.box(extents=[25.4] * 3).export(file_type="obj").encode()
    files = {"part_a": (f"a.{kind}", data), "part_b": ("b.obj", partner)}
    query = "part_a_units=inch&part_b_units=mm"
    response = client.post(f"/api/v1/validate/fit?{query}", files=files)
    assert response.status_code == 200, response.text
    assert response.json()["collision"]["volume_mm3"] == pytest.approx(25.4 ** 3, abs=1e-5)
    gap = client.post(f"/api/v1/validate/fit?{query}&nudge_x_mm=35.4", files=files)
    assert gap.status_code == 200, gap.text
    assert gap.json()["clearance"]["closest_sampled_gap_mm"] == pytest.approx(10, abs=1e-6)
    preview = client.post("/api/v1/validate/preview-mesh?units=inch", files={"file": files["part_a"]})
    assert preview.status_code == 200, preview.text
    rendered = trimesh.load(io.BytesIO(preview.content), file_type="glb").to_mesh()
    np.testing.assert_allclose(rendered.extents, [25.4] * 3, atol=1e-5)

    # Repeating with mm proves one request did not mutate a cached source mesh.
    unchanged = client.post("/api/v1/validate/fit", files=files)
    expected = 25.4 ** 3 if kind == "3mf" else 1
    assert unchanged.json()["collision"]["volume_mm3"] == pytest.approx(expected, abs=1e-5)
    assert client.post("/api/v1/validate/fit?part_b_units=unknown", files=files).status_code == 422


@pytest.mark.parametrize("axis", ["x", "y", "z"])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e309"])
def test_fit_rejects_nonfinite_offsets_without_server_error(client, monkeypatch, cube_10mm, stl_bytes_of, axis, value):
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    data = stl_bytes_of(cube_10mm)
    response = TestClient(client.app, raise_server_exceptions=False).post(
        f"/api/v1/validate/fit?nudge_{axis}_mm={value}",
        files={"part_a": ("a.stl", data), "part_b": ("b.stl", data)},
    )
    assert response.status_code == 422, response.text
    assert "finite" in response.text.lower()


def test_fit_budget_error_does_not_instruct_repairing_valid_shells(client, stl_bytes_of, monkeypatch):
    monkeypatch.setenv("CONTEXT_FIT_ENABLED", "1")
    monkeypatch.setenv("FIT_MAX_PAIR_FACES", "1000")
    data = stl_bytes_of(trimesh.creation.icosphere(subdivisions=3))
    response = client.post("/api/v1/validate/fit", files={
        "part_a": ("a.stl", data, "application/octet-stream"),
        "part_b": ("b.stl", data, "application/octet-stream"),
    })
    assert response.status_code == 422
    detail = response.json()
    assert "Reduce tessellation" in detail["message"]
    assert "repairable" not in detail
    assert "next_action" not in detail

    monkeypatch.setenv("MAX_TRIANGLES", "1")
    obj = trimesh.creation.box().export(file_type="obj").encode()
    capped = client.post("/api/v1/validate/fit", files={
        "part_a": ("a.obj", obj, "application/octet-stream"),
        "part_b": ("b.obj", obj, "application/octet-stream"),
    })
    assert capped.status_code == 400
    assert "MAX_TRIANGLES" in capped.json()["message"]
