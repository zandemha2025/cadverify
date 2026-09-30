"""Invalid replacement uploads must preserve the customer's existing BOM."""
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from src.db import engine
from src.db.engine import get_db_session
from tests.test_bom_api import _act_as, _build_app, _seed_org


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"), reason="requires local Postgres")
@pytest.mark.asyncio
async def test_invalid_uploads_leave_saved_bom_intact():
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
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose_engine()
