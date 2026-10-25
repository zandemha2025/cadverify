"""A web request refuses a file its process can't hold in memory.

The one-request check (/validate, /validate/cost and its siblings) sizes the
upload with the worker's measured memory model before parsing it. A file whose
estimated need is over this process's budget is refused with 413
CHECK_TOO_LARGE, the worker's own plain message, and the big-file check
endpoints. MAX_UPLOAD_MB stays the outer cap.
"""
from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient

from src.services import stored_check_service as svc

MB = 1024**2


@pytest.fixture()
def client(monkeypatch):
    import importlib

    import main

    monkeypatch.setenv("MAX_UPLOAD_MB", "100")
    # conftest installs its auth and database stand-ins on a reloaded app.
    importlib.reload(main)
    return TestClient(main.app)


def _step(size: int) -> bytes:
    head = b"ISO-10303-21;\nHEADER;\n"
    return head + b" " * (size - len(head))


def _binary_stl(triangles: int) -> bytes:
    return b"\0" * 80 + struct.pack("<I", triangles) + b"\0" * (50 * triangles)


def _no_analysis(monkeypatch):
    from src.services import analysis_service

    async def _fail(*_a, **_k):
        raise AssertionError("the file was analysed although it is over the memory budget")

    monkeypatch.setattr(analysis_service, "run_analysis", _fail)


def test_validate_refuses_a_step_file_over_the_memory_budget(client, monkeypatch):
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "1229")
    _no_analysis(monkeypatch)
    data = _step(5 * MB)
    r = client.post("/api/v1/validate", files={"file": ("asm.step", data, "application/octet-stream")})
    assert r.status_code == 413, r.text
    body = r.json()
    detail = body.get("detail", body)
    need, basis = svc.estimate_memory_bytes_for_data(data, "asm.step")
    assert detail["code"] == "CHECK_TOO_LARGE"
    assert detail["message"] == svc.too_heavy_message(need, basis, 1229 * MB)
    assert detail["message"].endswith("Nothing was charged.")
    assert detail["big_file_check"] == {"upload": "/api/v1/uploads/multipart", "check": "/api/v1/checks"}


def test_cost_refuses_a_binary_stl_over_the_memory_budget(client, monkeypatch):
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "600")
    data = _binary_stl(200_000)  # about 10 MB; needs about 0.8 GB
    r = client.post("/api/v1/validate/cost", files={"file": ("part.stl", data, "application/octet-stream")})
    assert r.status_code == 413, r.text
    body = r.json()
    detail = body.get("detail", body)
    assert detail["code"] == "CHECK_TOO_LARGE"
    assert "STL" in detail["message"]


def test_a_file_within_the_budget_is_checked(client, monkeypatch):
    from fastapi import HTTPException

    from src.services import analysis_service

    async def _reached(*_a, **_k):
        raise HTTPException(status_code=422, detail="reached the analysis")

    monkeypatch.setattr(analysis_service, "run_analysis", _reached)
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "100000")
    r = client.post(
        "/api/v1/validate",
        files={"file": ("asm.step", _step(5 * MB), "application/octet-stream")},
    )
    assert r.status_code == 422, r.text


def test_a_real_part_under_the_budget_still_checks(client, monkeypatch):
    import trimesh

    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "1229")
    data = trimesh.creation.box(extents=(20, 15, 10)).export(file_type="stl")
    r = client.post("/api/v1/validate", files={"file": ("box.stl", data, "application/octet-stream")})
    assert r.status_code == 200, r.text


def test_upload_limit_stays_the_outer_cap(client, monkeypatch):
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "100000")
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    r = client.post(
        "/api/v1/validate",
        files={"file": ("asm.step", _step(2 * MB), "application/octet-stream")},
    )
    assert r.status_code == 413
    assert "CHECK_TOO_LARGE" not in r.text


def test_the_web_and_worker_estimates_agree(tmp_path):
    for name, data in (("a.step", _step(3 * MB)), ("b.stl", _binary_stl(50_000)),
                       ("c.stl", b"solid c\n" + b"x" * (2 * MB)), ("d.iges", b"S" * MB)):
        p = tmp_path / name
        p.write_bytes(data)
        assert svc.estimate_memory_bytes_for_data(data, name) == svc.estimate_memory_bytes(str(p), name)


@pytest.mark.asyncio
async def test_bom_assembly_ingest_uses_the_same_memory_gate(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from tests.test_bom_assembly_limits import _app

    calls: list = []
    app = _app(monkeypatch, calls)
    monkeypatch.setenv("CHECK_MEMORY_BUDGET_MB", "1229")
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as c:
        r = await c.post("/api/v1/bom/ingest-assembly?assembly_key=k",
                         files={"file": ("asm.step", _step(5 * MB))})
    assert r.status_code == 413, r.text
    assert r.json()["detail"]["code"] == "CHECK_TOO_LARGE"
    assert calls == []
