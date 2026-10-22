"""POST /validate/cost with the compute budget full: an honest 429, then admitted once room frees.

The web process holds room in its compute budget for a check's parse and price.
When there is none within ``COMPUTE_WAIT_SECONDS`` it answers the existing 429
``server_busy`` with Retry-After; a request whose room frees while it waits runs.
"""
from __future__ import annotations

import asyncio
import importlib
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.services import compute_budget


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    # One tiny check needs ~165 MB in the memory model: with 200 MB, a full
    # budget leaves no room for it.
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "200")
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "0.5")
    import main

    importlib.reload(main)
    with TestClient(main.app) as test_client:
        yield test_client


def _fill_budget() -> compute_budget.Reservation:
    """Take the whole budget from outside the app (another piece of work running)."""
    budget = compute_budget.budget()
    return asyncio.run(budget.reserve(compute_budget.memory_capacity_bytes(), wait=None, label="other work"))


def _post_cost(client, data):
    return client.post(
        "/api/v1/validate/cost",
        files={"file": ("cube.stl", data, "application/octet-stream")},
        data={"qty": "50,5000", "material_class": "polymer", "region": "US"},
    )


def test_cost_answers_429_server_busy_within_the_bound_when_full(client, cube_10mm, stl_bytes_of):
    held = _fill_budget()
    try:
        t0 = time.monotonic()
        r = _post_cost(client, stl_bytes_of(cube_10mm))
        took = time.monotonic() - t0
        assert r.status_code == 429, r.text
        body = r.json()
        code = body.get("code") or (body.get("detail") or {}).get("code")
        assert code == "server_busy", body
        assert int(r.headers["retry-after"]) >= 1
        assert took < 5, took  # COMPUTE_WAIT_SECONDS=0.5, not the analysis timeout
        assert compute_budget.budget().snapshot()["waiting"] == 0
    finally:
        held.leave()
    # Room again: the same request is admitted and priced.
    r = _post_cost(client, stl_bytes_of(cube_10mm))
    assert r.status_code == 200, r.text
    assert compute_budget.budget().snapshot()["used_bytes"] == 0


def test_cost_is_admitted_when_room_frees_during_its_wait(client, cube_10mm, stl_bytes_of, monkeypatch):
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "10")
    held = _fill_budget()
    threading.Timer(0.4, held.leave).start()
    t0 = time.monotonic()
    r = _post_cost(client, stl_bytes_of(cube_10mm))
    assert r.status_code == 200, r.text
    assert time.monotonic() - t0 >= 0.4
    assert r.json().get("decision") is not None or r.json().get("status") == "OK"


def test_validate_answers_429_server_busy_when_full(client, cube_10mm, stl_bytes_of):
    held = _fill_budget()
    try:
        r = client.post("/api/v1/validate", files={"file": ("cube.stl", stl_bytes_of(cube_10mm), "application/octet-stream")})
        assert r.status_code == 429, r.text
        assert r.headers.get("retry-after")
    finally:
        held.leave()
