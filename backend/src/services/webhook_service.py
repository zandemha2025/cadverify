"""Webhook service -- HMAC signing, delivery, and retry logic.

Implements Stripe-like webhook signature format (t=timestamp,v1=hmac_hex)
with exponential backoff retries and timing-safe verification.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Batch, WebhookDelivery
from src.services.url_guard import validate_outbound_url

logger = logging.getLogger("cadverify.webhook_service")

# Exponential backoff delays in seconds: ~10s, 30s, 90s, 270s, 810s
RETRY_DELAYS = [10, 30, 90, 270, 810]


# ---------------------------------------------------------------------------
# HMAC signing (Stripe-like format)
# ---------------------------------------------------------------------------


def sign_webhook_payload(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature in Stripe-like header format.

    Returns: "t={unix_timestamp},v1={hex_signature}"
    """
    if not secret or not secret.strip():
        raise ValueError("A webhook signing secret is required.")
    timestamp = str(int(time.time()))
    signed_content = f"{timestamp}.{payload_bytes.decode()}"
    signature = hmac.new(
        secret.encode(), signed_content.encode(), hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


def verify_webhook_signature(
    payload_bytes: bytes,
    secret: str,
    signature_header: str,
    tolerance_sec: int = 300,
) -> bool:
    """Verify a webhook signature header against the expected HMAC.

    Parses t=... and v1=... from header, reconstructs signed_content,
    and uses timing-safe comparison. Rejects if timestamp exceeds tolerance
    (replay protection).
    """
    if not secret or not secret.strip():
        return False
    try:
        parts = {}
        for segment in signature_header.split(","):
            key, _, value = segment.partition("=")
            parts[key.strip()] = value.strip()

        t_str = parts.get("t")
        v1 = parts.get("v1")
        if not t_str or not v1:
            return False

        # Replay protection
        if abs(time.time() - int(t_str)) > tolerance_sec:
            return False

        signed_content = f"{t_str}.{payload_bytes.decode()}"
        expected = hmac.new(
            secret.encode(), signed_content.encode(), hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected, v1)
    except Exception:
        logger.exception("Webhook signature verification error")
        return False


# ---------------------------------------------------------------------------
# Delivery CRUD
# ---------------------------------------------------------------------------


async def create_webhook_delivery(
    session: AsyncSession,
    batch_id: int,
    event_type: str,
    payload: dict,
) -> WebhookDelivery:
    """Create a WebhookDelivery row with status='pending', attempts=0."""
    from src.auth.org_context import resolve_org_via_batch

    delivery = WebhookDelivery(
        batch_id=batch_id,
        org_id=await resolve_org_via_batch(session, batch_id),
        event_type=event_type,
        payload_json=payload,
        status="pending",
        attempts=0,
    )
    session.add(delivery)
    await session.flush()
    return delivery


# ---------------------------------------------------------------------------
# Delivery dispatch
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The batch's signing secret at rest
# ---------------------------------------------------------------------------

# batches.webhook_secret holds the secret sealed with the connector-credential
# Fernet key (CONNECTOR_SECRET_KEY), behind this prefix. A value without it is a
# row written before sealing (plaintext); the first delivery re-saves it sealed.
SEALED_SECRET_PREFIX = "fernet:v1:"


class WebhookSecretUnreadable(ValueError):
    """A sealed webhook secret that this deployment's key cannot open."""


def seal_webhook_secret(secret: Optional[str]) -> Optional[str]:
    """The value to store for a batch's signing secret (none or blank: None)."""
    if secret is None or not secret.strip():
        return None
    from fastapi import HTTPException

    from src.services.connector_credentials_service import _fernet

    try:
        token = _fernet().encrypt(secret.encode("utf-8")).decode("ascii")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Webhook signing storage is not configured. Ask the workspace operator to enable it.",
        ) from exc
    return SEALED_SECRET_PREFIX + token


