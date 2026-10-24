"""Self-serve Pro billing: Checkout, portal and the signed Stripe webhook.

Runs against a real PostgreSQL schema (DATABASE_URL); Stripe is mocked with
respx. Each test creates and drops its own schema.
"""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api import billing
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.billing import stripe_client
from src.db.models import BillingAccount, BillingEvent

STRIPE = "https://api.stripe.com"
WHSEC = "whsec_test_secret"
PRICE = "price_pro_test"
NOW = int(time.time())


def _sub(sub_id="sub_1", customer="cus_1", status="active", price=PRICE):
    return {
        "id": sub_id, "object": "subscription", "customer": customer, "status": status,
        "items": {"data": [{"price": {"id": price}, "current_period_start": NOW - 60,
                            "current_period_end": NOW + 30 * 86400}]},
    }


def _signed(event: dict, secret: str = WHSEC, ts: int | None = None) -> tuple[bytes, str]:
    payload = json.dumps(event).encode()
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, f"t={ts},v1={sig}"


@pytest_asyncio.fixture
async def db(monkeypatch):
    url = os.environ.get("DATABASE_URL", "")
    assert url.startswith("postgresql"), "Set DATABASE_URL to local/CI PostgreSQL to test billing."
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "billing_test_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE users (id bigint PRIMARY KEY, plan text NOT NULL, email text NOT NULL)"))
            await connection.run_sync(BillingAccount.__table__.create)
            await connection.run_sync(BillingEvent.__table__.create)
            await connection.execute(text(
                "INSERT INTO users VALUES (1, 'trial', 'buyer@acme-aero.com'), (2, 'pilot', 'ops@acme-aero.com'), "
                "(3, 'trial', 'other@acme-aero.com')"
            ))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(billing, "get_session_factory", lambda: factory)
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WHSEC)
        monkeypatch.setenv("STRIPE_PRO_PRICE_ID", PRICE)
        monkeypatch.setenv("DASHBOARD_ORIGIN", "https://app.example.test")
        monkeypatch.delenv("STRIPE_API_BASE", raising=False)
        monkeypatch.setattr(limiter, "enabled", False)
        yield factory
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


def _client(user: AuthedUser) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(billing.router, prefix="/api/v1/billing")
    app.include_router(billing.webhook_router, prefix="/billing")
    app.dependency_overrides[require_api_key] = lambda: user
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _session_user(user_id: int = 1) -> AuthedUser:
    return AuthedUser(user_id=user_id, api_key_id=0, key_prefix="session")


async def _plan(db, user_id: int) -> str:
    async with db() as session:
        return (await session.execute(text("SELECT plan FROM users WHERE id = :id"), {"id": user_id})).scalar_one()


@pytest.mark.asyncio
@respx.mock
async def test_checkout_creates_one_customer_and_a_subscription_session(db):
    customers = respx.post(f"{STRIPE}/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    sessions = respx.post(f"{STRIPE}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}))
    async with _client(_session_user()) as client:
        first = await client.post("/api/v1/billing/checkout")
        second = await client.post("/api/v1/billing/checkout")
        status = await client.get("/api/v1/billing")
    assert first.status_code == 200, first.text
    assert first.json() == {"url": "https://checkout.stripe.com/c/pay/cs_1"}
    assert second.status_code == 200
    assert customers.call_count == 1  # reused on the second click
    assert customers.calls[0].request.headers["Idempotency-Key"] == "scalecad-customer-1"
    assert customers.calls[0].request.headers["Authorization"] == "Bearer sk_test_123"
    form = parse_qs(sessions.calls[0].request.content.decode())
    assert form["mode"] == ["subscription"]
    assert form["customer"] == ["cus_1"]
    assert form["client_reference_id"] == ["1"]
    assert form["line_items[0][price]"] == [PRICE]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["success_url"] == ["https://app.example.test/verify?upgraded=1"]
    assert form["cancel_url"] == ["https://app.example.test/pricing?checkout=cancelled"]
    assert status.json()["checkout_available"] is True and status.json()["manage_available"] is True


