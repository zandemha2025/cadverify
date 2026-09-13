import importlib

import pytest
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
