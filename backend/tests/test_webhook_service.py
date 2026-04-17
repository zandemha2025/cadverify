"""Unit tests for webhook_service module.

Covers HMAC signing, verification, replay protection, timing-safe comparison,
and retry delay configuration.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.webhook_service import (
    RETRY_DELAYS,
    sign_webhook_payload,
    verify_webhook_signature,
)


# ---------------------------------------------------------------------------
# sign_webhook_payload
# ---------------------------------------------------------------------------


def test_sign_webhook_payload():
    """Signature matches format t=\\d+,v1=[a-f0-9]{64}."""
    payload = b'{"event":"batch.completed","batch_id":"01ABC"}'
    secret = "whsec_test_secret_123"
    sig = sign_webhook_payload(payload, secret)

    assert re.match(r"t=\d+,v1=[a-f0-9]{64}", sig), f"Bad format: {sig}"


def test_sign_webhook_payload_deterministic_within_second():
    """Two calls in the same second produce identical signatures."""
    payload = b'{"test":true}'
    secret = "secret"
    # Patch time.time to return a fixed value
    with patch("src.services.webhook_service.time.time", return_value=1700000000.0):
        sig1 = sign_webhook_payload(payload, secret)
        sig2 = sign_webhook_payload(payload, secret)
    assert sig1 == sig2


# ---------------------------------------------------------------------------
# verify_webhook_signature
# ---------------------------------------------------------------------------


def test_verify_webhook_signature_valid():
    """Sign then verify returns True."""
    payload = b'{"event":"batch.completed"}'
    secret = "whsec_my_secret"
    sig = sign_webhook_payload(payload, secret)
    assert verify_webhook_signature(payload, secret, sig) is True


def test_verify_webhook_signature_wrong_secret():
    """Different secret returns False."""
    payload = b'{"event":"test"}'
    sig = sign_webhook_payload(payload, "correct_secret")
    assert verify_webhook_signature(payload, "wrong_secret", sig) is False


def test_verify_webhook_signature_expired():
    """Timestamp >300s ago returns False (replay protection)."""
    payload = b'{"event":"old"}'
    secret = "secret"
    # Create signature with old timestamp
    old_ts = str(int(time.time()) - 600)  # 10 minutes ago
    signed_content = f"{old_ts}.{payload.decode()}"
    hex_sig = hmac.new(
        secret.encode(), signed_content.encode(), hashlib.sha256
    ).hexdigest()
    old_sig = f"t={old_ts},v1={hex_sig}"

    assert verify_webhook_signature(payload, secret, old_sig) is False


def test_verify_webhook_signature_tampered_payload():
    """Tampered payload returns False."""
    secret = "secret"
    sig = sign_webhook_payload(b'{"original":true}', secret)
    assert verify_webhook_signature(b'{"tampered":true}', secret, sig) is False


def test_verify_uses_compare_digest():
    """Implementation uses hmac.compare_digest (timing-safe)."""
    import inspect
    from src.services import webhook_service

    source = inspect.getsource(webhook_service.verify_webhook_signature)
    assert "hmac.compare_digest" in source


def test_verify_bad_header_format():
    """Malformed signature header returns False."""
    assert verify_webhook_signature(b"test", "secret", "garbage") is False
    assert verify_webhook_signature(b"test", "secret", "") is False
    assert verify_webhook_signature(b"test", "secret", "t=123") is False


# ---------------------------------------------------------------------------
# Retry delays
# ---------------------------------------------------------------------------


def test_retry_delays_exponential():
    """RETRY_DELAYS matches expected values."""
    assert RETRY_DELAYS == [10, 30, 90, 270, 810]


def test_retry_delays_length():
    """Exactly 5 retry attempts."""
    assert len(RETRY_DELAYS) == 5
