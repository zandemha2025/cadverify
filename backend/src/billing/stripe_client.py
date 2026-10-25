"""Minimal Stripe REST client for self-serve Pro billing.

Uses the Stripe HTTP API directly (form-encoded, bearer auth) so the hashed
production lock gains no new dependency. Webhook signatures follow Stripe's
documented scheme: HMAC-SHA256 over ``"{timestamp}.{raw body}"``.

Billing is off unless STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET and
STRIPE_PRO_PRICE_ID are all configured.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

STRIPE_API = "https://api.stripe.com"
SIGNATURE_TOLERANCE_SECONDS = 300
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class StripeError(RuntimeError):
    """Stripe rejected or failed a request. Never carries secrets."""

    def __init__(self, status: int, code: str | None = None):
        super().__init__(f"Stripe request failed ({status}{', ' + code if code else ''})")
        self.status = status
        self.code = code


def billing_enabled() -> bool:
    return all(os.getenv(name, "").strip() for name in
               ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRO_PRICE_ID"))


def pro_price_id() -> str:
    return os.getenv("STRIPE_PRO_PRICE_ID", "").strip()


def _api_base() -> str:
    # A local mock is allowed only outside released builds.
    override = os.getenv("STRIPE_API_BASE", "").strip().rstrip("/")
    return override if override and not os.getenv("RELEASE") else STRIPE_API


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Encode nested params the way Stripe expects: a[b][0][c]=v."""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            pairs.extend(_flatten(value, name))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                item_name = f"{name}[{index}]"
                if isinstance(item, dict):
                    pairs.extend(_flatten(item, item_name))
                else:
                    pairs.append((item_name, _scalar(item)))
        else:
            pairs.append((name, _scalar(value)))
    return pairs


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def stripe_request(
    method: str,
    path: str,
    data: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {os.environ['STRIPE_SECRET_KEY'].strip()}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    pairs = _flatten(data) if data is not None else []
    body = None
    if method != "GET" and pairs:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(pairs)
    async with httpx.AsyncClient(base_url=_api_base(), timeout=_TIMEOUT) as client:
        try:
            response = await client.request(
                method, path, headers=headers, content=body,
                params=tuple(pairs) if method == "GET" and pairs else None,
            )
        except httpx.HTTPError as exc:
            raise StripeError(503, "network") from exc
    if response.status_code >= 400:
        code = None
        try:
            code = response.json().get("error", {}).get("code")
        except ValueError:
            pass
        raise StripeError(response.status_code, code if isinstance(code, str) else None)
    return response.json()


def verify_webhook(payload: bytes, signature_header: str | None, *, now: float | None = None) -> dict[str, Any]:
    """Return the parsed event or raise ValueError on any signature problem."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret or not signature_header:
        raise ValueError("missing signature")
    timestamp: int | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                raise ValueError("bad timestamp")
        elif key == "v1" and value:
            signatures.append(value)
    if timestamp is None or not signatures:
        raise ValueError("malformed signature")
    current = time.time() if now is None else now
    if abs(current - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        raise ValueError("stale signature")
    expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise ValueError("signature mismatch")
    event = json.loads(payload)
    if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not isinstance(event.get("type"), str):
        raise ValueError("malformed event")
    return event


def subscription_period(subscription: dict[str, Any]) -> tuple[int | None, int | None]:
    """Period bounds live on the subscription (older API versions) or on its items."""
    start = subscription.get("current_period_start")
    end = subscription.get("current_period_end")
    if start is None or end is None:
        items = (subscription.get("items") or {}).get("data") or []
        for item in items:
            if isinstance(item, dict) and item.get("current_period_start") is not None:
                start, end = item.get("current_period_start"), item.get("current_period_end")
                break
    return (int(start) if start is not None else None, int(end) if end is not None else None)


def subscription_has_pro_price(subscription: dict[str, Any]) -> bool:
    price = pro_price_id()
    items = (subscription.get("items") or {}).get("data") or []
    return bool(price) and any(
        isinstance(item, dict) and (item.get("price") or {}).get("id") == price for item in items
    )
