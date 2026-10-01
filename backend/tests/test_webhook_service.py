"""Unit tests for webhook_service module.

Covers HMAC signing, verification, replay protection, timing-safe comparison,
and retry delay configuration.
"""
from __future__ import annotations

import hashlib
import hmac
from ipaddress import ip_address
import re
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


@pytest.mark.parametrize("secret", ["", " \t\n"])
def test_blank_secret_cannot_sign_or_authenticate(secret):
    body = b'{"event":"batch.completed"}'
    timestamp = str(int(time.time()))
    forged = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert not verify_webhook_signature(body, secret, f"t={timestamp},v1={forged}")
    with pytest.raises(ValueError, match="signing secret"):
        sign_webhook_payload(body, secret)


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [None, "", " \t\n"])
async def test_delivery_without_a_secret_is_terminal_without_network(secret):
    from src.services import webhook_service

    delivery = MagicMock(batch_id=1, status="pending", attempts=0)
    batch = MagicMock(webhook_url="https://hooks.example.test/receiver", webhook_secret=secret)
    delivery_result, batch_result = MagicMock(), MagicMock()
    delivery_result.scalars.return_value.first.return_value = delivery
    batch_result.scalars.return_value.first.return_value = batch
    session = AsyncMock()
    session.execute.side_effect = [delivery_result, batch_result, delivery_result]
    pool = AsyncMock()
    with patch.object(webhook_service, "validate_outbound_url") as validate, patch.object(webhook_service.httpx, "AsyncClient") as client:
        assert not await webhook_service.deliver_webhook(session, 7)
        assert delivery.status == "failed"
        assert delivery.attempts == 0
        validate.assert_not_called()
        client.assert_not_called()
        await webhook_service.schedule_webhook_retry(session, 7, pool)
        pool.enqueue_job.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("url,addresses,fail_first,status", [
    ("https://hooks.example.test:8443/receiver?tenant=a", ["93.184.216.34"], False, 204),
    ("https://hooks.example.test/receiver", ["2606:4700:4700::1111", "93.184.216.34"], True, 200),
    ("http://[2606:4700:4700::1111]:8080/receiver", ["2606:4700:4700::1111"], False, 202),
    ("https://hooks.example.test/receiver", ["93.184.216.34"], False, 302),
    ("https://hooks.example.test/receiver", ["93.184.216.34"], False, 503),
])
async def test_configured_delivery_signs_the_exact_sent_body(monkeypatch, url, addresses, fail_first, status):
    from src.services import url_guard, webhook_service

    secret = "local-test-only-signing-sentinel"
    delivery = MagicMock(batch_id=1, status="pending", attempts=0,
                         payload_json={"event": "batch.completed", "batch_id": "LOCAL-AUDIT-CONTROL"})
    batch = MagicMock(webhook_url=url, webhook_secret=secret)
    delivery_result, batch_result = MagicMock(), MagicMock()
    delivery_result.scalars.return_value.first.return_value = delivery
    batch_result.scalars.return_value.first.return_value = batch
    session = AsyncMock()
    session.execute.side_effect = [delivery_result, batch_result]
    requests, resolver_threads, client_options = [], [], []
    original = httpx.URL(url)
    main_thread = threading.get_ident()
    def resolve(host):
        resolver_threads.append(threading.get_ident())
        # A second lookup would return a forbidden address. No socket is opened.
        return [ip_address(ip) for ip in (addresses if len(resolver_threads) == 1 else ["127.0.0.1"])]

    class UnreadBody(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            raise AssertionError("Webhook acknowledgements must not buffer unbounded recipient bodies")
            yield b""  # pragma: no cover
        async def aclose(self):
            self.closed = True

    body = UnreadBody()
    def handle(request):
        requests.append(request)
        if fail_first and len(requests) == 1:
            raise httpx.ConnectError("unreachable first vetted address", request=request)
        return httpx.Response(status, stream=body, headers={"Location": "http://127.0.0.1/forbidden"})

    real_client = httpx.AsyncClient
    def client(**options):
        client_options.append(options)
        return real_client(transport=httpx.MockTransport(handle), **options)
    monkeypatch.setenv("WEBHOOK_SSRF_GUARD_ENABLED", "1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(url_guard, "_resolve_ips", resolve)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    ok = await webhook_service.deliver_webhook(session, 7)
    assert [request.url.host for request in requests] == addresses
    assert len(resolver_threads) == 1 and resolver_threads[0] != main_thread
    assert client_options[0]["trust_env"] is False
    assert client_options[0]["follow_redirects"] is False
    assert body.closed
    for request in requests:
        assert request.method == "POST"
        assert request.url.raw_path == original.raw_path
        assert request.url.port == original.port
        assert request.headers["Host"] == original.netloc.decode("ascii")
        assert request.extensions["sni_hostname"] == original.host
        timestamp, signature = request.headers["X-CadVerify-Signature"].split(",")
        expected = hmac.new(secret.encode(), timestamp[2:].encode() + b"." + request.content, hashlib.sha256).hexdigest()
        assert signature == "v1=" + expected
        assert secret not in str(request.headers) + request.content.decode()
    assert ok is (200 <= status < 300)
    assert delivery.status == ("delivered" if ok else "pending")
    assert delivery.response_code == status
    assert delivery.attempts == 1
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,connection_count", [
    (httpx.ConnectError, 2), (httpx.ConnectTimeout, 2), (httpx.ReadTimeout, 1),
])
async def test_transport_failures_remain_retryable_without_reposting_after_send(monkeypatch, failure, connection_count):
    from src.services import webhook_service

    delivery = MagicMock(batch_id=1, status="pending", attempts=0, response_code=None, payload_json={"event": "batch.completed"})
    batch = MagicMock(webhook_url="https://hooks.example.test/receiver", webhook_secret="test-only-key")
    delivery_result, batch_result = MagicMock(), MagicMock()
    delivery_result.scalars.return_value.first.return_value = delivery
    batch_result.scalars.return_value.first.return_value = batch
    session = AsyncMock()
    session.execute.side_effect = [delivery_result, batch_result, delivery_result, delivery_result]
    requests = []
    def handle(request):
        requests.append(request)
        raise failure("controlled transport failure", request=request)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(webhook_service, "validate_outbound_url", lambda url: ["93.184.216.34", "93.184.216.35"])
    assert not await webhook_service.deliver_webhook(session, 7)
    assert len(requests) == connection_count
    assert delivery.status == "pending" and delivery.attempts == 1
    assert delivery.response_code is None
    pool = AsyncMock()
    await webhook_service.schedule_webhook_retry(session, 7, pool)
    assert pool.enqueue_job.call_args.args == ("dispatch_webhook", 7)
    assert pool.enqueue_job.call_args.kwargs["_defer_by"].total_seconds() > 0
    assert delivery.next_retry_at is not None
    delivery.attempts = 5
    await webhook_service.schedule_webhook_retry(session, 7, pool)
    assert delivery.status == "failed"
    pool.enqueue_job.assert_awaited_once()


# ---------------------------------------------------------------------------
# Retry delays
# ---------------------------------------------------------------------------


def test_retry_delays_exponential():
    """RETRY_DELAYS matches expected values."""
    assert RETRY_DELAYS == [10, 30, 90, 270, 810]


def test_retry_delays_length():
    """Exactly 5 retry attempts."""
    assert len(RETRY_DELAYS) == 5
