"""A batch's webhook signing secret is stored encrypted, never in plaintext.

The secret is sealed with the connector-credential Fernet key
(CONNECTOR_SECRET_KEY) when the batch is created, opened only to sign a
delivery, and a row written before this (plaintext) is re-saved sealed the
first time a delivery reads it. The API never returns the secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from cryptography.fernet import Fernet

from src.services import webhook_service

SECRET = "local-test-only-signing-sentinel"


@pytest.fixture(autouse=True)
def connector_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTOR_SECRET_KEY", key)
    return key


def _delivery_session(batch):
    delivery = MagicMock(batch_id=1, status="pending", attempts=0, response_code=None,
                         payload_json={"event": "batch.completed", "batch_id": "B1"})
    delivery_result, batch_result = MagicMock(), MagicMock()
    delivery_result.scalars.return_value.first.return_value = delivery
    batch_result.scalars.return_value.first.return_value = batch
    session = AsyncMock()
    session.execute.side_effect = [delivery_result, batch_result]
    return session, delivery


def _capture_requests(monkeypatch):
    requests = []
    real_client = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(webhook_service, "validate_outbound_url", lambda url: ["93.184.216.34"])
    return requests


def _signed_with(request, secret: str) -> bool:
    timestamp, signature = request.headers["X-CadVerify-Signature"].split(",")
    expected = hmac.new(secret.encode(), timestamp[2:].encode() + b"." + request.content, hashlib.sha256).hexdigest()
    return signature == "v1=" + expected


@pytest.mark.asyncio
async def test_create_batch_stores_the_secret_sealed(monkeypatch):
    from src.services import batch_service

    monkeypatch.setattr("src.auth.org_context.resolve_org", AsyncMock(return_value="org-1"))
    monkeypatch.setattr("src.services.audit_service.emit_event", AsyncMock())
    session = MagicMock()
    session.flush = AsyncMock()
    batch = await batch_service.create_batch(
        session, user_id=1, input_mode="zip",
        webhook_url="https://hooks.example.test/receiver", webhook_secret=SECRET,
    )
    stored = batch.webhook_secret
    assert stored and SECRET not in stored
    assert stored.startswith(webhook_service.SEALED_SECRET_PREFIX)
    assert webhook_service.open_webhook_secret(stored) == (SECRET, False)


@pytest.mark.asyncio
async def test_create_batch_without_a_webhook_stores_no_secret(monkeypatch):
    from src.services import batch_service

    monkeypatch.setattr("src.auth.org_context.resolve_org", AsyncMock(return_value="org-1"))
    monkeypatch.setattr("src.services.audit_service.emit_event", AsyncMock())
    session = MagicMock()
    session.flush = AsyncMock()
    batch = await batch_service.create_batch(session, user_id=1, input_mode="zip")
    assert batch.webhook_secret is None


@pytest.mark.asyncio
async def test_a_sealed_secret_signs_deliveries_with_the_original(monkeypatch):
    requests = _capture_requests(monkeypatch)
    batch = MagicMock(webhook_url="https://hooks.example.test/receiver",
                      webhook_secret=webhook_service.seal_webhook_secret(SECRET))
    sealed = batch.webhook_secret
    session, delivery = _delivery_session(batch)
    assert await webhook_service.deliver_webhook(session, 7)
    assert len(requests) == 1 and _signed_with(requests[0], SECRET)
    assert delivery.status == "delivered"
    assert batch.webhook_secret == sealed


@pytest.mark.asyncio
async def test_a_plaintext_row_is_used_once_and_resaved_sealed(monkeypatch):
    requests = _capture_requests(monkeypatch)
    batch = MagicMock(webhook_url="https://hooks.example.test/receiver", webhook_secret=SECRET)
    session, _ = _delivery_session(batch)
    assert await webhook_service.deliver_webhook(session, 7)
    assert _signed_with(requests[0], SECRET)
    assert batch.webhook_secret.startswith(webhook_service.SEALED_SECRET_PREFIX)
    assert webhook_service.open_webhook_secret(batch.webhook_secret) == (SECRET, False)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_secret_sealed_under_another_key_fails_the_delivery_without_sending(monkeypatch):
    requests = _capture_requests(monkeypatch)
    other = Fernet(Fernet.generate_key()).encrypt(SECRET.encode()).decode()
    batch = MagicMock(webhook_url="https://hooks.example.test/receiver",
                      webhook_secret=webhook_service.SEALED_SECRET_PREFIX + other)
    session, delivery = _delivery_session(batch)
    assert not await webhook_service.deliver_webhook(session, 7)
    assert requests == []
    assert delivery.status == "failed"


def test_sealing_needs_the_connector_key_in_production(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("CONNECTOR_SECRET_KEY", raising=False)
    monkeypatch.setenv("RELEASE", "v-test")
    with pytest.raises(HTTPException) as exc:
        webhook_service.seal_webhook_secret(SECRET)
    assert exc.value.status_code == 503


@pytest.mark.skipif(
    not __import__("os").getenv("DATABASE_URL", "").startswith("postgresql"),
    reason="requires local Postgres (set DATABASE_URL=postgresql://...)",
)
@pytest.mark.asyncio
async def test_stored_plaintext_secrets_are_sealed_once():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from ulid import ULID

    from src.db import engine

    org = str(ULID())
    try:
        async with engine.get_engine().connect() as connection:
            outer = await connection.begin()
            try:
                def factory():
                    return AsyncSession(bind=connection, join_transaction_mode="create_savepoint")

                async with factory() as s:
                    await s.execute(text(
                        "INSERT INTO organizations (id, name, slug, created_at) VALUES (:id, :n, :n, now())"
                    ), {"id": org, "n": f"seal-{org.lower()}"})
                    uid = (await s.execute(text(
                        "INSERT INTO users (email, email_lower, role, auth_provider, plan) "
                        "VALUES (:e, :e, 'analyst', 'password', 'pilot') RETURNING id"
                    ), {"e": f"seal-{org.lower()}@example.com"})).scalar_one()
                    sealed = webhook_service.seal_webhook_secret("already-sealed")
                    for ulid, secret in (("P" + org[1:], SECRET), ("S" + org[1:], sealed), ("N" + org[1:], None)):
                        await s.execute(text(
                            "INSERT INTO batches (ulid, user_id, org_id, input_mode, webhook_secret) "
                            "VALUES (:u, :uid, :org, 'zip', :sec)"
                        ), {"u": ulid, "uid": uid, "org": org, "sec": secret})
                    await s.commit()

                assert await webhook_service.seal_plaintext_webhook_secrets(factory) >= 1
                assert await webhook_service.seal_plaintext_webhook_secrets(factory) == 0

                async with factory() as s:
                    rows = dict((await s.execute(text(
                        "SELECT ulid, webhook_secret FROM batches WHERE org_id = :org"
                    ), {"org": org})).all())
                plain = rows["P" + org[1:]]
                assert plain.startswith(webhook_service.SEALED_SECRET_PREFIX) and SECRET not in plain
                assert webhook_service.open_webhook_secret(plain) == (SECRET, False)
                assert rows["S" + org[1:]] == sealed
                assert rows["N" + org[1:]] is None
            finally:
                await outer.rollback()
    finally:
        await engine.dispose_engine()
