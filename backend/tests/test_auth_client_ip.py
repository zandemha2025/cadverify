from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _request(
    *,
    headers: dict[str, str] | None = None,
    method: str = "POST",
    path: str = "/auth/login",
) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "scheme": "https",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (key.lower().encode(), value.encode())
            for key, value in (headers or {}).items()
        ],
        "client": ("203.0.113.90", 12345),
        "server": ("api.example.test", 443),
    }
    return Request(scope)


def _signed_headers(secret: bytes, ip: str, timestamp: str) -> dict[str, str]:
    payload = f"{timestamp}\nPOST\n/auth/login\n{ip}".encode()
    signature = base64.urlsafe_b64encode(
        hmac.new(secret, payload, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return {
        "x-cadverify-client-ip": ip,
        "x-cadverify-proxy-timestamp": timestamp,
        "x-cadverify-proxy-signature": signature,
    }


def test_valid_proxy_signature_restores_real_client_ip(monkeypatch):
    from src.auth.client_ip import client_ip, verified_proxy_client_ip

    secret = b"p" * 32
    monkeypatch.setenv("AUTH_PROXY_SECRET", base64.b64encode(secret).decode())
    headers = _signed_headers(secret, "198.51.100.44", str(int(time.time())))
    request = _request(headers=headers)

    assert verified_proxy_client_ip(request) == "198.51.100.44"
    assert client_ip(request) == "198.51.100.44"


def test_spoofed_or_expired_proxy_header_falls_back_to_socket_peer(monkeypatch):
    from src.auth.client_ip import client_ip

    secret = b"p" * 32
    monkeypatch.setenv("AUTH_PROXY_SECRET", base64.b64encode(secret).decode())
    expired = _signed_headers(secret, "198.51.100.44", str(int(time.time()) - 300))
    assert client_ip(_request(headers=expired)) == "203.0.113.90"

    tampered = _signed_headers(secret, "198.51.100.44", str(int(time.time())))
    tampered["x-cadverify-client-ip"] = "198.51.100.45"
    assert client_ip(_request(headers=tampered)) == "203.0.113.90"


def test_proxy_handshake_requires_a_verified_signature(monkeypatch):
    from src.auth.client_ip import require_verified_proxy

    monkeypatch.delenv("AUTH_PROXY_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_verified_proxy(_request())
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "auth_proxy_unavailable"


def test_auth_proxy_enforcement_is_deploy_gated(monkeypatch):
    from src.auth.client_ip import require_auth_proxy_if_enabled

    monkeypatch.delenv("PRODUCTION_AUTH_PROXY_REQUIRED", raising=False)
    assert require_auth_proxy_if_enabled(_request()) is None

    monkeypatch.setenv("PRODUCTION_AUTH_PROXY_REQUIRED", "1")
    monkeypatch.delenv("AUTH_PROXY_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        require_auth_proxy_if_enabled(_request())
    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "auth_proxy_unavailable"
