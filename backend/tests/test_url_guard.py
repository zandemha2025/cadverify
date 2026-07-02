"""Tests for the webhook SSRF guard (S7).

Uses IP literals so the reject/accept cases need no DNS, and mocks
socket.getaddrinfo for the hostname-resolution paths.
"""
from __future__ import annotations

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.services import url_guard
from src.services.url_guard import (
    UnsafeURLError,
    is_safe_outbound_url,
    validate_outbound_url,
)


# ---------------------------------------------------------------------------
# validate_outbound_url — rejects
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://127.5.5.5/hook",
        "http://10.0.0.1/hook",
        "http://172.16.0.1/hook",
        "http://192.168.1.1/hook",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://0.0.0.0/hook",
        "http://[::1]/hook",
        "http://[fc00::1]/hook",  # IPv6 unique-local
        "http://[fe80::1]/hook",  # IPv6 link-local
    ],
)
def test_rejects_non_routable_ip_literals(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)
    assert is_safe_outbound_url(url) is False


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/x", "file:///etc/passwd", "gopher://1.2.3.4/", "//no-scheme"],
)
def test_rejects_non_http_schemes(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


def test_rejects_missing_host():
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http:///path-only")


def test_rejects_ipv4_mapped_ipv6_loopback():
    # ::ffff:127.0.0.1 must be unwrapped and blocked.
    with pytest.raises(UnsafeURLError):
        validate_outbound_url("http://[::ffff:127.0.0.1]/hook")


# ---------------------------------------------------------------------------
# validate_outbound_url — accepts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://93.184.216.34/webhook",  # public IPv4 literal
        "http://93.184.216.34:8080/webhook",
        "https://[2606:2800:220:1:248:1893:25c8:1946]/hook",  # public IPv6 literal
    ],
)
def test_accepts_public_ip_literals(url):
    validate_outbound_url(url)  # no raise
    assert is_safe_outbound_url(url) is True


def test_hostname_resolving_to_public_ip_is_accepted():
    with patch(
        "src.services.url_guard.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
    ):
        validate_outbound_url("https://webhooks.example.com/hook")


def test_hostname_resolving_to_private_ip_is_rejected():
    # DNS rebinding style: public name -> RFC-1918 address.
    with patch(
        "src.services.url_guard.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.1.2.3", 0))],
    ):
        with pytest.raises(UnsafeURLError):
            validate_outbound_url("https://evil.example.com/hook")


def test_unresolvable_host_rejected():
    import socket as _socket

    with patch(
        "src.services.url_guard.socket.getaddrinfo",
        side_effect=_socket.gaierror("nope"),
    ):
        with pytest.raises(UnsafeURLError):
            validate_outbound_url("https://does-not-exist.invalid/hook")


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------


def test_none_and_empty_are_noops():
    validate_outbound_url(None)
    validate_outbound_url("")
    assert is_safe_outbound_url(None) is True


def test_off_switch_disables_guard(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SSRF_GUARD_ENABLED", "0")
    validate_outbound_url("http://127.0.0.1/hook")  # no raise when disabled


# ---------------------------------------------------------------------------
# Request-time enforcement: POST /batch returns 400 for an internal webhook_url
# ---------------------------------------------------------------------------


def _batch_app():
    from src.api.batch_router import router
    from src.auth.require_api_key import AuthedUser, require_api_key
    from src.db.engine import get_db_session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(
        user_id=1, api_key_id=1, key_prefix="cv_live_test"
    )
    app.dependency_overrides[get_db_session] = lambda: AsyncMock()
    return app


def test_create_batch_rejects_internal_webhook_url():
    app = _batch_app()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("part.stl", b"solid test\nendsolid test")
    buf.seek(0)

    with patch("src.api.batch_router.batch_service") as mock_bs:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/batch",
            files={"file": ("test.zip", buf, "application/zip")},
            data={"webhook_url": "http://169.254.169.254/latest/meta-data/"},
        )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "webhook_url_rejected"
    # Rejected before any batch row is created.
    mock_bs.create_batch.assert_not_called()
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Delivery-time re-check: deliver_webhook marks failed, never sends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deliver_webhook_blocks_rebound_url():
    from src.services import webhook_service

    delivery = MagicMock()
    delivery.id = 7
    delivery.batch_id = 3
    delivery.attempts = 0
    delivery.payload_json = {"event": "batch.completed"}

    batch = MagicMock()
    batch.id = 3
    batch.ulid = "01BATCH"
    batch.webhook_url = "http://169.254.169.254/latest/meta-data/"
    batch.webhook_secret = "s"

    res1 = MagicMock()
    res1.scalars.return_value.first.return_value = delivery
    res2 = MagicMock()
    res2.scalars.return_value.first.return_value = batch

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[res1, res2])

    with patch("src.services.webhook_service.httpx.AsyncClient") as mock_client:
        ok = await webhook_service.deliver_webhook(session, 7)

    assert ok is False
    assert delivery.status == "failed"
    mock_client.assert_not_called()  # no outbound request ever made


@pytest.mark.asyncio
async def test_terminally_failed_delivery_not_rescheduled():
    """An SSRF-blocked (status=failed) delivery must not be retried forever."""
    from src.services import webhook_service

    delivery = MagicMock()
    delivery.id = 9
    delivery.status = "failed"
    delivery.attempts = 0  # never incremented by the SSRF-block path

    res = MagicMock()
    res.scalars.return_value.first.return_value = delivery
    session = AsyncMock()
    session.execute = AsyncMock(return_value=res)
    pool = AsyncMock()

    await webhook_service.schedule_webhook_retry(session, 9, pool)

    pool.enqueue_job.assert_not_called()
