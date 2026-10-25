"""Invalid replacement uploads must preserve the customer's existing BOM."""
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db import engine
from src.db.engine import get_db_session
from tests.test_bom_api import _act_as, _build_app, _seed_org
from tests.cad_fixtures import as1_fixture_bytes


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"), reason="requires local Postgres")
@pytest.mark.asyncio
async def test_invalid_uploads_leave_saved_bom_intact():
    from src.parsers import parse_pool
    parse_pool.startup()
    try:
        async with engine.get_engine().connect() as connection:
            transaction = await connection.begin()
            try:
                async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as session:
                    org_id = str(ULID())
                    uid = await _seed_org(session, org_id, f"bom-preserve-{org_id.lower()}@example.com")
                    await session.commit()

                async def request_session():
                    async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint") as session:
                        yield session

                app = _build_app()
                _act_as(app, uid)
                app.dependency_overrides[get_db_session] = request_session
                async with AsyncClient(transport=ASGITransport(app, raise_app_exceptions=False), base_url="http://test") as client:
                    url = "/api/v1/bom/onboard?assembly_key=preserved-tree"
                    good = await client.post(url, content="parent_ref,child_ref,qty_per_parent\ncar,door,4\ndoor,handle,2\n", headers={"content-type": "text/csv"})
                    assert good.status_code == 200, good.text
                    for content, mime in [
                        ("bad,header\nx,y\n", "text/csv"),
                        ('{"edges":42}', "application/json"),
                        ('{"edges":[]}', "application/json"),
                        ("parent_ref,child_ref,qty_per_parent\na,b,1\nb,a,1\n", "text/csv"),
                        ("parent_ref,child_ref,qty_per_parent\ncar,handle,2147483648\n", "text/csv"),
                    ]:
                        failed = await client.post(url, content=content, headers={"content-type": mime})
                        assert failed.status_code == 422, failed.text
                        saved = await client.get("/api/v1/bom/preserved-tree/ancestry?child_ref=handle")
                        assert saved.status_code == 200, saved.text
                        assert saved.json()["ancestry"] == ["handle", "door", "car"]
                        assert saved.json()["rolled_up_multiplier"] == 8
                    # One total per parent/child: neither last-row-wins nor
                    # summing ambiguous repeated lines may replace saved demand.
                    for content, mime in [
                        ("parent_ref,child_ref,qty_per_parent\ncar,door,2\ncar,door,3\n", "text/csv"),
                        ("parent_ref,child_ref,qty_per_parent\ncar,door,3\ncar,door,2\n", "text/csv"),
                        ('{"edges":[{"parent_ref":"car","child_ref":"door","qty_per_parent":2},{"parent_ref":"car","child_ref":"door","qty_per_parent":2}]}', "application/json"),
                    ]:
                        failed = await client.post(url, content=content, headers={"content-type": mime})
                        assert failed.status_code == 422, failed.text
                        assert "Duplicate BOM relationship" in failed.json()["detail"]
                        saved = await client.get("/api/v1/bom/preserved-tree/ancestry?child_ref=handle")
                        assert saved.status_code == 200, saved.text
                        assert saved.json()["rolled_up_multiplier"] == 8
                        tree = await client.get("/api/v1/bom/preserved-tree")
                        assert tree.status_code == 200, tree.text
                        assert len(tree.json()["edges"]) == 2

                    # Real STEP geometry is unchanged; only product labels
                    # collide. That must not merge distinct assembly designs.
                    original = as1_fixture_bytes()
                    assert b"'rod-assembly'" in original
                    collided = original.replace(b"'rod-assembly'", b"'l-bracket-assembly'")
                    assembly_url = "/api/v1/bom/ingest-assembly?assembly_key=preserved-tree"
                    failed = await client.post(assembly_url, files={"file": ("name-collision.step", collided)})
                    assert failed.status_code == 422, failed.text
                    assert "different child structures" in failed.json()["detail"]
                    saved = await client.get("/api/v1/bom/preserved-tree/ancestry?child_ref=handle")
                    assert saved.status_code == 200, saved.text
                    assert saved.json()["rolled_up_multiplier"] == 8

                    accepted = await client.post(assembly_url, files={"file": ("original.step", original)})
                    assert accepted.status_code == 200, accepted.text
                    for part, expected in [("bolt", 6), ("nut", 8)]:
                        saved = await client.get(f"/api/v1/bom/preserved-tree/ancestry?child_ref={part}")
                        assert saved.status_code == 200, saved.text
                        assert saved.json()["rolled_up_multiplier"] == expected
            finally:
                await transaction.rollback()
    finally:
        parse_pool.shutdown(final=True)
        await engine.dispose_engine()
