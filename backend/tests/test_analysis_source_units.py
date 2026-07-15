"""Regression coverage for one source-unit interpretation across DFM + cache."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


CUBED = 25.4 ** 3


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)
    return TestClient(main.app)


def _post(client, data, units=None):
    suffix = f"?units={units}" if units else ""
    return client.post(
        f"/api/v1/validate{suffix}",
        files={"file": ("unitless-cube.stl", data, "application/octet-stream")},
    )


def test_validate_rejects_unknown_source_units_before_parsing(client):
    response = _post(client, b"not-cad", "furlong")
    assert response.status_code == 400
    assert "units" in response.json()["message"].lower()


def test_validate_inch_scales_geometry_once_and_cannot_hit_mm_cache(
    client, cube_10mm, stl_bytes_of
):
    data = stl_bytes_of(cube_10mm)

    # Same account + same raw bytes + same process set. If source units are not
    # part of the dedup key, the second request incorrectly returns the mm row.
    mm = _post(client, data, "mm")
    inch = _post(client, data, "inch")
    assert mm.status_code == 200 and inch.status_code == 200, (mm.text, inch.text)

    mm_body, inch_body = mm.json(), inch.json()
    assert inch_body["geometry"]["volume_mm3"] / mm_body["geometry"]["volume_mm3"] == pytest.approx(CUBED, rel=1e-6)
    for mm_dim, inch_dim in zip(
        mm_body["geometry"]["bounding_box_mm"],
        inch_body["geometry"]["bounding_box_mm"],
    ):
        assert inch_dim / mm_dim == pytest.approx(25.4, rel=1e-9)
    assert "source_units" not in mm_body
    assert inch_body["source_units"] == {
        "declared": "inch",
        "scale_to_mm": 25.4,
        "provenance": "USER",
        "note": "Source coordinates scaled once before geometry and DFM analysis.",
    }


def test_validate_default_and_explicit_mm_share_historical_geometry(
    client, cube_10mm, stl_bytes_of
):
    data = stl_bytes_of(cube_10mm)
    default = _post(client, data)
    explicit = _post(client, data, "mm")
    assert default.status_code == 200 and explicit.status_code == 200
    assert default.json()["geometry"] == explicit.json()["geometry"]
    assert "source_units" not in default.json()
    assert "source_units" not in explicit.json()
