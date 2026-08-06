"""Real-file STEP smoke test (Cycle 5 §A.8.3), always on and zero egress.

Runs the checked-in NIST AP203 periodic-surface fixture through the full cost
path. The fixture is a U.S. government test artifact already used by the meshing
regression suite, so CI no longer depends on mutable network content.

Fixture: ``tests/assets/nist_periodic_ctc05.stp`` (NIST CTC 05).
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_FIXTURE = Path(__file__).parent / "assets" / "nist_periodic_ctc05.stp"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app)


def test_real_step_costs_end_to_end(client):
    pytest.importorskip("gmsh", reason="gmsh not installed; STEP path unavailable")
    data = _FIXTURE.read_bytes()
    assert data[:13] == b"ISO-10303-21;", "fixture is not a STEP file"

    r = client.post(
        "/api/v1/validate/cost",
        files={"file": (_FIXTURE.name, data, "application/octet-stream")},
        data={"qty": "50,5000", "material_class": "aluminum", "region": "US"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert body["geometry"]["watertight"] is True
    assert body["geometry"]["volume_cm3"] > 1  # real part, not a toy
    assert body["decision"] and body["decision"]["make_now_process"]
    for e in body["estimates"]:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02
        for d in e["drivers"]:
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")
