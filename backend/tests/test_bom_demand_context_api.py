"""Verify must receive the resolved BOM quantity without overwriting its fallback."""
import os

import pytest
from httpx import ASGITransport, AsyncClient
from ulid import ULID

from src.db import engine
from src.services import bom_service, part_context_service
from tests.test_bom_api import _seed_org
from tests.test_part_context_api import _act_as, _build_app


@pytest.mark.skipif(not os.getenv("DATABASE_URL", "").startswith("postgresql"), reason="requires local Postgres")
@pytest.mark.asyncio
async def test_context_read_and_write_expose_bom_demand_and_preserve_flat_fallback():
    try:
        # The org, its BOM and the part's context are committed: the role gate
        # reads membership in its own session, so rows left uncommitted in a
        # test transaction are invisible to it. The org is new each run.
        async with engine.get_session_factory()(expire_on_commit=False) as session:
            org = str(ULID())
            uid = await _seed_org(session, org, f"bom-context-{org.lower()}@example.com")
            await bom_service.ingest_bom_rows(session, org, "assembly", [
                {"parent_ref": "root", "child_ref": "part", "qty_per_parent": 8},
            ])
            await part_context_service.upsert_context(session, org, "mesh", {
                "annual_volume": 55, "bom_assembly_key": "assembly",
                "bom_child_ref": "part", "bom_roots_per_year": 126,
            })
            await session.commit()

        app = _build_app()
        _act_as(app, uid)
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            for method, fields in [("GET", None), ("PUT", {"service_environment": {}})]:
                response = await client.request(method, "/api/v1/part-context/mesh", json=fields)
                assert response.status_code == 200, response.text
                result = response.json()
                assert result["annual_volume"] == 55
                assert result["resolved_annual_volume"] == 1008
                assert result["annual_volume_basis"] == "bom_rollup"
            response = await client.put("/api/v1/part-context/mesh", json={"bom_roots_per_year": None})
            assert response.status_code == 200
            assert response.json()["resolved_annual_volume"] == 55
            assert response.json()["annual_volume_basis"] == "declared"
    finally:
        await engine.dispose_engine()
