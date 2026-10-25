"""Saved verdicts go stale in BOTH places they are served from.

A part's in-house verdict is served twice: by the ``part_summaries`` makeability
projection (the Triage / catalog rollup: "N verdict(s) predate a recent
machine-inventory change and are marked stale") and by the saved cost decision
it was projected from (``is_stale`` on the decision list/detail and RFQ
packages). A machine-inventory change used to mark only the projection, so the
rollup could report 7 stale verdicts while every one of those decisions still
read ``is_stale: false`` and showed no "re-cost before relying on this record"
warning.

These tests drive the real routes against in-memory SQLite copies of the real
tables (``tests/sqlite_tables.py``); only auth and org resolution are stubbed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db.models import (
    ApiKey,
    AuditLog,
    CostDecision,
    MachineInstance,
    Organization,
    PartSummary,
    ShopCapabilities,
    User,
)
from src.services import cost_decision_service
from src.services import machine_inventory_service
from src.services.catalog_service import build_makeability_rollup
from tests.sqlite_tables import sqlite_sessionmaker

ORG_A = "01ORGA0000000000000000000A"
ORG_B = "01ORGB0000000000000000000B"
USER_ID = 1
EXISTING_MACHINE = "01MACHA00000000000000000AA"

_MACHINE = {
    "name": "VF-2 #2",
    "process": "cnc_3axis",
    "count": 1,
    "max_workpiece_kg": 200,
    "hourly_rate_usd": 75,
    "capital_frac": 0.4,
    "capabilities": {"x": 762, "y": 406, "z": 508, "axes": 3,
                     "achievable_it_grade": 9},
    "materials": ["304 Stainless"],
}

_CSV = (
    machine_inventory_service.MACHINE_HEADER + "\n"
    + machine_inventory_service._example_row() + "\n"
).encode()

# Every machine-inventory write that changes the §0 verdict inputs:
# (method, path under the router, request kwargs, expected status).
_INVENTORY_WRITES = {
    "create": ("POST", "", {"json": _MACHINE}, 201),
    "import": ("POST", "/import", {"files": {"file": ("m.csv", _CSV, "text/csv")}}, 200),
    "patch": ("PATCH", f"/{EXISTING_MACHINE}", {"json": {"count": 3}}, 200),
    "delete": ("DELETE", f"/{EXISTING_MACHINE}", {}, 200),
    "shop_caps": ("PUT", "/shop-capabilities", {"json": {"ops": {"heat_treat": True}}}, 200),
}


def _decision(org_id: str, mesh_hash: str, created_at: datetime) -> CostDecision:
    return CostDecision(
        user_id=USER_ID,
        org_id=org_id,
        mesh_hash=mesh_hash,
        params_hash=f"params-{mesh_hash}",
        engine_version="test",
        filename=f"{mesh_hash}.stl",
        file_type="stl",
        result_json={"verification": {"verdict": "in_house_now"}},
        approval_status="unreviewed",
        is_public=False,
        created_at=created_at,
    )


def _summary(org_id: str, mesh_hash: str, verdict, updated_at: datetime) -> PartSummary:
    return PartSummary(
        org_id=org_id,
        mesh_hash=mesh_hash,
        triage_bucket="makeable",
        has_analysis=False,
        has_cost=True,
        updated_at=updated_at,
        row_json={},
        makeability_verdict=verdict,
        makeability_bucket="makeable_in_house" if verdict else "unknown",
        makeability_stale=False,
    )


async def _seed(maker, n_verdicts: int = 7):
    """Org A: ``n_verdicts`` costed parts carrying a verdict (one saved decision
    each) + one costed part with no verdict. Org B: one costed part."""
    then = datetime.now(timezone.utc) - timedelta(days=1)
    async with maker() as s:
        s.add_all([
            Organization(id=ORG_A, name="A", slug="org-a"),
            Organization(id=ORG_B, name="B", slug="org-b"),
            User(id=USER_ID, email="eng@example.com", email_lower="eng@example.com",
                 role="analyst", auth_provider="password"),
        ])
        await s.flush()
        s.add(MachineInstance(
            ulid=EXISTING_MACHINE, org_id=ORG_A, process="cnc_3axis", count=1,
            capabilities={"x": 500, "y": 400, "z": 300, "axes": 3},
        ))
        for i in range(n_verdicts):
            mesh = f"mesh-a-{i}"
            s.add(_summary(ORG_A, mesh, "in_house_now", then))
            s.add(_decision(ORG_A, mesh, then))
        s.add(_summary(ORG_A, "mesh-a-noverdict", None, then))
        s.add(_summary(ORG_B, "mesh-b-0", "in_house_now", then))
        s.add(_decision(ORG_B, "mesh-b-0", then))
        await s.commit()


def _machine_app(maker, monkeypatch):
    from fastapi import FastAPI

    import src.api.machine_inventory as mi
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    async def _session():
        async with maker() as s:
            yield s

    async def _resolve_org(session, user_id):
        return ORG_A

    monkeypatch.setattr(mi, "resolve_org", _resolve_org)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(mi.router, prefix="/api/v1/machine-inventory")
    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=USER_ID, api_key_id=0, key_prefix="session", role="analyst"
    )
    return app


async def _decisions(maker, org_id: str) -> list[CostDecision]:
    async with maker() as s:
        return list(
            (await s.execute(
                select(CostDecision).where(CostDecision.org_id == org_id)
            )).scalars().all()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("write", sorted(_INVENTORY_WRITES))
async def test_machine_change_marks_saved_decisions_stale_with_their_verdicts(
    monkeypatch, write
):
    method, path, kwargs, expected_status = _INVENTORY_WRITES[write]
    engine, maker = await sqlite_sessionmaker(
        Organization, User, ApiKey, AuditLog, MachineInstance, ShopCapabilities,
        PartSummary, CostDecision,
    )
    try:
        await _seed(maker, n_verdicts=7)
        app = _machine_app(maker, monkeypatch)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            r = await c.request(method, f"/api/v1/machine-inventory{path}", **kwargs)
        assert r.status_code == expected_status, r.text

        async with maker() as s:
            rollup = (await build_makeability_rollup(s, ORG_A))["summary"]
        decisions_a = await _decisions(maker, ORG_A)
        decisions_b = await _decisions(maker, ORG_B)
    finally:
        await engine.dispose()

    # Source 1 — the Triage / catalog rollup: the 7 verdict-carrying parts are
    # stale (the no-verdict part is honestly ``unknown``, not stale).
    assert rollup["stale"] is True
    assert rollup["stale_count"] == 7

    # Source 2 — the saved decisions those verdicts were projected from now say
    # the same thing, with a reason naming the change.
    assert len(decisions_a) == 7
    for d in decisions_a:
        gov = cost_decision_service.governance_fields(d)
        assert gov["is_stale"] is True, d.mesh_hash
        assert gov["stale_reason"] == cost_decision_service.MACHINE_INVENTORY_STALE_REASON

    # Another org's inventory never touches this org's records.
    assert [
        cost_decision_service.governance_fields(d)["is_stale"] for d in decisions_b
    ] == [False]
