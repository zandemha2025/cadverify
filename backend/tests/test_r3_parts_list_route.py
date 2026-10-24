"""Security review R3, F1 (route): POST /api/v1/catalog-runs/parts-list answers a
hostile cell fast, and reads the list in a worker thread, never on the event loop."""
from __future__ import annotations

import asyncio
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import batch_router
from src.auth.rbac import require_org_writer
from src.auth.require_api_key import AuthedUser
from src.services import catalog_run_service


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(batch_router.router)
    app.dependency_overrides[require_org_writer] = lambda: AuthedUser(
        user_id=1, api_key_id=0, key_prefix="session", role="analyst", org_id="org1")
    return TestClient(app)


def _post(body: bytes):
    t = time.monotonic()
    r = _client().post("/api/v1/catalog-runs/parts-list", files={"manifest": ("list.csv", body, "text/csv")})
    return r, time.monotonic() - t


def test_parts_list_check_is_fast_on_a_hostile_ra_cell():
    r, elapsed = _post(("file,Ra\npart.stl,1" + " " * 1600 + "x\n").encode())
    assert r.status_code == 200, r.text[:300]
    # Was ~9 s for a 1.6 KB cell, all of it on the event loop (O(n^3) in the run of spaces).
    assert elapsed < 1.0, f"took {elapsed:.1f}s"
    body = r.json()
    assert body["ok"] is False
    assert [(p["row"], p["column"], p["why"]) for p in body["problems"]] == [
        (2, "Ra", "is longer than 1,000 characters")]


def test_a_hostile_ra_cell_under_the_cap_is_a_note_and_fast():
    r, elapsed = _post(("file,Ra\npart.stl,1" + " " * 990 + "x\n").encode())
    assert elapsed < 1.0, f"took {elapsed:.1f}s"  # was ~2 s
    body = r.json()
    assert body["ok"] is True and body["rows"] == 1
    assert body["not_priced"]["count"] == 1 and body["not_priced"]["notes"][0]["column"] == "Ra"


def test_the_list_is_read_in_a_worker_thread(monkeypatch):
    on_loop: list[bool] = []
    real = catalog_run_service.read_parts_list

    def spy(text: str):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real(text)

    monkeypatch.setattr(catalog_run_service, "read_parts_list", spy)
    r, _ = _post(b"file,qty,Ra\npart.stl,10,0.8 um\n")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert on_loop == [False]