def open_webhook_secret(stored: Optional[str]) -> tuple[Optional[str], bool]:
    """``(secret, plaintext_row)`` from a stored value.

    ``plaintext_row`` is True for a value written before sealing, which the
    caller re-saves sealed. Raises WebhookSecretUnreadable when a sealed value
    can't be opened with this deployment's key.
    """
    if not stored or not stored.startswith(SEALED_SECRET_PREFIX):
        return stored, bool(stored)
    from cryptography.fernet import InvalidToken

    from src.services.connector_credentials_service import _fernet

    token = stored[len(SEALED_SECRET_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8"), False
    except (InvalidToken, RuntimeError, UnicodeError, ValueError) as exc:
        raise WebhookSecretUnreadable("webhook signing secret cannot be opened") from exc


async def seal_plaintext_webhook_secrets(session_factory=None, *, page: int = 200) -> int:
    """Seal every batch webhook secret still stored in plaintext; returns how many.

    Same column, no migration: each plaintext value is replaced by its sealed
    form only if it is unchanged since it was read. Run once at worker startup.
    """
    from sqlalchemy import update

    if session_factory is None:
        from src.db.engine import get_session_factory

        session_factory = get_session_factory()
    sealed = 0
    last_id = 0
    while True:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Batch.id, Batch.webhook_secret)
                    .where(
                        Batch.id > last_id,
                        Batch.webhook_secret.is_not(None),
                        ~Batch.webhook_secret.startswith(SEALED_SECRET_PREFIX, autoescape=True),
                    )
                    .order_by(Batch.id)
                    .limit(page)
                )
            ).all()
            if not rows:
                return sealed
            for batch_id, stored in rows:
                last_id = batch_id
                await session.execute(
                    update(Batch)
                    .where(Batch.id == batch_id, Batch.webhook_secret == stored)
                    .values(webhook_secret=seal_webhook_secret(stored))
                )
            await session.commit()
            sealed += len(rows)


