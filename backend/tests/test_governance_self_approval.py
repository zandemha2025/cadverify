"""A proposer can't approve their own rate-card change when another admin can (ce-13).

Priyanka proposed labor $35 -> $58/h and approved it herself: "at Northfield that
would be a segregation-of-duties problem". With another admin in the organization
the approve route refuses the proposer (403 ``self_approval``) and the other admin
approves; in a single-admin organization the proposer may, and the request reads
``self_approved``. Drives the real approve route and governance service against
in-memory SQLite copies of the real tables; only auth is stubbed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from ulid import ULID

from src.db.models import (
    ApiKey,
    AuditLog,
    ChangeRequest,
    CostDecision,
    Membership,
    Notification,
    Organization,
    RateCardVersion,
    ShopProfileVersion,
    User,
)
from src.services import rate_library_service
from tests.sqlite_tables import sqlite_sessionmaker

ORG = "01ORGNFP000000000000000000"
PRIYANKA, DANA = 1, 2


async def _seed(maker, admins):
    async with maker() as s:
        s.add(Organization(id=ORG, name="Northfield Pumps", slug="nfp"))
        for uid in (PRIYANKA, DANA):
            s.add(User(id=uid, email=f"u{uid}@northfieldpumps.com", email_lower=f"u{uid}@northfieldpumps.com",
                       role="analyst", auth_provider="password"))
        await s.flush()
        for uid in admins:
            s.add(Membership(org_id=ORG, user_id=uid, org_role="admin"))
        payload = rate_library_service.default_rate_payload()
        payload["global"]["labor_rate"] = 58.0
        draft = RateCardVersion(org_id=ORG, version=1, name="Labor $58", status="draft", payload=payload)
        s.add(draft)
        await s.flush()
        cr = ChangeRequest(ulid=str(ULID()), org_id=ORG, asset_type="rate_card", target_version_id=draft.id,
                           status="proposed", title="Labor $35 -> $58/h", note="", proposed_by=PRIYANKA)
        s.add(cr)
        await s.commit()
        return cr.id


def _app(maker, user_id):
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
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")
    return app


async def _call(maker, user_id, method, path):
    with patch("src.auth.rbac.lookup_org_membership", new=AsyncMock(return_value=(ORG, "admin"))), \
            patch("src.api.governance.resolve_org", new=AsyncMock(return_value=ORG)):
        async with AsyncClient(transport=ASGITransport(app=_app(maker, user_id)), base_url="http://t") as c:
            return await (c.post(path) if method == "post" else c.get(path))


async def _tables():
    return await sqlite_sessionmaker(Organization, User, ApiKey, Membership, AuditLog, Notification,
                                     ChangeRequest, RateCardVersion, ShopProfileVersion, CostDecision)


@pytest.mark.asyncio
async def test_with_another_admin_the_proposer_cant_approve_and_the_other_admin_can():
    engine, maker = await _tables()
    try:
        cr = await _seed(maker, admins=(PRIYANKA, DANA))
        r = await _call(maker, PRIYANKA, "post", f"/api/v1/governance/change-requests/{cr}/approve")
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "self_approval"
        assert r.json()["detail"]["message"] == ("You proposed this change, so another admin approves it. "
                                                 "Your organization has 1 other admin.")
        listing = (await _call(maker, PRIYANKA, "get", "/api/v1/governance/change-requests")).json()
        assert listing["admins"] == 2 and listing["change_requests"][0]["status"] == "proposed"
        r = await _call(maker, DANA, "post", f"/api/v1/governance/change-requests/{cr}/approve")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["change_request"]["status"] == "approved"
        assert body["change_request"]["self_approved"] is False
        assert body["published_version"]["payload"]["global"]["labor_rate"] == 58.0
    finally:
        await engine.dispose()
        rate_library_service.invalidate(ORG)


@pytest.mark.asyncio
async def test_single_admin_org_may_self_approve_and_it_says_so():
    engine, maker = await _tables()
    try:
        cr = await _seed(maker, admins=(PRIYANKA,))
        r = await _call(maker, PRIYANKA, "post", f"/api/v1/governance/change-requests/{cr}/approve")
        assert r.status_code == 200, r.text
        assert r.json()["change_request"]["self_approved"] is True
        listing = (await _call(maker, PRIYANKA, "get", "/api/v1/governance/change-requests")).json()
        assert listing["admins"] == 1 and listing["change_requests"][0]["self_approved"] is True
    finally:
        await engine.dispose()
        rate_library_service.invalidate(ORG)
