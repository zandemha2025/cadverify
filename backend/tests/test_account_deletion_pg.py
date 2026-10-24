"""Deleting a person's sign-in account, against real Postgres and a real object store.

Skipped unless DATABASE_URL points at Postgres migrated to head. The person has
a personal organization only they are in and is a member of a shared one. The
tests delete through the HTTP routes and prove: the personal organization goes
through the organization deletion path; the shared one keeps its parts; the
account can't sign in and holds nothing personal; billing keeps only the Stripe
reference (a live plan is cancelled first, and a Stripe failure deletes
nothing); the audit trail loses the person; and signing up again with the same
email starts from the free checks already used.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest
from sqlalchemy import text

from tests import test_data_deletion_pg as part_tests
from tests.test_data_deletion_pg import World, _act, _app, _count, _org, _seed_part, _user

stores = part_tests.stores  # the object-store fixture, shared with the part and organization tests

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not _PG, reason="requires live Postgres")]


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """The test clients share one address, so a limiter another test file
    switched on would carry its counts (5 deletes an hour) into these tests."""
    from src.auth.rate_limit import limiter

    limiter.reset()
    yield


@pytest.fixture
def stripe(monkeypatch):
    """Stripe as seen by the cancel call: records requests, can be made to fail."""
    from src.billing import stripe_client

    for name in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRO_PRICE_ID"):
        monkeypatch.setenv(name, f"test-{name.lower()}")
    calls: list[tuple[str, str, str | None]] = []
    state = {"fail": None}

    async def fake(method, path, data=None, *, idempotency_key=None):
        calls.append((method, path, idempotency_key))
        if state["fail"] is not None:
            raise stripe_client.StripeError(state["fail"], "api_error")
        return {"id": path.rsplit("/", 1)[-1], "status": "canceled"}

    monkeypatch.setattr(stripe_client, "stripe_request", fake)
    return {"calls": calls, "state": state}


async def _world(root) -> World:
    import src.db.engine as eng
    from src.db.models import (
        ApiKey, AuditLog, AuthIdentity, BillingAccount, CatalogPart, OrgInvite, ScimIdentity, TrialCheck, UsageEvent,
    )

    w = World(uuid.uuid4().hex[:10])
    w.parts_by_hash = {}
    async with eng.get_session_factory()() as s:
        await _org(s, w, "Mine")
        await _org(s, w, "Shop")
        me = await _user(s, w, "me", "Mine", "admin")
        await _user(s, w, "boss", "Shop", "admin")
        await s.execute(text("INSERT INTO memberships (id, org_id, user_id, org_role) VALUES (:id, :o, :u, 'member')"),
                        {"id": uuid.uuid4().hex, "o": w.orgs["Shop"], "u": me})
        await s.execute(text("UPDATE users SET full_name='Mia Example', phone='+15550100', password_hash='x', "
                             "google_sub=:g, signup_metadata='{\"company\": \"Mia Co\"}', "
                             "preferences='{\"length_unit\": \"in\"}' WHERE id=:u"), {"u": me, "g": f"g-{w.tag}"})
        mine = await _seed_part(s, root, w, "MINE", "Mine", "me")
        shop = await _seed_part(s, root, w, "SHOP", "Shop", "me")
        email = f"dd-{w.tag}-me@example.com"
        s.add_all([
            ApiKey(user_id=me, org_id=w.orgs["Mine"], name="laptop", prefix="aaaa1111", hmac_index=f"i1-{w.tag}",
                   secret_hash="x"),
            ApiKey(user_id=me, org_id=w.orgs["Shop"], name="ci", prefix="bbbb2222", hmac_index=f"i2-{w.tag}",
                   secret_hash="x"),
            BillingAccount(user_id=me, stripe_customer_id=f"cus_{w.tag}", stripe_subscription_id=f"sub_{w.tag}",
                           status="active"),
            TrialCheck(user_id=me, check_id="c1", file_hash="f" * 64, completed=True, operations={}),
            TrialCheck(user_id=me, check_id="c2", file_hash="e" * 64, completed=True, operations={}),
            CatalogPart(user_id=me, file_hash="d" * 64, state="counted"),
            AuthIdentity(provider="oidc", issuer=f"https://idp-{w.tag}", subject="s1", user_id=me, email_at_link=email),
            ScimIdentity(org_id=w.orgs["Shop"], user_id=me, external_id=f"ext-{w.tag}", org_role="member"),
            OrgInvite(org_id=w.orgs["Shop"], email=email, role="member", token_hash=f"t-{w.tag}",
                      expires_at=__import__("datetime").datetime(2030, 1, 1), created_by=w.users["boss"],
                      accepted_by=me),
            # The person's own action, from their browser.
            AuditLog(user_id=me, org_id=w.orgs["Shop"], user_email=email, action="analysis.created",
                     resource_type="analysis", resource_id=shop["analysis"], ip_address="198.51.100.4",
                     user_agent="Mozilla/5.0 mia"),
            # The admin's action naming the person, and someone whose email merely contains theirs.
            AuditLog(user_id=w.users["boss"], org_id=w.orgs["Shop"], user_email=f"dd-{w.tag}-boss@example.com",
                     action="org.invite_created", resource_type="invite", ip_address="203.0.113.9",
                     detail_json={"email": email.upper(), "other": f"x{email}", "role": "member"}),
            UsageEvent(user_id=me, org_id=w.orgs["Shop"], event_type="analysis", mesh_hash=shop["hash"], face_count=12),
            # A pilot request from the public form, before or without signing in.
            AuditLog(user_id=None, org_id=None, user_email=email, action="pilot.requested",
                     resource_type="pilot_request", resource_id=f"pr-{w.tag}", ip_address="192.0.2.8",
                     user_agent="Mozilla/5.0 form", detail_json={"company": "Mia Co", "what": "brackets"}),
        ])
        # Two-step sign-in on: a sealed authenticator secret and recovery-code hashes.
        await s.execute(text("INSERT INTO user_two_step (user_id, secret_sealed, enabled_at) "
                             "VALUES (:u, 'fernet:v1:sealed-secret', now())"), {"u": me})
        for n in range(3):
            await s.execute(text("INSERT INTO user_two_step_recovery_codes (user_id, code_hash) VALUES (:u, :h)"),
                            {"u": me, "h": f"hash-{w.tag}-{n}"})
        await s.commit()
    w.email = email
    w.mine, w.shop = mine, shop
    return w


async def _cleanup(w: World) -> None:
    import src.db.engine as eng
    from src.services.deleted_account_allowance import email_fingerprint

    async with eng.get_session_factory()() as s:
        ids = list(w.users.values())
        await s.execute(text("DELETE FROM deleted_account_allowances WHERE email_hmac = :h"),
                        {"h": email_fingerprint(w.email)})
        await s.execute(text("DELETE FROM data_deletions WHERE org_id = ANY(:o) OR requested_by = ANY(:u)"),
                        {"o": list(w.orgs.values()), "u": ids})
        await s.execute(text("DELETE FROM audit_log WHERE user_id = ANY(:u) OR org_id = ANY(:o) OR resource_id = :r"),
                        {"u": ids, "o": list(w.orgs.values()), "r": f"pr-{w.tag}"})
        orgs = (await s.execute(text("SELECT org_id FROM memberships WHERE user_id = ANY(:u)"), {"u": ids})).scalars().all()
        await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": list({*w.orgs.values(), *orgs})})
        await s.execute(text("DELETE FROM users WHERE id = ANY(:u) OR email_lower = :e"), {"u": ids, "e": w.email})
        await s.commit()
    await eng.dispose_engine()


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_deleting_an_account(stores, stripe):
    w = await _world(stores)
    me, mine_org, shop_org = w.users["me"], w.orgs["Mine"], w.orgs["Shop"]
    app = _app()
    try:
        async with _client(app) as client:
            _act(app, me)
            pv = await client.get("/api/v1/account/deletion-preview")
            assert pv.status_code == 200, pv.text
            p = pv.json()
            assert p["can_delete"] is True and p["blockers"] == [] and p["email"] == w.email
            assert [o["org_id"] for o in p["orgs_deleted"]] == [mine_org]
            assert p["orgs_deleted"][0]["will_remove"]["parts"] == 1
            assert [(o["org_id"], o["role"], o["members"]) for o in p["orgs_left"]] == [(shop_org, "member", 2)]
            assert p["api_keys"] == 2 and p["billing"]["cancels_now"] is True
            assert any("fingerprint of your email" in k for k in p["kept"])

            # An API key can't delete the account; the email must be typed.
            from src.auth.require_api_key import AuthedUser, require_api_key

            app.dependency_overrides[require_api_key] = lambda: AuthedUser(
                user_id=me, api_key_id=1, key_prefix="aaaa1111", role="analyst")
            r = await client.post("/api/v1/account/delete", json={"confirm_email": w.email})
            assert r.status_code == 403 and r.json()["detail"]["code"] == "browser_session_required"
            _act(app, me)
            r = await client.post("/api/v1/account/delete", json={"confirm_email": "someone@example.com"})
            assert r.status_code == 400 and r.json()["detail"]["code"] == "confirm_email_mismatch"
            assert stripe["calls"] == []

            r = await client.post("/api/v1/account/delete", json={"confirm_email": f"  {w.email.upper()} "})
            assert r.status_code == 200, r.text
            receipt = r.json()
            assert receipt["scope"] == "account" and receipt["target"] == str(me)
            assert receipt["status"] == "done", receipt
            assert receipt["removed"]["organizations_deleted"] == 1 and receipt["removed"]["organizations_left"] == 1
            assert receipt["removed"]["plan_cancelled"] is True and receipt["removed"]["free_checks_used"] == 2
            assert receipt["removed"]["free_catalog_parts_used"] == 1
            assert w.email not in str(receipt).lower() and "Mia" not in str(receipt)
            assert any("Stripe" in k for k in receipt["kept"])

            # Deleted already: a second try finds no account.
            assert (await client.post("/api/v1/account/delete", json={"confirm_email": w.email})).status_code == 404

        # The live plan was cancelled at Stripe, once, before anything else; the reference stays.
        assert [(m, path) for m, path, _ in stripe["calls"]] == [("DELETE", f"/v1/subscriptions/sub_{w.tag}")]
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u AND stripe_customer_id=:c "
                            "AND status='canceled'", u=me, c=f"cus_{w.tag}") == 1

        # The personal organization went through organization deletion; its files are gone.
        assert await _count("SELECT count(*) FROM organizations WHERE id=:o", o=mine_org) == 0
        assert await _count("SELECT count(*) FROM analyses WHERE org_id=:o", o=mine_org) == 0
        assert not (stores / "objects" / "source-artifacts" / mine_org).exists()
        assert await _count("SELECT count(*) FROM audit_log WHERE action='organization.deleted' AND resource_id=:o "
                            "AND user_email='deleted account'", o=mine_org) == 1
        # The shared organization keeps what the person made there, and its other admin.
        assert await _count("SELECT count(*) FROM analyses WHERE org_id=:o AND mesh_hash=:h", o=shop_org,
                            h=w.shop["hash"]) == 1
        assert (stores / "objects" / "source-artifacts" / shop_org / w.shop["hash"]).exists()
        assert await _count("SELECT count(*) FROM memberships WHERE org_id=:o", o=shop_org) == 1

        # Nothing personal is left on the account, and it can't sign in.
        async with __import__("src.db.engine", fromlist=["x"]).get_session_factory()() as s:
            row = (await s.execute(text(
                "SELECT email, email_lower, full_name, phone, password_hash, google_sub, signup_metadata, preferences, "
                "is_active, session_version, current_org_id, role FROM users WHERE id=:u"), {"u": me})).one()
        assert row.email == f"deleted-account-{me}@deleted.invalid" == row.email_lower
        assert (row.full_name, row.phone, row.password_hash, row.google_sub, row.current_org_id) == (None,) * 5
        assert row.signup_metadata == {} and row.preferences == {}
        assert row.is_active is False and row.session_version == 1 and row.role == "viewer"
        for table in ("memberships", "auth_identities", "scim_identities", "trial_checks", "catalog_parts",
                      "user_two_step", "user_two_step_recovery_codes"):
            assert await _count(f"SELECT count(*) FROM {table} WHERE user_id=:u", u=me) == 0, table
        assert receipt["removed"]["two_step_removed"] is True
        assert await _count("SELECT count(*) FROM api_keys WHERE user_id=:u AND revoked_at IS NULL", u=me) == 0
        assert await _count("SELECT count(*) FROM org_invites WHERE lower(email)=:e", e=w.email) == 0
        from src.auth.models import lookup_session_user

        session_row = await lookup_session_user(me)
        assert session_row is not None and session_row.is_active is False

        # Usage counts stay, without the file's fingerprint.
        assert await _count("SELECT count(*) FROM usage_events WHERE user_id=:u", u=me) >= 1
        assert await _count("SELECT count(*) FROM usage_events WHERE user_id=:u AND mesh_hash IS NOT NULL", u=me) == 0

        # The audit trail loses the person: no email, network address or browser.
        assert await _count("SELECT count(*) FROM audit_log WHERE lower(user_email)=:e", e=w.email) == 0
        assert await _count("SELECT count(*) FROM audit_log WHERE lower(detail_json::text) LIKE :e "
                            "AND detail_json::text NOT LIKE :x", e=f'%"{w.email}"%', x=f"%x{w.email}%") == 0
        assert await _count("SELECT count(*) FROM audit_log WHERE user_id=:u AND (ip_address IS NOT NULL "
                            "OR user_agent IS NOT NULL OR user_email <> 'deleted account')", u=me) == 0
        invite = await _count("SELECT count(*) FROM audit_log WHERE action='org.invite_created' AND org_id=:o "
                              "AND detail_json->>'email' = 'redacted' AND detail_json->>'other' = :x "
                              "AND ip_address = '203.0.113.9'", o=shop_org, x=f"x{w.email}")
        assert invite == 1  # the admin's own address stays; a longer email containing theirs is untouched
        assert await _count("SELECT count(*) FROM audit_log WHERE action='pilot.requested' AND resource_id=:r "
                            "AND user_email='deleted account' AND ip_address IS NULL AND user_agent IS NULL "
                            "AND detail_json->>'company' = 'Mia Co'", r=f"pr-{w.tag}") == 1
        assert await _count("SELECT count(*) FROM audit_log WHERE action='account.deleted' AND user_id=:u "
                            "AND detail_json->>'deletion_id' = :d", u=me, d=receipt["id"]) == 1

        # The free allowance outlives the account only as a fingerprint.
        from src.services.deleted_account_allowance import email_fingerprint

        assert await _count("SELECT count(*) FROM deleted_account_allowances WHERE email_hmac=:h AND checks_used=2 "
                            "AND catalog_parts_used=1", h=email_fingerprint(w.email)) == 1
        assert await _count("SELECT count(*) FROM deleted_account_allowances WHERE email_hmac LIKE :e",
                            e="%@%") == 0
    finally:
        await _cleanup(w)


async def test_the_only_admin_of_a_shared_org_is_refused_until_they_hand_it_over(stores, stripe):
    w = await _world(stores)
    me, shop = w.users["me"], w.orgs["Shop"]
    import src.db.engine as eng

    async with eng.get_session_factory()() as s:
        await s.execute(text("UPDATE memberships SET org_role='admin' WHERE org_id=:o AND user_id=:u"), {"o": shop, "u": me})
        await s.execute(text("UPDATE memberships SET org_role='member' WHERE org_id=:o AND user_id=:u"),
                        {"o": shop, "u": w.users["boss"]})
        await s.commit()
    app = _app()
    try:
        async with _client(app) as client:
            _act(app, me)
            p = (await client.get("/api/v1/account/deletion-preview")).json()
            assert p["can_delete"] is False
            (blocker,) = p["blockers"]
            assert blocker["org_id"] == shop and blocker["members"] == 2
            assert "only admin" in blocker["message"] and "make another member an admin" in blocker["message"]
            r = await client.post("/api/v1/account/delete", json={"confirm_email": w.email})
            assert r.status_code == 409 and r.json()["detail"]["code"] == "account_delete_blocked"
            assert r.json()["detail"]["blockers"][0]["org_id"] == shop
            # Nothing changed: not even Stripe was asked.
            assert stripe["calls"] == []
            assert await _count("SELECT count(*) FROM users WHERE id=:u AND is_active", u=me) == 1
            assert await _count("SELECT count(*) FROM organizations WHERE id=:o", o=w.orgs["Mine"]) == 1

            # Another admin, and it goes through.
            async with eng.get_session_factory()() as s:
                await s.execute(text("UPDATE memberships SET org_role='admin' WHERE org_id=:o AND user_id=:u"),
                                {"o": shop, "u": w.users["boss"]})
                await s.commit()
            r = await client.post("/api/v1/account/delete", json={"confirm_email": w.email})
            assert r.status_code == 200, r.text
    finally:
        await _cleanup(w)


async def test_a_stripe_failure_deletes_nothing(stores, stripe):
    w = await _world(stores)
    me = w.users["me"]
    stripe["state"]["fail"] = 500
    app = _app()
    try:
        async with _client(app) as client:
            _act(app, me)
            r = await client.post("/api/v1/account/delete", json={"confirm_email": w.email})
            assert r.status_code == 503 and r.json()["detail"]["code"] == "billing_cancel_failed"
            assert "nothing was deleted" in r.json()["detail"]["message"]
        assert len(stripe["calls"]) == 1
        assert await _count("SELECT count(*) FROM users WHERE id=:u AND is_active AND email=:e", u=me, e=w.email) == 1
        assert await _count("SELECT count(*) FROM organizations WHERE id=:o", o=w.orgs["Mine"]) == 1
        assert await _count("SELECT count(*) FROM trial_checks WHERE user_id=:u", u=me) == 2
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u AND status='active'", u=me) == 1
        from src.services.deleted_account_allowance import email_fingerprint

        assert await _count("SELECT count(*) FROM deleted_account_allowances WHERE email_hmac=:h",
                            h=email_fingerprint(w.email)) == 0
    finally:
        await _cleanup(w)


async def test_signing_up_again_starts_from_the_free_checks_already_used(stores, stripe):
    import src.db.engine as eng
    from src.auth import catalog_allowance, validation_caps
    from src.services.deleted_account_allowance import carry_over, email_fingerprint

    w = await _world(stores)
    app = _app()
    new_id = None
    try:
        async with _client(app) as client:
            _act(app, w.users["me"])
            assert (await client.post("/api/v1/account/delete", json={"confirm_email": w.email})).status_code == 200
        # The same person signs up again; the address differs only by a +tag and case.
        local, domain = w.email.split("@")
        again = f"{local.upper()}+again@{domain}"
        async with eng.get_session_factory()() as s:
            new_id = int((await s.execute(text(
                "INSERT INTO users (email, email_lower, role, auth_provider, plan) "
                "VALUES (:e, :l, 'analyst', 'password', 'trial') RETURNING id"),
                {"e": again, "l": w.email})).scalar_one())
            await s.commit()
        usage = await validation_caps.user_trial_usage(new_id)
        assert usage["used"] == 2, usage
        assert usage["remaining"] == max(0, usage["cap"] - 2)
        assert (await catalog_allowance.catalog_usage(new_id))["used"] == 1
        # Reading doesn't consume the ledger; the first committed use carries it over, once.
        async with eng.get_session_factory()() as s:
            assert await carry_over(s, new_id, w.email) is True
            await s.commit()
        async with eng.get_session_factory()() as s:
            assert await carry_over(s, new_id, w.email) is False
        assert await _count("SELECT count(*) FROM deleted_account_allowances WHERE email_hmac=:h",
                            h=email_fingerprint(w.email)) == 0
        assert (await validation_caps.user_trial_usage(new_id))["used"] == 2
        assert (await catalog_allowance.catalog_usage(new_id))["used"] == 1
        # The carried checks are dated at the deletion, so a Pro period that starts later doesn't count them.
        assert await _count("SELECT count(*) FROM trial_checks WHERE user_id=:u AND file_hash LIKE 'carried-check:%' "
                            "AND created_at < now() - interval '0 seconds'", u=new_id) == 2
    finally:
        if new_id is not None:
            async with eng.get_session_factory()() as s:
                await s.execute(text("DELETE FROM users WHERE id=:u"), {"u": new_id})
                await s.commit()
        await _cleanup(w)


async def test_the_crm_page_moves_to_notions_trash(monkeypatch):
    from src.services import customer_sync

    monkeypatch.delenv("NOTION_INTEGRATION_TOKEN", raising=False)
    assert await customer_sync.archive_notion_user(7, None) is False  # no CRM configured here

    monkeypatch.setenv("NOTION_INTEGRATION_TOKEN", "secret-test")
    monkeypatch.setenv("NOTION_CRM_DATA_SOURCE_ID", str(uuid.UUID(int=1)))
    page = str(uuid.UUID(int=99))
    seen: list[tuple[str, str, bytes]] = []
    status = {"patch": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content))
        if request.method == "POST":
            return httpx.Response(200, json={"results": [{"id": page}]})
        return httpx.Response(status["patch"], json={"id": page})

    monkeypatch.setattr(customer_sync, "_notion_client", lambda token: httpx.AsyncClient(
        base_url="https://api.notion.com", transport=httpx.MockTransport(handler)))
    assert await customer_sync.archive_notion_user(7, None) is True
    assert [m for m, _, _ in seen] == ["POST", "PATCH", "PATCH"]
    assert b"scalecad-user-7" in seen[0][2] and seen[1][1] == seen[2][1] == f"/v1/pages/{page}"
    # it-13: the personal fields are blanked before the page goes to the trash (Notion's
    # API can't delete a page), so the trashed copy keeps only the Account ID.
    erased = __import__("json").loads(seen[1][2])["properties"]
    assert erased["Email"] == {"email": None} and erased["Phone"] == {"phone_number": None}
    assert erased["Contact Person"] == {"rich_text": []} and erased["City"] == {"rich_text": []}
    assert erased["Company"]["title"][0]["text"]["content"] == "Deleted account"
    assert "Account ID" not in erased
    assert __import__("json").loads(seen[2][2]) == {"in_trash": True}
    seen.clear()
    status["patch"] = 404  # already gone
    assert await customer_sync.archive_notion_user(7, page) is True
    assert [m for m, _, _ in seen] == ["PATCH"]
    status["patch"] = 502
    with pytest.raises(httpx.HTTPStatusError):  # retried by the deletion's worker steps
        await customer_sync.archive_notion_user(7, page)


async def test_a_webhook_during_the_cancel_doesnt_block_the_delete(stores, monkeypatch):
    """Stripe's customer.subscription.deleted can arrive before it answers the cancel.

    The webhook locks the billing row and then the account; no lock of the
    deletion may be held while Stripe is called, or the two wait on each other.
    """
    import asyncio
    import os

    import asyncpg

    from src.services import account_deletion_service as ads

    w = await _world(stores)
    me = w.users["me"]

    async def cancel_with_webhook(sub_id: str, key: str) -> None:
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            async with conn.transaction():
                await asyncio.wait_for(
                    conn.execute("UPDATE billing_accounts SET status='canceled' WHERE stripe_subscription_id=$1", sub_id),
                    timeout=5,
                )
                await asyncio.wait_for(conn.execute("UPDATE users SET plan='trial' WHERE id=$1", me), timeout=5)
        finally:
            await conn.close()

    monkeypatch.setattr(ads, "cancel_subscription_at_stripe", cancel_with_webhook)
    app = _app()
    try:
        async with _client(app) as client:
            _act(app, me)
            r = await client.post("/api/v1/account/delete", json={"confirm_email": w.email})
            assert r.status_code == 200, r.text
            assert r.json()["removed"]["plan_cancelled"] is True
        assert await _count("SELECT count(*) FROM users WHERE id=:u AND is_active", u=me) == 0
        assert await _count("SELECT count(*) FROM billing_accounts WHERE user_id=:u AND status='canceled'", u=me) == 1
    finally:
        await _cleanup(w)
