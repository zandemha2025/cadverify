"""Deleting an organization ends the deleting admin's paid plan (it-24), live Postgres.

The dialog says so beforehand (the preview carries the admin's plan), the
cancel happens at Stripe before anything is deleted, a Stripe failure deletes
nothing, the admin can keep the plan, and members land in a workspace named
for them, never after the company.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from tests.test_data_deletion_pg import _act, _app, _cleanup, _count, _world, stores  # noqa: F401

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]


async def _live_plan(w, label: str) -> None:
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(
            text("INSERT INTO billing_accounts (user_id, stripe_customer_id, stripe_subscription_id, status) "
                 "VALUES (:u, :c, :sub, 'active')"),
            {"u": w.users[label], "c": f"cus_{w.tag}_{label}", "sub": f"sub_{w.tag}_{label}"},
        )
        await s.commit()


async def _drop_billing(w) -> None:
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(text("DELETE FROM billing_accounts WHERE user_id = ANY(:u)"), {"u": list(w.users.values())})
        await s.commit()


async def test_deleting_the_org_cancels_the_admins_pro_plan_first(stores, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from src.services import account_deletion_service as ads

    w = await _world(stores)
    await _live_plan(w, "admin")
    await _live_plan(w, "colleague")
    cancelled: list[tuple[str, str]] = []

    async def fake_cancel(sub_id: str, key: str) -> None:
        cancelled.append((sub_id, key))

    monkeypatch.setattr(ads, "cancel_subscription_at_stripe", fake_cancel)
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["admin"])
            pv = (await client.get("/api/v1/orgs/current/deletion-preview")).json()
            assert pv["billing"]["cancels_now"] is True
            r = await client.post("/api/v1/orgs/current/delete", json={"confirm_name": f"Acme A {w.tag}"})
            assert r.status_code == 200, r.text
            assert r.json()["removed"]["pro_plan_cancelled"] is True
        # Only the deleting admin's subscription; a colleague's own plan is theirs.
        assert [c[0] for c in cancelled] == [f"sub_{w.tag}_admin"]
        assert cancelled[0][1].startswith("org-delete-")
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u AND status='canceled'",
                            u=w.users["admin"]) == 1
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u AND status='active'",
                            u=w.users["colleague"]) == 1
        # Members left without an org land in their own workspace, not a company-named org.
        names = await _count(
            "SELECT count(*) FROM organizations o JOIN users u ON u.current_org_id = o.id "
            "WHERE u.id = ANY(:u) AND o.is_personal AND o.name LIKE '%''s workspace'",
            u=[w.users[k] for k in ("colleague", "admin", "viewer")],
        )
        assert names == 3
    finally:
        await _drop_billing(w)
        await _cleanup(w)


async def test_a_stripe_failure_deletes_nothing_and_keep_plan_skips_the_cancel(stores, monkeypatch):
    from fastapi import HTTPException
    from httpx import ASGITransport, AsyncClient

    from src.services import account_deletion_service as ads

    w = await _world(stores)
    await _live_plan(w, "admin")

    async def failing(sub_id: str, key: str) -> None:
        raise HTTPException(status_code=503, detail={"code": "billing_cancel_failed", "message": "Stripe down."})

    monkeypatch.setattr(ads, "cancel_subscription_at_stripe", failing)
    app = _app()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            _act(app, w.users["admin"])
            r = await client.post("/api/v1/orgs/current/delete", json={"confirm_name": f"Acme A {w.tag}"})
            assert r.status_code == 503
            assert await _count("SELECT count(*) FROM organizations WHERE id=:o", o=w.orgs["A"]) == 1
            r = await client.post("/api/v1/orgs/current/delete",
                                  json={"confirm_name": f"Acme A {w.tag}", "keep_plan": True})
            assert r.status_code == 200, r.text
            assert r.json()["removed"]["pro_plan_cancelled"] is False
        assert await _count("SELECT count(*) FROM organizations WHERE id=:o", o=w.orgs["A"]) == 0
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u AND status='active'",
                            u=w.users["admin"]) == 1
    finally:
        await _drop_billing(w)
        await _cleanup(w)
