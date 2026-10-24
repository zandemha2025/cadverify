"""Authenticated client-IP forwarding for the first-party web proxy.

The browser sends password and magic-link requests to Next.js so session
tokens never enter browser JavaScript. Without an authenticated handoff, the
API sees only the frontend machine/pod address and collapses every customer
into one abuse-control bucket. The frontend therefore signs the original IP,
request method, backend path, and a short-lived timestamp with a dedicated
shared secret.

Unsigned requests remain valid and use the direct socket peer. That preserves
direct API/OAuth traffic while making spoofed forwarding headers useless.
"""
from __future__ import annotations

from src.config.public_urls import error_doc_url

import base64
import hashlib
import hmac
import ipaddress
import os
import time

from fastapi import HTTPException, Request

CLIENT_IP_HEADER = "x-cadverify-client-ip"
TIMESTAMP_HEADER = "x-cadverify-proxy-timestamp"
SIGNATURE_HEADER = "x-cadverify-proxy-signature"
MAX_CLOCK_SKEW_SECONDS = 90
_TRUTHY = {"1", "true", "yes", "on"}


def _secret() -> bytes | None:
    raw = os.getenv("AUTH_PROXY_SECRET", "").strip()
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        return None
    return decoded if len(decoded) >= 32 else None


def signature_payload(timestamp: str, method: str, path: str, ip: str) -> bytes:
    """Canonical payload shared with ``frontend/src/lib/auth-proxy.ts``."""
    return f"{timestamp}\n{method.upper()}\n{path}\n{ip}".encode()


def _encoded_signature(payload: bytes, secret: bytes) -> str:
    digest = hmac.new(secret, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def verified_proxy_client_ip(request: Request) -> str | None:
    """Return the signed proxy IP, or ``None`` for absent/invalid headers."""
    headers = getattr(request, "headers", {})
    ip = headers.get(CLIENT_IP_HEADER, "").strip()
    timestamp = headers.get(TIMESTAMP_HEADER, "").strip()
    supplied = headers.get(SIGNATURE_HEADER, "").strip()
    secret = _secret()
    if not ip or not timestamp or not supplied or secret is None:
        return None

    try:
        ipaddress.ip_address(ip)
        issued_at = int(timestamp)
    except (ValueError, TypeError):
        return None
    if abs(int(time.time()) - issued_at) > MAX_CLOCK_SKEW_SECONDS:
        return None

    expected = _encoded_signature(
        signature_payload(timestamp, request.method, request.url.path, ip),
        secret,
    )
    return ip if hmac.compare_digest(supplied, expected) else None


def client_ip(request: Request) -> str:
    """Rate-limit identity: verified proxy IP, otherwise direct socket peer."""
    forwarded = verified_proxy_client_ip(request)
    if forwarded is not None:
        return forwarded
    peer = getattr(request, "client", None)
    return peer.host if peer else "unknown"


def require_verified_proxy(request: Request) -> str:
    """Fail closed for the deploy-time frontend/backend proxy handshake."""
    forwarded = verified_proxy_client_ip(request)
    if forwarded is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "auth_proxy_unavailable",
                "message": "The first-party authentication proxy is unavailable.",
                "doc_url": error_doc_url("auth_proxy_unavailable"),
            },
        )
    return forwarded


def require_auth_proxy_if_enabled(request: Request) -> str | None:
    """Enforce the server-to-server auth boundary when deployment requires it.

    Local development and direct API test harnesses keep their historical
    behavior. Released commercial deployments set
    ``PRODUCTION_AUTH_PROXY_REQUIRED=1`` and therefore cannot return a session
    bearer to an unsigned browser/direct caller.
    """
    if os.getenv("PRODUCTION_AUTH_PROXY_REQUIRED", "0").strip().lower() in _TRUTHY:
        return require_verified_proxy(request)
    return None
