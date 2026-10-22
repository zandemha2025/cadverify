"""A rate card can't skip review through the API (C2).

The screens publish a rate card only by approving its change request: draft →
propose → approve. The API's own ``POST /{library}/{id}/publish`` used to publish
a draft directly, so an admin could change the organization's rates with no
review at all. Now every governed library that sets prices (rate card, supplier
rate profile, material catalog) publishes only through an approved change
request: a direct publish is refused (403 ``review_required``, in plain words), a
draft under review can't be edited under the reviewer (409 ``under_review``), and
in a single-admin organization the admin approves their own change and it reads
``self_approved``.

Drives the real library and governance routers against in-memory SQLite copies of
the real tables; only auth and the caller's org are stubbed. (SQLite hands back
naive timestamps, so what the engine reads after a publish is asserted on
Postgres in ``test_{rate,shop,material}_library_api.py``.)
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from src.db.models import (
    ApiKey,
    AuditLog,
    ChangeRequest,
    CostDecision,
    MaterialLibraryVersion,
    Membership,
    Notification,
    Organization,
    RateCardVersion,
    ShopProfileVersion,
    User,
)
from src.services import material_library_service, rate_library_service, shop_library_service
from tests.sqlite_tables import sqlite_sessionmaker

ORG = "01ORGNFP000000000000000000"
PRIYANKA, DANA = 1, 2


async def _tables():
    return await sqlite_sessionmaker(
        Organization, User, ApiKey, Membership, AuditLog, Notification, ChangeRequest,
        RateCardVersion, ShopProfileVersion, MaterialLibraryVersion, CostDecision)


async def _seed(maker, admins):
    async with maker() as s:
        s.add(Organization(id=ORG, name="Northfield Pumps", slug="nfp"))
        for uid in (PRIYANKA, DANA):
            s.add(User(id=uid, email=f"u{uid}@northfieldpumps.com", email_lower=f"u{uid}@northfieldpumps.com",
                       role="analyst", auth_provider="password"))
        await s.flush()
        for uid in admins:
            s.add(Membership(org_id=ORG, user_id=uid, org_role="admin"))
        await s.commit()


def _app(maker, user_id):
    from fastapi import FastAPI

    from src.api.governance import router as governance_router
    from src.api.material_library import router as material_router
    from src.api.rate_library import router as rate_router
    from src.api.shop_library import router as shop_router
    from src.auth.rate_limit import limiter
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    async def _session():
        async with maker() as s:
            yield s

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rate_router, prefix="/api/v1/rate-library")
    app.include_router(shop_router, prefix="/api/v1/shop-library")
    app.include_router(material_router, prefix="/api/v1/material-library")
    app.include_router(governance_router, prefix="/api/v1/governance")
    app.dependency_overrides[get_db_session] = _session
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=user_id, api_key_id=0, key_prefix="session", role="analyst")
    return app


class _As:
    """An API client acting as one admin of ORG."""

    def __init__(self, maker, user_id):
        self._maker, self._uid = maker, user_id

    async def __aenter__(self):
        self._stack = ExitStack()
        org = AsyncMock(return_value=ORG)
        self._stack.enter_context(patch("src.auth.rbac.lookup_org_membership",
                                        new=AsyncMock(return_value=(ORG, "admin"))))
        for mod in ("rate_library", "shop_library", "material_library", "governance"):
            self._stack.enter_context(patch(f"src.api.{mod}.resolve_org", new=org))
        self._client = AsyncClient(transport=ASGITransport(app=_app(self._maker, self._uid)), base_url="http://t")
        return await self._client.__aenter__()

    async def __aexit__(self, *exc):
        await self._client.__aexit__(*exc)
        self._stack.close()


@pytest.fixture
def flags(monkeypatch):
    for flag in ("RATE_LIBRARY_ENABLED", "SHOP_LIBRARY_ENABLED", "MATERIAL_LIBRARY_ENABLED"):
        monkeypatch.setenv(flag, "1")
    yield
    for svc in (rate_library_service, material_library_service):
        svc.invalidate(ORG)
    shop_library_service.invalidate(ORG)


async def _rate_draft(c, labor):
    r = await c.post("/api/v1/rate-library", json={"name": f"Labor ${labor:g}"})
    assert r.status_code == 200, r.text
    draft = r.json()
    payload = draft["payload"]
    payload["global"]["labor_rate"] = labor
    r = await c.patch(f"/api/v1/rate-library/{draft['id']}", json={"payload": payload})
    assert r.status_code == 200, r.text
    return draft["id"]


async def _propose(c, asset_type, vid, title="Labor $35 -> $58/h"):
    r = await c.post("/api/v1/governance/change-requests",
                     json={"asset_type": asset_type, "target_version_id": vid, "title": title})
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _audit(maker, action):
    async with maker() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars().all())


@pytest.mark.asyncio
async def test_a_direct_publish_without_approval_is_refused_in_plain_words(flags):
    engine, maker = await _tables()
    try:
        await _seed(maker, admins=(PRIYANKA, DANA))
        async with _As(maker, PRIYANKA) as c:
            rate = await _rate_draft(c, 58.0)
            r = await c.post(f"/api/v1/rate-library/{rate}/publish", json={})
            assert r.status_code == 403, r.text
            detail = r.json()["detail"]
            assert detail["code"] == "review_required"
            assert detail["message"] == (
                "A rate card is published when an admin approves its change request, as on Your shop › Changes "
                "to review. Propose this draft for review. Another admin approves it: your organization has 1 "
                "other admin.")
            assert detail["propose"] == {"method": "POST", "path": "/api/v1/governance/change-requests",
                                         "body": {"asset_type": "rate_card", "target_version_id": rate}}
            # Nothing changed: still a draft, and the engine still uses the typical card.
            assert (await c.get(f"/api/v1/rate-library/{rate}")).json()["status"] == "draft"
            assert (await c.get("/api/v1/rate-library/effective")).json()["using_governed"] is False

            # The supplier rate profile and the material catalog set prices too.
            r = await c.post("/api/v1/shop-library", json={"slug": "midwest-precision-cnc", "name": "Q4"})
            assert r.status_code == 200, r.text
            shop = r.json()["id"]
            r = await c.post(f"/api/v1/shop-library/{shop}/publish", json={})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "review_required", r.text
            assert r.json()["detail"]["message"].startswith("A supplier rate profile is published when an admin")
            r = await c.post("/api/v1/material-library", json={
                "name": "Q4 materials", "payload": {"material_prices": {"PA12 (Nylon 12)": 26.5}, "materials": {}}})
            assert r.status_code == 200, r.text
            mat = r.json()["id"]
            r = await c.post(f"/api/v1/material-library/{mat}/publish", json={})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "review_required", r.text
            assert r.json()["detail"]["message"].startswith("A material catalog is published when an admin")
            assert (await c.get("/api/v1/material-library/effective")).json()["using_governed"] is False

            # A version that isn't in this organization is still a plain 404.
            assert (await c.post("/api/v1/rate-library/987654/publish", json={})).status_code == 404
        assert await _audit(maker, "library.version_published") == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_the_approved_path_publishes_and_the_reviewed_numbers_are_the_ones_published(flags):
    engine, maker = await _tables()
    try:
        await _seed(maker, admins=(PRIYANKA, DANA))
        async with _As(maker, PRIYANKA) as c:
            rate = await _rate_draft(c, 58.0)
            cr = await _propose(c, "rate_card", rate)
            # Under review, the draft's numbers can't change under the reviewer.
            payload = (await c.get(f"/api/v1/rate-library/{rate}")).json()["payload"]
            payload["global"]["labor_rate"] = 95.0
            r = await c.patch(f"/api/v1/rate-library/{rate}", json={"payload": payload})
            assert r.status_code == 409, r.text
            assert r.json()["detail"]["code"] == "under_review"
            assert r.json()["detail"]["message"] == (
                "This draft is waiting for review, so it can't be changed. An admin can reject the change "
                "request; then edit the draft and propose it again.")
        async with _As(maker, DANA) as c:
            r = await c.post(f"/api/v1/governance/change-requests/{cr}/approve")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["change_request"]["status"] == "approved"
            assert body["change_request"]["self_approved"] is False
            assert body["published_version"]["status"] == "published"
            assert body["published_version"]["payload"]["global"]["labor_rate"] == 58.0

            # The material catalog goes through the same review.
            r = await c.post("/api/v1/material-library", json={
                "name": "Q4 materials", "payload": {"material_prices": {"PA12 (Nylon 12)": 26.5}, "materials": {}}})
            mat = r.json()["id"]
        async with _As(maker, PRIYANKA) as c:
            mcr = await _propose(c, "material_catalog", mat, title="PA12 $26.50/kg")
        async with _As(maker, DANA) as c:
            r = await c.post(f"/api/v1/governance/change-requests/{mcr}/approve")
            assert r.status_code == 200, r.text
            assert r.json()["published_version"]["status"] == "published"
            assert r.json()["published_version"]["payload"]["material_prices"]["PA12 (Nylon 12)"] == 26.5
        approved = await _audit(maker, "governance.approved")
        assert [(a.detail_json or {}).get("self_approved") for a in approved] == [False, False]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_single_admin_org_self_approves_and_it_is_labelled(flags):
    engine, maker = await _tables()
    try:
        await _seed(maker, admins=(PRIYANKA,))
        async with _As(maker, PRIYANKA) as c:
            rate = await _rate_draft(c, 58.0)
            r = await c.post(f"/api/v1/rate-library/{rate}/publish", json={})
            assert r.status_code == 403, r.text
            assert r.json()["detail"]["message"].endswith(
                "You're your organization's only admin, so you approve it yourself and it's marked self-approved.")
            cr = await _propose(c, "rate_card", rate)
            r = await c.post(f"/api/v1/governance/change-requests/{cr}/approve")
            assert r.status_code == 200, r.text
            assert r.json()["change_request"]["self_approved"] is True
            assert r.json()["published_version"]["payload"]["global"]["labor_rate"] == 58.0
            listing = (await c.get("/api/v1/governance/change-requests")).json()
            assert listing["change_requests"][0]["self_approved"] is True
        [approved] = await _audit(maker, "governance.approved")
        assert approved.detail_json["self_approved"] is True
    finally:
        await engine.dispose()
