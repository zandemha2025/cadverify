"""BOM assembly ingest uses the same admission control and size cap as /validate.

``POST /bom/ingest-assembly`` runs the same OCC assembly extraction as
``/validate/assembly``, so it takes an analysis slot (429 when the server or
the org is at capacity) and refuses an upload over the web upload limit
(MAX_UPLOAD_MB) before any parse starts.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient


def _app(monkeypatch, calls: list):
    from fastapi import FastAPI

    from src.api import bom
    from src.auth.kill_switch import require_kill_switch_open
    from src.auth.org_limits import enforce_org_limits
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.auth.validation_caps import require_paid_access
    from src.db.engine import get_db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(bom.router, prefix="/api/v1/bom")

    def _user(request: Request):
        user = AuthedUser(user_id=41, api_key_id=0, key_prefix="session", role="analyst")
        request.state.authed_user = user
        return user

    class _Session:
        async def commit(self):
            return None

    async def _session():
        yield _Session()

    app.dependency_overrides[require_api_key] = _user
    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[require_paid_access] = lambda: None
    app.dependency_overrides[require_kill_switch_open] = lambda: None
    app.dependency_overrides[enforce_org_limits] = lambda: None

    async def _org(_session, _user):
        return "org-bom-limits"

    async def _membership(_uid):
        return ("org-bom-limits", "admin")

    async def _extract(data, filename):
        calls.append(len(data))
        return SimpleNamespace()

    async def _ingest(_session, org_id, key, _model):
        return {"assembly_key": key, "edges": 0, "roots": [], "source": "assembly_step"}

    monkeypatch.setattr(bom, "_require_org", _org)
    monkeypatch.setattr("src.api.admission.lookup_org_membership", _membership)
    monkeypatch.setattr("src.api.routes._extract_assembly_async", _extract)
    monkeypatch.setattr(bom.svc, "ingest_assembly", _ingest)
    monkeypatch.delenv("ADMISSION_DISABLED", raising=False)
    monkeypatch.delenv("BOM_ASSEMBLY_MAX_MB", raising=False)
    return app


async def _post(app, body: bytes):
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        return await client.post(
            "/api/v1/bom/ingest-assembly?assembly_key=k",
            files={"file": ("asm.step", body)},
        )


@pytest.mark.asyncio
async def test_ingest_assembly_waits_for_an_analysis_slot(monkeypatch):
    calls: list = []
    app = _app(monkeypatch, calls)
    monkeypatch.setenv("MAX_CONCURRENT_ANALYSES", "0")
    resp = await _post(app, b"ISO-10303-21;\nHEADER;\n")
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "server_busy"
    assert calls == []


@pytest.mark.asyncio
async def test_ingest_assembly_refuses_upload_over_web_limit(monkeypatch):
    calls: list = []
    app = _app(monkeypatch, calls)
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    resp = await _post(app, b"ISO-10303-21;\n" + b" " * (1024 * 1024 + 1))
    assert resp.status_code == 413
    assert calls == []


@pytest.mark.asyncio
async def test_bom_assembly_setting_cannot_raise_the_cap_above_web_limit(monkeypatch):
    calls: list = []
    app = _app(monkeypatch, calls)
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("BOM_ASSEMBLY_MAX_MB", "256")
    resp = await _post(app, b"ISO-10303-21;\n" + b" " * (1024 * 1024 + 1))
    assert resp.status_code == 413
    assert calls == []


@pytest.mark.asyncio
async def test_ingest_assembly_under_limits_still_runs(monkeypatch):
    calls: list = []
    app = _app(monkeypatch, calls)
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    body = b"ISO-10303-21;\n" + b" " * 1000
    resp = await _post(app, body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["assembly_key"] == "k"
    assert calls == [len(body)]
