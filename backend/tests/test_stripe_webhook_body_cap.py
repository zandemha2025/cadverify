"""The Stripe webhook refuses a body over 1 MiB while reading it.

A request without Content-Length (chunked transfer encoding) is read chunk by
chunk and refused with 413 as soon as it passes MAX_WEBHOOK_BYTES, so the
whole body is never buffered and the signature check never runs on it.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.api import billing


@pytest.fixture()
def webhook(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    monkeypatch.setenv("STRIPE_PRO_PRICE_ID", "price_pro_test")
    verified: list[bytes] = []

    def fake_verify(payload, signature):
        verified.append(payload)
        return {"id": "evt_x", "type": "invoice.paid", "data": {"object": {"id": "in_1"}}}

    monkeypatch.setattr(billing, "verify_webhook", fake_verify)
    app = FastAPI()
    app.include_router(billing.webhook_router, prefix="/billing")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, verified


def _chunks(total_chunks: int, size: int, sent: list):
    async def gen():
        for _ in range(total_chunks):
            sent.append(size)
            yield b"x" * size
    return gen()


@pytest.mark.asyncio
async def test_chunked_body_over_cap_is_refused_while_reading(webhook):
    client, verified = webhook
    sent: list = []
    chunk = 64 * 1024
    async with client:
        resp = await client.post(
            "/billing/stripe-webhook",
            content=_chunks(100, chunk, sent),
            headers={"stripe-signature": "t=1,v1=00"},
        )
    assert resp.status_code == 413, resp.text
    assert verified == []
    # Reading stopped just past 1 MiB instead of draining all 6.25 MiB.
    assert sum(sent) <= billing.MAX_WEBHOOK_BYTES + 4 * chunk, sum(sent)


@pytest.mark.asyncio
async def test_declared_length_over_cap_is_refused_up_front(webhook):
    client, verified = webhook
    async with client:
        resp = await client.post(
            "/billing/stripe-webhook",
            content=b"x" * (billing.MAX_WEBHOOK_BYTES + 1),
            headers={"stripe-signature": "t=1,v1=00"},
        )
    assert resp.status_code == 413
    assert verified == []


@pytest.mark.asyncio
async def test_chunked_body_within_cap_reaches_signature_check_whole(webhook):
    client, verified = webhook
    sent: list = []
    async with client:
        resp = await client.post(
            "/billing/stripe-webhook",
            content=_chunks(4, 1000, sent),
            headers={"stripe-signature": "t=1,v1=00"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["handled"] is False
    assert verified == [b"x" * 4000]
