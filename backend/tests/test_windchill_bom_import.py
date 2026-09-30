"""BOM preview/import API against PostgreSQL and a vendor-shaped HTTP fixture."""
import os

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.api import bom, integrations
from src.auth.rate_limit import limiter
from src.auth import rbac, kill_switch
from src.db import engine
from src.db.engine import get_db_session
from tests.test_bom_api import _act_as, _seed_org
from tests.test_connector_probe_transport import mock_http
from tests.test_windchill_bom_transport import structure


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"), reason="requires local Postgres")
@pytest.mark.asyncio
async def test_preview_import_revision_guard_failure_and_revocation(monkeypatch):
    payload = structure()
    calls = []

    def vendor(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"NonceKey": "CSRF_NONCE", "NonceValue": "nonce"})
        return httpx.Response(200, json=payload)

    mock_http(monkeypatch, vendor)
    try:
        async with engine.get_engine().connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                    org_id = str(ULID())
                    uid = await _seed_org(session, org_id, f"windchill-{org_id.lower()}@example.com")
                    await session.commit()

                async def request_session():
                    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                        yield session

                # Auth normally opens its own connection; bind its real membership
                # query to this rollback-only transaction so it sees fixture rows.
                async def membership(user_id):
                    result = await connection.execute(text(
                        "SELECT org_id, org_role FROM memberships WHERE user_id=:uid ORDER BY created_at, id LIMIT 1"
                    ), {"uid": user_id})
                    return result.first()

                monkeypatch.setattr(rbac, "lookup_org_membership", membership)

                app = FastAPI()
                app.state.limiter = limiter
                app.include_router(integrations.router, prefix="/api/v1/integrations")
                app.include_router(bom.router, prefix="/api/v1/bom")
                app.dependency_overrides[get_db_session] = request_session
                _act_as(app, uid)
                async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
                    profile = await client.post("/api/v1/integrations/credential-profiles", json={
                        "connector_id": "windchill_part_bom_readonly", "label": "Fixture connection",
                        "base_url": "https://windchill.example", "auth_type": "bearer", "secret": {"token": "fixture-only-secret"},
                    })
                    assert profile.status_code == 201, profile.text
                    profile_id = profile.json()["profile"]["id"]
                    url = f"/api/v1/integrations/credential-profiles/{profile_id}/bom-runs"
                    body = {"part_id": "OR:wt.part.WTPart:1", "assembly_key": "vendor-test"}
                    missing_preview = await client.post(url, json={**body, "mode": "import"})
                    assert missing_preview.status_code == 400
                    assert not calls, "invalid import must not send credentials"
                    preview = await client.post(url, json=body)
                    assert preview.status_code == 200, preview.text
                    preview_run = preview.json()["run"]
                    assert preview_run["status"] == "passed"
                    assert preview_run["imported_count"] == 0
                    assert preview_run["source_record_count"] == 4
                    assert preview_run["normalized_record_count"] == 4
                    before = await client.get("/api/v1/bom/vendor-test")
                    assert before.json()["edges"] == []
                    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", "false")
                    monkeypatch.setattr(kill_switch, "_CACHE_TS", 0)
                    count = len(calls)
                    paused = await client.post(url, json={**body, "mode": "import", "expected_sha256": preview_run["file_sha256"]})
                    assert paused.status_code == 503
                    assert len(calls) == count
                    monkeypatch.setenv("ACCEPTING_NEW_ANALYSES", "true")
                    monkeypatch.setattr(kill_switch, "_CACHE_TS", 0)
                    # Vendor collection order is not a change to the BOM.
                    payload["Components"].reverse()
                    imported = await client.post(url, json={**body, "mode": "import", "expected_sha256": preview_run["file_sha256"]})
                    assert imported.status_code == 200, imported.text
                    run = imported.json()["run"]
                    assert run["status"] == "passed" and run["imported_count"] == 4
                    saved = await client.get("/api/v1/bom/vendor-test/ancestry?child_ref=OR:wt.part.WTPart:4")
                    assert saved.json()["rolled_up_multiplier"] == 8
                    tree = await client.get("/api/v1/bom/vendor-test")
                    assert {edge["source"] for edge in tree.json()["edges"]} == {"windchill_api"}
                    payload["Components"][0]["PartUse"]["Quantity"] = 5
                    changed = await client.post(url, json={**body, "mode": "import", "expected_sha256": preview_run["file_sha256"]})
                    assert changed.status_code == 200, changed.text
                    assert changed.json()["run"]["status"] == "failed"
                    assert "changed" in changed.json()["run"]["errors"][0]["reason"]
                    payload["HasUnresolvedObjectsByAccessRights"] = True
                    restricted = await client.post(url, json=body)
                    assert restricted.json()["run"]["status"] == "failed"
                    kept = await client.get("/api/v1/bom/vendor-test")
                    assert kept.json()["edges"] == tree.json()["edges"]
                    ledger = await client.get(f'/api/v1/integrations/runs/{run["id"]}')
                    assert ledger.status_code == 200
                    assert ledger.json()["file_sha256"] == preview_run["file_sha256"]
                    assert "fixture-only-secret" not in ledger.text
                    await connection.execute(text("UPDATE memberships SET org_role='viewer' WHERE user_id=:uid"), {"uid": uid})
                    count = len(calls)
                    unauthorized = await client.post(url, json=body)
                    assert unauthorized.status_code == 403
                    assert len(calls) == count
                    await connection.execute(text("UPDATE memberships SET org_role='admin' WHERE user_id=:uid"), {"uid": uid})
                    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                        other_org = str(ULID())
                        other_user = await _seed_org(session, other_org, f"other-{other_org.lower()}@example.com")
                        await session.commit()
                    _act_as(app, other_user)
                    outside = await client.post(url, json=body)
                    assert outside.status_code == 404
                    assert len(calls) == count
                    hidden = await client.get(f'/api/v1/integrations/runs/{run["id"]}')
                    assert hidden.status_code == 404
                    _act_as(app, uid)
                    revoked = await client.delete(f"/api/v1/integrations/credential-profiles/{profile_id}")
                    assert revoked.status_code == 200
                    count = len(calls)
                    blocked = await client.post(url, json=body)
                    assert blocked.status_code == 409
                    assert len(calls) == count
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose_engine()