@pytest.mark.asyncio
@respx.mock
async def test_checkout_and_portal_return_to_the_v4_app_only_when_asked(db):
    sessions = respx.post(f"{STRIPE}/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}))
    respx.post(f"{STRIPE}/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_1"}))
    portal = respx.post(f"{STRIPE}/v1/billing_portal/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/x"}))
    async with _client(_session_user()) as client:
        v4 = await client.post("/api/v1/billing/checkout", json={"return_to": "app"})
        legacy = await client.post("/api/v1/billing/checkout", json={})
        bad = await client.post("/api/v1/billing/checkout", json={"return_to": "https://evil.example"})
        portal_v4 = await client.post("/api/v1/billing/portal", json={"return_to": "app"})
        portal_legacy = await client.post("/api/v1/billing/portal")
    assert v4.status_code == 200 and legacy.status_code == 200, (v4.text, legacy.text)
    assert bad.status_code == 422  # only the two fixed destinations exist
    first = parse_qs(sessions.calls[0].request.content.decode())
    assert first["success_url"] == ["https://app.example.test/app?upgraded=1"]
    assert first["cancel_url"] == ["https://app.example.test/app/account/billing?checkout=cancelled"]
    second = parse_qs(sessions.calls[1].request.content.decode())
    assert second["success_url"] == ["https://app.example.test/verify?upgraded=1"]
    assert second["cancel_url"] == ["https://app.example.test/pricing?checkout=cancelled"]
    assert sessions.call_count == 2
    assert portal_v4.status_code == 200 and portal_legacy.status_code == 200
    assert parse_qs(portal.calls[0].request.content.decode())["return_url"] == ["https://app.example.test/app/account/billing"]
    assert parse_qs(portal.calls[1].request.content.decode())["return_url"] == ["https://app.example.test/history"]


@pytest.mark.asyncio
@respx.mock
async def test_checkout_refuses_api_keys_pilots_and_missing_configuration(db, monkeypatch):
    respx.post(f"{STRIPE}/v1/customers").mock(return_value=httpx.Response(200, json={"id": "cus_x"}))
    async with _client(AuthedUser(user_id=1, api_key_id=9, key_prefix="cv_live_abc")) as client:
        denied = await client.post("/api/v1/billing/checkout")
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "browser_session_required"
    async with _client(_session_user(2)) as client:
        pilot = await client.post("/api/v1/billing/checkout")
    assert pilot.status_code == 409 and pilot.json()["detail"]["code"] == "plan_already_included"
    monkeypatch.delenv("STRIPE_PRO_PRICE_ID")
    async with _client(_session_user()) as client:
        off = await client.post("/api/v1/billing/checkout")
        status = await client.get("/api/v1/billing")
    assert off.status_code == 503 and off.json()["detail"]["code"] == "billing_unavailable"
    assert status.json()["checkout_available"] is False


@pytest.mark.asyncio
@respx.mock
async def test_checkout_reports_stripe_failure_without_leaking_detail(db):
    respx.post(f"{STRIPE}/v1/customers").mock(return_value=httpx.Response(401, json={"error": {"code": "api_key_expired", "message": "sk_test_123 expired"}}))
    async with _client(_session_user()) as client:
        response = await client.post("/api/v1/billing/checkout")
    assert response.status_code == 503
    assert "sk_test" not in response.text and response.json()["detail"]["code"] == "billing_unavailable"


async def _seed_account(db, user_id=1, customer="cus_1"):
    async with db() as session, session.begin():
        session.add(BillingAccount(user_id=user_id, stripe_customer_id=customer, status="none"))


