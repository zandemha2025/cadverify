"""POST /api/v1/validate/cost — opt-in ensemble `uncertainty` block (Moat P1).

Proves the assumption-ensemble band is a strictly ADDITIVE, opt-in response
block: OFF (default) the response is byte-identical to today (no key); ON the
response gains an honest `uncertainty` block whose bands are ordered and
labelled as an assumption spread, WITHOUT moving the point estimate. Mirrors the
style of tests/test_cost_api.py — procedural meshes, real FastAPI app via
TestClient + the conftest autouse auth/DB bypass, no external services.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from src.costing.ensemble import COST_ENSEMBLE_ENABLED


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    import main

    importlib.reload(main)  # conftest re-applies the auth/DB bypass on reload
    return TestClient(main.app)


def _post(client, name, data, **form):
    return client.post(
        "/api/v1/validate/cost",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def _post_demo(client, name, data, **form):
    return client.post(
        "/api/v1/validate/cost/demo",
        files={"file": (name, data, "application/octet-stream")},
        data=form,
    )


def test_flag_off_has_no_uncertainty_key(client, monkeypatch, cube_10mm, stl_bytes_of):
    """OFF (default): the response has NO `uncertainty` key and the usual
    decision shape is unchanged — byte-identical to today."""
    monkeypatch.delenv(COST_ENSEMBLE_ENABLED, raising=False)
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="50,5000",
              material_class="polymer", region="US")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "uncertainty" not in body
    # rest of the response shape unchanged
    assert body["status"] == "OK"
    assert body["decision"] and body["decision"]["make_now_process"]
    assert body["estimates"]


def test_flag_on_adds_honest_uncertainty_block(
    client, monkeypatch, cube_10mm, stl_bytes_of
):
    """ON: an `uncertainty` block with ordered assumption bands (p10<=p50<=p90),
    validated False, the assumption label, and disagreement_cov >= 0."""
    monkeypatch.setenv(COST_ENSEMBLE_ENABLED, "1")
    r = _post(client, "cube.stl", stl_bytes_of(cube_10mm), qty="50,5000",
              material_class="polymer", region="US")
    assert r.status_code == 200, r.text
    body = r.json()
    unc = body.get("uncertainty")
    assert unc is not None, "flag ON must attach an uncertainty block"

    # Honest labels come straight from the ensemble — never relabelled measured.
    assert unc["validated"] is False
    assert unc["method"] == "assumption-ensemble"
    assert "not shop-validated" in unc["label"]
    assert unc["bands"], "expected per-(process, qty) bands"

    for b in unc["bands"]:
        assert b["p10_usd"] <= b["p50_usd"] <= b["p90_usd"]
        assert b["validated"] is False
        assert "not shop-validated" in b["label"]
        assert b["disagreement_cov"] >= 0
        # point rides byte-identical to member 0 (unperturbed baseline)
        assert b["point_usd"] == b["point_usd"]


def test_flag_on_does_not_move_the_point(
    client, monkeypatch, cube_10mm, stl_bytes_of
):
    """The ensemble NEVER moves the point: every estimate's unit_cost_usd is
    IDENTICAL between the flag-off and flag-on runs."""
    stl = stl_bytes_of(cube_10mm)

    monkeypatch.delenv(COST_ENSEMBLE_ENABLED, raising=False)
    off = _post(client, "cube.stl", stl, qty="50,5000",
                material_class="polymer", region="US")
    assert off.status_code == 200, off.text
    off_body = off.json()

    monkeypatch.setenv(COST_ENSEMBLE_ENABLED, "1")
    on = _post(client, "cube.stl", stl, qty="50,5000",
               material_class="polymer", region="US")
    assert on.status_code == 200, on.text
    on_body = on.json()

    def _points(body):
        return {
            (e["process"], e["quantity"]): e["unit_cost_usd"]
            for e in body["estimates"]
        }

    assert _points(off_body) == _points(on_body)

    # And the band's point matches the served point exactly.
    on_points = _points(on_body)
    for b in on_body["uncertainty"]["bands"]:
        key = (b["process"], b["quantity"])
        assert key in on_points
        assert b["point_usd"] == on_points[key]


def test_demo_route_unaffected(client, monkeypatch, cube_10mm, stl_bytes_of):
    """The public demo route (no user/session) stays byte-identical even with
    the flag ON — it never attaches an uncertainty block."""
    monkeypatch.setenv(COST_ENSEMBLE_ENABLED, "1")
    r = _post_demo(client, "cube.stl", stl_bytes_of(cube_10mm), qty="50,5000",
                   material_class="polymer", region="US")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK"
    assert body["estimates"]
    assert "uncertainty" not in body
