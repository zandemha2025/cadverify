"""Webhook service -- HMAC signing, delivery, and retry logic.

Implements Stripe-like webhook signature format (t=timestamp,v1=hmac_hex)
with exponential backoff retries and timing-safe verification.
"""
from __future__ import annotations

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
    delivery = WebhookDelivery(
        batch_id=batch_id,
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

    # Sign and send
    import json

    payload_bytes = json.dumps(delivery.payload_json, default=str).encode()
    signature = sign_webhook_payload(payload_bytes, batch.webhook_secret or "")

    headers = {
        "Content-Type": "application/json",
        "X-CadVerify-Signature": signature,
        "User-Agent": "CadVerify-Webhook/1.0",
    }

    now = datetime.now(timezone.utc)
    delivery.attempts += 1
    delivery.last_attempt_at = now

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                batch.webhook_url,
                content=payload_bytes,
                headers=headers,
            )
        delivery.response_code = resp.status_code
        if 200 <= resp.status_code < 300:
            delivery.status = "delivered"
            await session.commit()
            logger.info(
                "Webhook delivered: delivery=%d batch=%s status=%d",
                delivery_id, batch.ulid, resp.status_code,
            )
            return True
        else:
            logger.warning(
                "Webhook non-2xx: delivery=%d batch=%s status=%d",
                delivery_id, batch.ulid, resp.status_code,
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
