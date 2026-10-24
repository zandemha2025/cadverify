"""The admin who wrote a draft can't approve it while another admin can (R2 F3).

governance_service.approve used to refuse self-approval only when the reviewer
was the change request's PROPOSER. Any org member may propose any draft, so an
admin could write the numbers, have a member propose them, and publish them
themselves: the "another admin approves it" rule (ce-13, C2) was bypassed and
the request was not even labelled self-approved. Approve now also refuses the
draft's author (``created_by``) and its last editor (``edited_by``, 0065), for
the rate card, supplier rate profiles and the material catalog alike; a
single-admin org still approves its own drafts, recorded as self-approved.

Skipped unless DATABASE_URL points at Postgres migrated to head.
"""
from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgresql"), reason="needs Postgres"
    ),
]

LIBRARIES = [
    ("rate_card", "/api/v1/rate-library", {"name": "Author's rates", "change_note": "new labour rate"}),
    ("shop_profile", "/api/v1/shop-library", {"slug": "midway", "name": "Midway", "change_note": "new rates"}),
    ("material_catalog", "/api/v1/material-library", {"name": "Author's prices", "change_note": "new prices"}),
]


def _app():
    from fastapi import FastAPI

    from src.api.governance import router as gov_router
    from src.api.material_library import router as material_router
    from src.api.rate_library import router as rate_router
    from src.api.shop_library import router as shop_router
    from src.auth.rate_limit import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(rate_router, prefix="/api/v1/rate-library")
    app.include_router(shop_router, prefix="/api/v1/shop-library")
    app.include_router(material_router, prefix="/api/v1/material-library")
    app.include_router(gov_router, prefix="/api/v1/governance")
    return app


def _act_as(app, uid: int) -> None:
    from src.auth.require_api_key import AuthedUser, require_api_key

    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=uid, api_key_id=0, key_prefix="session", role="analyst"
    )


@pytest.fixture
def real_membership_lookup(monkeypatch):
    import src.auth.models as models
    import src.auth.rbac as rbac

    monkeypatch.setattr(rbac, "lookup_org_membership", models.lookup_org_membership)


async def _org(roles: tuple[tuple[str, str], ...]):
    from sqlalchemy import text
    from ulid import ULID

    import src.db.engine as eng

    tag = uuid.uuid4().hex[:8]
    org = str(ULID())
    async with eng.get_session_factory()() as s:
        await s.execute(text("INSERT INTO organizations (id, name, slug, created_at) VALUES (:i, :n, :s, now())"),
                        {"i": org, "n": f"Gov {tag}", "s": f"gov-{tag}"})
        uids = []
        for label, role in roles:
            e = f"gov-{tag}-{label}@example.com"
            uid = int((await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, current_org_id) "
                "VALUES (:e, :e, 'analyst', 'password', :o) RETURNING id"), {"e": e, "o": org})).first()[0])
            await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role, created_at) "
                                 "VALUES (:i, :o, :u, :r, now())"),
                            {"i": str(ULID()), "o": org, "u": uid, "r": role})
            uids.append(uid)
        await s.commit()
    return org, uids


def _invalidate(org: str) -> None:
    from src.services import material_library_service, rate_library_service, shop_library_service

    for lib in (rate_library_service, shop_library_service, material_library_service):
        invalidate = getattr(lib, "invalidate", None)
        if invalidate is not None:
            invalidate(org)