async def deliver_webhook(
    session: AsyncSession,
    delivery_id: int,
) -> bool:
    """Attempt to deliver a webhook. Returns True on success, False on failure.

    Fetches delivery + associated batch for webhook_url and webhook_secret.
    Signs payload, POSTs to URL, updates delivery record.
    """
    delivery = (
        await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
        )
    ).scalars().first()

    if delivery is None:
        logger.error("WebhookDelivery %d not found", delivery_id)
        return False

    batch = (
        await session.execute(
            select(Batch).where(Batch.id == delivery.batch_id)
        )
    ).scalars().first()

    if batch is None:
        logger.error("Batch %d not found for delivery %d", delivery.batch_id, delivery_id)
        delivery.status = "failed"
        await session.commit()
        return False

    # No webhook URL configured -- mark delivered and return
    if not batch.webhook_url:
        delivery.status = "delivered"
        delivery.last_attempt_at = datetime.now(timezone.utc)
        await session.commit()
        return True

    try:
        secret, plaintext_row = open_webhook_secret(batch.webhook_secret)
    except WebhookSecretUnreadable:
        # Sealed under a key this deployment doesn't hold: a configuration
        # error that retrying can't fix. Never sign with anything else.
        delivery.status = "failed"
        delivery.last_attempt_at = datetime.now(timezone.utc)
        await session.commit()
        logger.warning("Webhook delivery %d: the signing secret cannot be opened", delivery_id)
        return False
    if plaintext_row and secret.strip():
        # A row stored before sealing: keep it sealed from now on (saved with
        # this delivery's own commit). Without the key it stays as it was.
        try:
            batch.webhook_secret = seal_webhook_secret(secret)
        except Exception:
            logger.warning("Webhook delivery %d: could not re-save the signing secret sealed", delivery_id)
    if not secret or not secret.strip():
        # Old rows may predate submission validation. Never send a signature
        # made with the public empty key, or retry this permanent configuration error.
        delivery.status = "failed"
        delivery.last_attempt_at = datetime.now(timezone.utc)
        await session.commit()
        logger.warning("Webhook delivery %d has no signing secret", delivery_id)
        return False

    # Resolve once at delivery time and connect only to the vetted addresses,
    # preserving Host and TLS SNI as in connector_transport.
    # A rejected URL is a permanent failure -- mark failed, never retried.
    try:
        url = httpx.URL(batch.webhook_url)
        addresses = await asyncio.to_thread(validate_outbound_url, str(url))
    except (ValueError, httpx.InvalidURL):
        logger.warning(
            "Webhook delivery blocked by SSRF guard: delivery=%d batch=%s",
            delivery_id, batch.ulid,
        )
        delivery.status = "failed"
        delivery.last_attempt_at = datetime.now(timezone.utc)
        await session.commit()
        return False

    # Sign and send
    import json

    payload_bytes = json.dumps(delivery.payload_json, default=str).encode()
    signature = sign_webhook_payload(payload_bytes, secret)

    headers = {
        "Host": url.netloc.decode("ascii"),
        "Content-Type": "application/json",
        "X-CadVerify-Signature": signature,
        "User-Agent": "ScaleCad-Webhook/1.0",
    }

    now = datetime.now(timezone.utc)
    delivery.attempts += 1
    delivery.last_attempt_at = now

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            targets = addresses or [url.host]  # Preserve the operator's explicit guard off-switch.
            for index, address in enumerate(targets):
                try:
                    # Acknowledgement needs only the status; never buffer an
                    # unbounded response body supplied by the recipient.
                    async with client.stream(
                        "POST", url.copy_with(host=address), content=payload_bytes,
                        headers=headers, extensions={"sni_hostname": url.host},
                    ) as response:
                        status = response.status_code
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if index == len(targets) - 1:
                        raise
            else:
                raise httpx.ConnectError("No webhook address available")
        delivery.response_code = status
        if 200 <= status < 300:
            delivery.status = "delivered"
            await session.commit()
            logger.info(
                "Webhook delivered: delivery=%d batch=%s status=%d",
                delivery_id, batch.ulid, status,
            )
            return True
        else:
            logger.warning(
                "Webhook non-2xx: delivery=%d batch=%s status=%d",
                delivery_id, batch.ulid, status,
            )
            await session.commit()
            return False
    except Exception:
        logger.exception(
            "Webhook delivery failed: delivery=%d batch=%s",
            delivery_id, batch.ulid,
        )
        await session.commit()
        return False


# ---------------------------------------------------------------------------
# Retry scheduling
# ---------------------------------------------------------------------------


async def schedule_webhook_retry(
    session: AsyncSession,
    delivery_id: int,
    pool,
) -> None:
    """Schedule a retry for a failed webhook delivery with exponential backoff.

    RETRY_DELAYS = [10, 30, 90, 270, 810] seconds.
    After 5 attempts, marks delivery as failed.
    Adds jitter of up to 10% of the delay.
    """
    delivery = (
        await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery_id)
        )
    ).scalars().first()

    if delivery is None:
        logger.error("WebhookDelivery %d not found for retry", delivery_id)
        return

    # Terminal failure (e.g. rejected by the SSRF guard at delivery time) must
    # never be rescheduled -- that path does not increment attempts, so without
    # this guard it would retry forever.
    if delivery.status == "failed":
        return

    if delivery.attempts >= 5:
        delivery.status = "failed"
        await session.commit()
        logger.warning(
            "Webhook delivery %d exhausted retries (%d attempts)",
            delivery_id, delivery.attempts,
        )
        return

    delay = RETRY_DELAYS[delivery.attempts] + random.uniform(
        0, RETRY_DELAYS[delivery.attempts] * 0.1
    )
    delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    await session.commit()

    # Enqueue retry via arq
    await pool.enqueue_job("dispatch_webhook", delivery_id, _defer_by=timedelta(seconds=delay))
    logger.info(
        "Webhook retry scheduled: delivery=%d attempt=%d delay=%.1fs",
        delivery_id, delivery.attempts, delay,
    )
