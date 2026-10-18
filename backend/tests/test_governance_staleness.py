"""Approving a governed change marks older decisions stale, like a direct publish.

The rate-card and shop-profile publish routes mark the org's older saved cost
decisions stale (``rate_library_published:vN`` /
``shop_profile_published:<slug>:vN``). Approving a governance change request
publishes the same draft through the same ``publish_version`` but skipped that
step, so a change that went THROUGH review left every older decision reading
``is_stale: false`` while a change that bypassed review did not.

Drives the real approve route, governance service and library publish against
in-memory SQLite copies of the real tables; only auth is stubbed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from ulid import ULID

from src.db.models import (
    ApiKey,
    AuditLog,
    ChangeRequest,
    CostDecision,
    Notification,
    Organization,
    RateCardVersion,
    ShopProfileVersion,
    User,
)
from src.services import cost_decision_service, rate_library_service
from src.services import governance_service as gov
from tests.sqlite_tables import sqlite_sessionmaker

ORG = "01ORGG0000000000000000000G"
ADMIN = 1

_EXPECTED_REASON = {
    gov.ASSET_RATE_CARD: "rate_library_published:v1",
    gov.ASSET_SHOP_PROFILE: "shop_profile_published:acme-machining:v1",
}


async def _seed(maker, asset_type: str) -> int:
    then = datetime.now(timezone.utc) - timedelta(days=1)
    async with maker() as s:
        s.add_all([
            Organization(id=ORG, name="G", slug="org-g"),
            User(id=ADMIN, email="admin@example.com", email_lower="admin@example.com",
                 role="analyst", auth_provider="password"),
        ])
        await s.flush()
        s.add(CostDecision(
            user_id=ADMIN, org_id=ORG, mesh_hash="mesh-1", params_hash="p-1",
            engine_version="test", filename="part.stl", file_type="stl",
            result_json={}, approval_status="unreviewed", is_public=False,
            created_at=then,
        ))
        if asset_type == gov.ASSET_RATE_CARD:
            draft = RateCardVersion(
                org_id=ORG, version=1, name="2026 Q4", status="draft",
                payload=rate_library_service.default_rate_payload(),
            )
        else:
            draft = ShopProfileVersion(
                org_id=ORG, version=1, slug="acme-machining", name="Acme",
                status="draft", payload={},
            )
        s.add(draft)
        await s.flush()
        cr = ChangeRequest(
            ulid=str(ULID()), org_id=ORG, asset_type=asset_type,
            target_version_id=draft.id, status="proposed", title="", note="",
            proposed_by=ADMIN,
        )
        s.add(cr)
        await s.commit()
        return cr.id


def _governance_app(maker):
    from fastapi import FastAPI

    from src.api.governance import router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    async def _session():
        async with maker() as s:
            yield s

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(router, prefix="/api/v1/governance")
    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=ADMIN, api_key_id=0, key_prefix="session", role="analyst"
    )
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_type", sorted(_EXPECTED_REASON))
async def test_approving_a_change_request_marks_older_decisions_stale(asset_type):
    engine, maker = await sqlite_sessionmaker(
        Organization, User, ApiKey, AuditLog, Notification, ChangeRequest,
        RateCardVersion, ShopProfileVersion, CostDecision,
    )
    try:
        cr_id = await _seed(maker, asset_type)
        app = _governance_app(maker)
        with patch(
            "src.auth.rbac.lookup_org_membership",
            new=AsyncMock(return_value=(ORG, "admin")),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as c:
                r = await c.post(f"/api/v1/governance/change-requests/{cr_id}/approve")
        assert r.status_code == 200, r.text
        assert r.json()["published_version"]["status"] == "published"

        async with maker() as s:
            (decision,) = (await s.execute(select(CostDecision))).scalars().all()
    finally:
        await engine.dispose()

    fields = cost_decision_service.governance_fields(decision)
    assert fields["is_stale"] is True
    assert fields["stale_reason"] == _EXPECTED_REASON[asset_type]
