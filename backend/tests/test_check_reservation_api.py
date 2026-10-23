"""A part check's calls through the real app: one reservation, sized from the mesh.

The app checks a part with several calls on the same file at once (the preview
mesh and ``/validate``, then ``/validate/cost``). Admission names the check
(organization, person, file) and the compute budget gives its calls one
reservation; a STEP is held at its parse size, then at what its mesh needs.
A web request's read-only transaction ends before it waits for room.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import threading
import time
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.auth.require_api_key import AuthedUser
from src.services import compute_budget

ASSETS = Path(__file__).parent / "assets"
MB = compute_budget.MB


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    monkeypatch.setenv("COMPUTE_MEMORY_BUDGET_MB", "4000")
    monkeypatch.setenv("COMPUTE_WAIT_SECONDS", "20")
    import main

    importlib.reload(main)
    from src.auth.require_api_key import require_api_key

    def _member(request: Request) -> AuthedUser:
        user = AuthedUser(user_id=7, api_key_id=1, key_prefix="testkey1", role="analyst")
        request.state.authed_user = user  # what the real dependency sets: admission reads it
        return user

    async def _org(_user_id):
        return ("org-check", "member")

    main.app.dependency_overrides[require_api_key] = _member
    monkeypatch.setattr("src.api.admission.lookup_org_membership", _org)
    monkeypatch.setenv("ADMISSION_CHECK_GRACE_SECONDS", "0")
    with TestClient(main.app) as client:
        yield client


def _recording(monkeypatch):
    """Every reservation and re-size the budget is asked for, with the check it belongs to."""
    seen = {"reserve": [], "resize": []}
    real_reserve = compute_budget.ComputeBudget.reserve
    real_resize = compute_budget.ComputeBudget.resize

    async def reserve(self, need_bytes, *, wait, label="cad", **kw):
        h = await real_reserve(self, need_bytes, wait=wait, label=label, **kw)
        seen["reserve"].append((label, need_bytes, compute_budget.check_key(), h.reservation))
        return h

    async def resize(self, hold, need_bytes, *, wait):
        await real_resize(self, hold, need_bytes, wait=wait)
        seen["resize"].append((hold.label, need_bytes, hold.need_bytes))

    monkeypatch.setattr(compute_budget.ComputeBudget, "reserve", reserve)
    monkeypatch.setattr(compute_budget.ComputeBudget, "resize", resize)
    return seen


def test_the_preview_and_the_check_of_one_file_share_one_reservation(app_client, monkeypatch):
    from src.api import routes

    seen = _recording(monkeypatch)
    real_glb = routes._build_preview_glb

    def slow_glb(*a, **k):
        time.sleep(1.0)  # the preview still holds its room when the check's analysis asks
        return real_glb(*a, **k)

    monkeypatch.setattr(routes, "_build_preview_glb", slow_glb)
    data = (ASSETS / "cube.step").read_bytes()
    out = {}

    def call(name, path):
        out[name] = app_client.post(path, files={"file": ("cube.step", data, "application/octet-stream")})

    threads = [threading.Thread(target=call, args=("preview", "/api/v1/validate/preview-mesh?purpose=analysis")),
               threading.Thread(target=call, args=("validate", "/api/v1/validate"))]
    for t in threads:
        t.start()
        time.sleep(0.2)
    for t in threads:
        t.join(120)
    assert out["preview"].status_code == 200, out["preview"].text
    assert out["validate"].status_code == 200, out["validate"].text
    checks = {key for _l, _n, key, _r in seen["reserve"]}
    assert checks == {f"org-check:7:{hashlib.sha256(data).hexdigest()}"}
    labels = {label for label, *_ in seen["reserve"]}
    assert {"preview mesh", "analysis"} <= labels
    # One room for both calls: the same reservation object, one slot.
    assert len({id(r) for *_x, r in seen["reserve"]}) == 1
    assert compute_budget.budget().snapshot()["used_bytes"] == 0


def test_a_step_check_holds_its_parse_then_what_its_mesh_needs(app_client, monkeypatch):
    seen = _recording(monkeypatch)
    data = (ASSETS / "plate-with-boss.step").read_bytes()
    r = app_client.post("/api/v1/validate", files={"file": ("plate.step", data, "application/octet-stream")})
    assert r.status_code == 200, r.text
    faces = r.json()["geometry"]["faces"]
    first = [(label, need) for label, need, *_ in seen["reserve"]][0]
    assert first == ("analysis", compute_budget.parse_need_for_data(data, "plate.step"))
    assert first[1] < compute_budget.need_for_data(data, "plate.step")  # not the 902 MB face-budget floor
    assert ("analysis", compute_budget.need_for_mesh(faces, len(data), "plate.step"),
            compute_budget.need_for_mesh(faces, len(data), "plate.step")) in seen["resize"]


@pytest.mark.asyncio
async def test_a_web_request_gives_its_read_connection_back_before_it_waits():
    # The same database the suite uses (conftest): CI sets only DATABASE_URL.
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL (TEST_DATABASE_URL or DATABASE_URL)")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from src.services.analysis_service import release_read_connection

    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            assert session.in_transaction()
            await release_read_connection(session)
            assert not session.in_transaction()  # its connection is back in the pool
            await session.execute(text("SELECT 1"))  # and the session still works
            # A pending write is never committed early...
            from src.db.models import Batch

            session.add(Batch(ulid="01TESTRELEASEREADCONNECTN0", user_id=1, input_mode="zip", status="pending"))
            await release_read_connection(session)
            assert session.in_transaction() and session.new
            await session.rollback()
            # ...and a worker's session (its job's writes) is left alone.
            await session.execute(text("SELECT 1"))
            compute_budget.worker_process()
            try:
                await release_read_connection(session)
                assert session.in_transaction()
            finally:
                compute_budget.reset_for_tests()
    finally:
        await engine.dispose()