@pytest.mark.parametrize("asset_type,prefix,body", LIBRARIES, ids=[x[0] for x in LIBRARIES])
async def test_draft_author_cannot_approve_when_another_admin_exists(real_membership_lookup, asset_type, prefix, body):
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    org, (author, other_admin, member) = await _org((("author", "admin"), ("other_admin", "admin"),
                                                     ("member", "member")))
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            _act_as(app, author)
            r = await ac.post(prefix, json=body)
            assert r.status_code == 200, r.text
            draft = r.json()["id"]
            assert r.json()["created_by"] == author

            # A member proposes the author's draft.
            _act_as(app, member)
            r = await ac.post("/api/v1/governance/change-requests",
                              json={"asset_type": asset_type, "target_version_id": draft, "title": "Rates"})
            assert r.status_code == 200, r.text
            cr = r.json()["id"]

            _act_as(app, author)
            r = await ac.post(f"/api/v1/governance/change-requests/{cr}/approve", json={})
            assert r.status_code == 403, r.text
            assert r.json()["detail"]["code"] == "self_approval"
            assert r.json()["detail"]["message"] == (
                "You wrote this draft, so another admin approves it. Your organization has 1 other admin.")
            # Still open, still a draft.
            listed = (await ac.get("/api/v1/governance/change-requests")).json()["change_requests"]
            assert [x["status"] for x in listed if x["id"] == cr] == ["proposed"]

            _act_as(app, other_admin)
            r = await ac.post(f"/api/v1/governance/change-requests/{cr}/approve", json={})
            assert r.status_code == 200, r.text
            assert r.json()["change_request"]["self_approved"] is False
    finally:
        _invalidate(org)
        await eng.dispose_engine()


async def test_the_last_editor_cannot_approve_either(real_membership_lookup):
    """Admin A writes the draft, admin B edits it, a member proposes it: neither
    A nor B may approve it while admin C can; C approves it."""
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    org, (writer, editor, third, member) = await _org((("writer", "admin"), ("editor", "admin"),
                                                       ("third", "admin"), ("member", "member")))
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            _act_as(app, writer)
            draft = (await ac.post("/api/v1/rate-library", json={"name": "Q4 rates"})).json()["id"]
            _act_as(app, editor)
            r = await ac.patch(f"/api/v1/rate-library/{draft}", json={"change_note": "labour $58/h"})
            assert r.status_code == 200, r.text
            assert r.json()["created_by"] == writer and r.json()["edited_by"] == editor
            _act_as(app, member)
            cr = (await ac.post("/api/v1/governance/change-requests",
                                json={"asset_type": "rate_card", "target_version_id": draft})).json()["id"]

            _act_as(app, editor)
            r = await ac.post(f"/api/v1/governance/change-requests/{cr}/approve", json={})
            assert r.status_code == 403 and r.json()["detail"]["message"] == (
                "You last edited this draft, so another admin approves it. Your organization has 2 other admins."
            ), r.text
            _act_as(app, writer)
            r = await ac.post(f"/api/v1/governance/change-requests/{cr}/approve", json={})
            assert r.status_code == 403 and r.json()["detail"]["message"].startswith("You wrote this draft"), r.text

            _act_as(app, third)
            r = await ac.post(f"/api/v1/governance/change-requests/{cr}/approve", json={})
            assert r.status_code == 200, r.text
            assert r.json()["change_request"]["self_approved"] is False
    finally:
        _invalidate(org)
        await eng.dispose_engine()


async def test_single_admin_org_still_approves_its_own_draft(real_membership_lookup):
    from httpx import ASGITransport, AsyncClient

    import src.db.engine as eng

    org, (admin, member) = await _org((("admin", "admin"), ("member", "member")))
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            _act_as(app, admin)
            draft = (await ac.post("/api/v1/rate-library", json={"name": "Only admin"})).json()["id"]
            _act_as(app, member)
            cr = (await ac.post("/api/v1/governance/change-requests",
                                json={"asset_type": "rate_card", "target_version_id": draft})).json()["id"]
            _act_as(app, admin)
            r = await ac.post(f"/api/v1/governance/change-requests/{cr}/approve", json={})
            assert r.status_code == 200, r.text
            assert r.json()["change_request"]["status"] == "approved"
            # A member proposed it, but the only admin wrote it: no second admin saw it.
            assert r.json()["change_request"]["self_approved"] is True
            listed = (await ac.get("/api/v1/governance/change-requests")).json()["change_requests"]
            assert [x["self_approved"] for x in listed if x["id"] == cr] == [True]
    finally:
        _invalidate(org)
        await eng.dispose_engine()