@pytest.mark.asyncio
@respx.mock
async def test_webhook_upgrades_on_payment_and_downgrades_on_cancel(db):
    await _seed_account(db)
    route = respx.get(f"{STRIPE}/v1/subscriptions/sub_1").mock(return_value=httpx.Response(200, json=_sub()))
    completed = {"id": "evt_1", "type": "checkout.session.completed",
                 "data": {"object": {"id": "cs_1", "customer": "cus_1", "subscription": "sub_1"}}}
    async with _client(_session_user()) as client:
        payload, sig = _signed(completed)
        response = await client.post("/billing/stripe-webhook", content=payload, headers={"stripe-signature": sig})
        assert response.status_code == 200 and response.json()["handled"] is True
        assert await _plan(db, 1) == "pro"
        async with db() as session:
            account = await session.get(BillingAccount, 1)
        assert (account.status, account.stripe_subscription_id) == ("active", "sub_1")
        assert int(account.current_period_start.timestamp()) == NOW - 60

        # Stripe retries deliver the same event again: applied once.
        replay = await client.post("/billing/stripe-webhook", content=payload, headers={"stripe-signature": sig})
        assert replay.json().get("duplicate") is True and route.call_count == 2

        # The event body says "updated" but Stripe's current state is canceled.
        route.mock(return_value=httpx.Response(200, json=_sub(status="canceled")))
        updated = {"id": "evt_2", "type": "customer.subscription.updated", "data": {"object": _sub()}}
        payload, sig = _signed(updated)
        response = await client.post("/billing/stripe-webhook", content=payload, headers={"stripe-signature": sig})
        assert response.status_code == 200
    assert await _plan(db, 1) == "trial"


@pytest.mark.asyncio
@respx.mock
async def test_webhook_never_touches_pilots_other_prices_or_unknown_customers(db):
    await _seed_account(db, user_id=2, customer="cus_pilot")
    await _seed_account(db, user_id=3, customer="cus_other")
    respx.get(f"{STRIPE}/v1/subscriptions/sub_p").mock(return_value=httpx.Response(200, json=_sub("sub_p", "cus_pilot", "canceled")))
    respx.get(f"{STRIPE}/v1/subscriptions/sub_o").mock(return_value=httpx.Response(200, json=_sub("sub_o", "cus_other", price="price_other")))
    respx.get(f"{STRIPE}/v1/subscriptions/sub_u").mock(return_value=httpx.Response(200, json=_sub("sub_u", "cus_unknown")))
    async with _client(_session_user()) as client:
        for event_id, sub in (("evt_p", "sub_p"), ("evt_o", "sub_o"), ("evt_u", "sub_u")):
            payload, sig = _signed({"id": event_id, "type": "customer.subscription.updated", "data": {"object": {"id": sub}}})
            response = await client.post("/billing/stripe-webhook", content=payload, headers={"stripe-signature": sig})
            assert response.status_code == 200, response.text
        # Events Pro billing doesn't use are acknowledged and ignored.
        payload, sig = _signed({"id": "evt_i", "type": "invoice.paid", "data": {"object": {"id": "in_1"}}})
        ignored = await client.post("/billing/stripe-webhook", content=payload, headers={"stripe-signature": sig})
    assert ignored.json()["handled"] is False
    assert await _plan(db, 2) == "pilot"
    assert await _plan(db, 3) == "trial"
    async with db() as session:
        assert (await session.get(BillingAccount, 3)).status == "not_pro"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_stale_and_missing_signatures(db):
    event = {"id": "evt_bad", "type": "checkout.session.completed", "data": {"object": {}}}
    async with _client(_session_user()) as client:
        payload, _ = _signed(event)
        _, wrong = _signed(event, secret="whsec_other")
        _, stale = _signed(event, ts=int(time.time()) - 3600)
        for header in (wrong, stale, None, "t=abc,v1=00"):
            headers = {"stripe-signature": header} if header else {}
            response = await client.post("/billing/stripe-webhook", content=payload, headers=headers)
            assert response.status_code == 400, header
    async with db() as session:
        assert (await session.execute(text("SELECT count(*) FROM billing_events"))).scalar_one() == 0


