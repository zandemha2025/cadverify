"""Real-file STEP smoke test (Cycle 5 §A.8.3) — gated behind STEP_NETWORK_TESTS=1.

Fetches a genuine, OSI-licensed STEP part over the network and runs it through
the full cost path. Gated so CI without egress stays green. The serve/cost path
itself opens zero sockets; the only network call here is the test fetching the
fixture (not the endpoint).

Fixture: eight_cyl.stp from tpaviot/pythonocc-core (repo license: LGPL-3.0,
confirmed via the GitHub license API). Single solid, ~1175 cm^3, 499x196x454 mm.
"""
from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient

_GATE = os.getenv("STEP_NETWORK_TESTS") != "1"
_URL = (
    "https://raw.githubusercontent.com/tpaviot/pythonocc-core/"
    "master/test/test_io/eight_cyl.stp"
)

pytestmark = pytest.mark.skipif(
    _GATE, reason="set STEP_NETWORK_TESTS=1 to run network-fetched STEP tests"
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app)


def _fetch(url: str) -> bytes:
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (test only)
        return resp.read()


def test_real_step_costs_end_to_end(client):
    pytest.importorskip("gmsh", reason="gmsh not installed; STEP path unavailable")
    data = _fetch(_URL)
    assert data[:13] == b"ISO-10303-21;", "fixture is not a STEP file"

    r = client.post(
        "/api/v1/validate/cost",
        files={"file": ("eight_cyl.stp", data, "application/octet-stream")},
        data={"qty": "50,5000", "material_class": "aluminum", "region": "US"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert body["geometry"]["watertight"] is True
    assert body["geometry"]["volume_cm3"] > 100  # real part, not a toy
    assert body["decision"] and body["decision"]["make_now_process"]
    for e in body["estimates"]:
        assert abs(e["unit_cost_usd"] - round(sum(e["line_items"].values()), 2)) < 0.02
        for d in e["drivers"]:
            assert d["provenance"] in ("MEASURED", "USER", "DEFAULT")