@pytest.mark.asyncio
@respx.mock
async def test_webhook_asks_stripe_to_retry_when_it_cannot_read_the_subscription(db):
    await _seed_account(db)
    respx.get(f"{STRIPE}/v1/subscriptions/sub_1").mock(return_value=httpx.Response(500))
    payload, sig = _signed({"id": "evt_r", "type": "customer.subscription.updated", "data": {"object": {"id": "sub_1"}}})
    async with _client(_session_user()) as client:
        response = await client.post("/billing/stripe-webhook", content=payload, headers={"stripe-signature": sig})
    assert response.status_code == 503
    async with db() as session:
        # Not recorded, so Stripe's retry is processed.
        assert (await session.execute(text("SELECT count(*) FROM billing_events"))).scalar_one() == 0


@pytest.mark.asyncio
@respx.mock
async def test_portal_needs_a_billing_account(db):
    portal = respx.post(f"{STRIPE}/v1/billing_portal/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://billing.stripe.com/p/session/x"}))
    async with _client(_session_user()) as client:
        missing = await client.post("/api/v1/billing/portal")
        await _seed_account(db)
        ok = await client.post("/api/v1/billing/portal")
    assert missing.status_code == 404
    assert ok.json() == {"url": "https://billing.stripe.com/p/session/x"}
    form = parse_qs(portal.calls[0].request.content.decode())
    assert form == {"customer": ["cus_1"], "return_url": ["https://app.example.test/history"]}


def test_stripe_param_encoding_and_period_fallback():
    assert stripe_client._flatten({"a": {"b": [{"c": 1}], "d": True}, "e": None}) == [("a[b][0][c]", "1"), ("a[d]", "true")]
    assert stripe_client.subscription_period({"current_period_start": 1, "current_period_end": 2}) == (1, 2)
    assert stripe_client.subscription_period(_sub()) == (NOW - 60, NOW + 30 * 86400)
    assert stripe_client.subscription_period({"items": {"data": []}}) == (None, None)


def test_mock_api_base_is_refused_in_released_builds(monkeypatch):
    monkeypatch.setenv("STRIPE_API_BASE", "http://127.0.0.1:9999")
    monkeypatch.delenv("RELEASE", raising=False)
    assert stripe_client._api_base() == "http://127.0.0.1:9999"
    monkeypatch.setenv("RELEASE", "abc123")
    assert stripe_client._api_base() == STRIPE


@pytest.mark.asyncio
@respx.mock
async def test_public_plans_report_the_stripe_price_and_tier_sizes(db, monkeypatch):
    billing._PRICE_CACHE.clear()
    price = respx.get(f"{STRIPE}/v1/prices/{PRICE}").mock(return_value=httpx.Response(200, json={
        "id": PRICE, "unit_amount": 14900, "currency": "usd", "recurring": {"interval": "month"}}))
    monkeypatch.setenv("PRO_MONTHLY_CHECKS", "50")
    monkeypatch.setenv("FREE_CHECKS_WORK", "15")
    monkeypatch.setenv("FREE_CHECKS_PERSONAL", "3")
    async with _client(_session_user()) as client:
        first = (await client.get("/billing/plans")).json()
        await client.get("/billing/plans")
        monkeypatch.delenv("STRIPE_SECRET_KEY")
        off = (await client.get("/billing/plans")).json()
    assert first == {"free": {"work_checks": 15, "personal_checks": 3, "catalog_parts": 50}, "pro": {
        "checkout_available": True, "monthly_checks": 50,
        "price": {"unit_amount": 14900, "currency": "usd", "interval": "month"}}}
    assert price.call_count == 1  # cached
    assert off["pro"] == {"checkout_available": False, "monthly_checks": 50, "price": None}


@pytest.mark.asyncio
async def test_webhook_refuses_oversized_bodies_before_reading_them(db):
    async with _client(_session_user()) as client:
        response = await client.post("/billing/stripe-webhook", content=b"x" * (billing.MAX_WEBHOOK_BYTES + 1),
                                     headers={"stripe-signature": "t=1,v1=00"})
    assert response.status_code == 413
