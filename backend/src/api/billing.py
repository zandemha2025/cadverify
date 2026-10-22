"""Self-serve Pro billing through Stripe Checkout.

``router`` (mounted at /api/v1/billing) serves signed-in browser sessions:
plan status, a Checkout link and a billing-portal link. ``webhook_router``
(mounted at /billing) receives Stripe events, verified by signature.

Stripe is the source of truth. Every subscription event re-reads the current
subscription from Stripe before writing, so out-of-order or replayed events
cannot leave a stale plan. Pilot accounts are never changed by billing.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from src.auth.catalog_allowance import free_catalog_parts
from src.auth.email_tiers import personal_checks, work_checks
from src.auth.rate_limit import limiter
from src.auth.require_api_key import AuthedUser, require_api_key
from src.auth.validation_caps import PRO_ACTIVE_STATUSES, pro_monthly_checks
from src.billing.stripe_client import (
    StripeError,
    billing_enabled,
    pro_price_id,
    stripe_request,
    subscription_has_pro_price,
    subscription_period,
    verify_webhook,
)
from src.config.public_urls import dashboard_origin
from src.db.engine import get_session_factory
from src.db.models import BillingAccount, BillingEvent, User

logger = logging.getLogger(__name__)
router = APIRouter()
webhook_router = APIRouter()
MAX_WEBHOOK_BYTES = 1024 * 1024
SUBSCRIPTION_EVENTS = frozenset({
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
})


class ReturnBody(BaseModel):
    """Where Stripe sends the person back. "verify" (the default) is today's app;
    "app" is the v4 app, sent by its Plan and billing page (behind the
    frontend's NEXT_PUBLIC_UI_V4 flag). Only these two fixed paths exist, so the
    caller can't point Stripe anywhere else."""

    return_to: Literal["verify", "app"] = "verify"


_RETURN_PATHS = {
    "verify": {"success": "/verify?upgraded=1", "cancel": "/pricing?checkout=cancelled", "portal": "/history"},
    "app": {"success": "/app?upgraded=1", "cancel": "/app/account/billing?checkout=cancelled", "portal": "/app/account/billing"},
}


def _return_paths(body: ReturnBody | None) -> dict[str, str]:
    return _RETURN_PATHS[(body or ReturnBody()).return_to]


def _problem(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _billing_unavailable() -> HTTPException:
    return _problem(503, "billing_unavailable", "Online checkout isn't available right now. Email us and we'll set up Pro for you.")


def _require_browser_session(user: AuthedUser) -> None:
    # Purchases and the billing portal belong to a signed-in person, not an API key.
    if user.key_prefix != "session":
        raise _problem(403, "browser_session_required", "Open billing from the ScaleCAD web app.")


_PRICE_CACHE: dict[str, tuple[float, dict | None]] = {}
PRICE_CACHE_SECONDS = 600


async def _pro_price() -> dict | None:
    """The Pro price exactly as Stripe will charge it, cached briefly."""
    price_id = pro_price_id()
    cached = _PRICE_CACHE.get(price_id)
    if cached and time.monotonic() - cached[0] < PRICE_CACHE_SECONDS:
        return cached[1]
    try:
        price = await stripe_request("GET", f"/v1/prices/{price_id}")
        recurring = price.get("recurring") or {}
        value = {
            "unit_amount": int(price["unit_amount"]),
            "currency": str(price.get("currency", "usd")),
            "interval": str(recurring.get("interval", "month")),
        }
    except (StripeError, KeyError, TypeError, ValueError):
        logger.warning("billing plans: Stripe price unavailable")
        return None
    _PRICE_CACHE[price_id] = (time.monotonic(), value)
    return value


@webhook_router.get("/plans")
async def public_plans() -> dict:
    """Public plan facts for the pricing and sign-up pages."""
    enabled = billing_enabled()
    return {
        "free": {"work_checks": work_checks(), "personal_checks": personal_checks(),
                 "catalog_parts": free_catalog_parts()},
        "pro": {
            "checkout_available": enabled,
            "monthly_checks": pro_monthly_checks(),
            "price": await _pro_price() if enabled else None,
        },
    }


def _ts(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value is not None else None


@router.get("")
async def billing_status(user: AuthedUser = Depends(require_api_key)) -> dict:
    try:
        async with get_session_factory()() as session:
            plan = (await session.execute(select(User.plan).where(User.id == user.user_id))).scalar_one()
            account = await session.get(BillingAccount, user.user_id)
    except SQLAlchemyError as exc:
        raise _problem(503, "billing_status_unavailable", "Billing status is temporarily unavailable.") from exc
    return {
        "checkout_available": billing_enabled(),
        "plan": plan,
        "status": account.status if account else None,
        "current_period_end": account.current_period_end.isoformat() if account and account.current_period_end else None,
        "manage_available": billing_enabled() and account is not None,
        "pro_monthly_checks": pro_monthly_checks(),
    }


@router.post("/checkout")
@limiter.limit("10/minute;30/hour")
async def create_checkout(
    request: Request,
    response: Response,
    body: ReturnBody | None = None,
    user: AuthedUser = Depends(require_api_key),
) -> dict:
    _require_browser_session(user)
    if not billing_enabled():
        raise _billing_unavailable()
    try:
        async with get_session_factory()() as session:
            row = (await session.execute(select(User.plan, User.email).where(User.id == user.user_id))).one()
            account = await session.get(BillingAccount, user.user_id)
    except SQLAlchemyError as exc:
        raise _billing_unavailable() from exc
    if row.plan == "pilot":
        raise _problem(409, "plan_already_included", "Your account is on a pilot plan, which already includes unlimited checks.")
    if row.plan == "pro" and account is not None and account.status in PRO_ACTIVE_STATUSES:
        raise _problem(409, "already_pro", "You're already on Pro. Manage your plan from billing.")

    try:
        if account is None:
            # The idempotency key makes a double click return the same customer.
            customer = await stripe_request(
                "POST", "/v1/customers",
                {"email": row.email, "metadata": {"scalecad_user_id": user.user_id}},
                idempotency_key=f"scalecad-customer-{user.user_id}",
            )
            customer_id = str(customer["id"])
            async with get_session_factory()() as session, session.begin():
                await session.execute(
                    insert(BillingAccount)
                    .values(user_id=user.user_id, stripe_customer_id=customer_id, status="none")
                    .on_conflict_do_nothing(index_elements=["user_id"])
                )
                account = await session.get(BillingAccount, user.user_id)
            customer_id = account.stripe_customer_id if account else customer_id
        else:
            customer_id = account.stripe_customer_id
        origin = dashboard_origin()
        paths = _return_paths(body)
        checkout = await stripe_request("POST", "/v1/checkout/sessions", {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": str(user.user_id),
            "line_items": [{"price": pro_price_id(), "quantity": 1}],
            "allow_promotion_codes": True,
            "metadata": {"scalecad_user_id": user.user_id},
            "subscription_data": {"metadata": {"scalecad_user_id": user.user_id}},
            "success_url": f"{origin}{paths['success']}",
            "cancel_url": f"{origin}{paths['cancel']}",
        })
    except (StripeError, KeyError, SQLAlchemyError) as exc:
        logger.warning("billing checkout failed: %s", type(exc).__name__)
        raise _billing_unavailable() from exc
    url = checkout.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise _billing_unavailable()
    return {"url": url}


@router.post("/portal")
@limiter.limit("10/minute;30/hour")
async def create_portal(
    request: Request,
    response: Response,
    body: ReturnBody | None = None,
    user: AuthedUser = Depends(require_api_key),
) -> dict:
    _require_browser_session(user)
    if not billing_enabled():
        raise _billing_unavailable()
    try:
        async with get_session_factory()() as session:
            account = await session.get(BillingAccount, user.user_id)
    except SQLAlchemyError as exc:
        raise _billing_unavailable() from exc
    if account is None:
        raise _problem(404, "no_billing_account", "There's no billing on this account yet.")
    try:
        portal = await stripe_request("POST", "/v1/billing_portal/sessions", {
            "customer": account.stripe_customer_id,
            "return_url": f"{dashboard_origin()}{_return_paths(body)['portal']}",
        })
    except StripeError as exc:
        logger.warning("billing portal failed: %s", exc)
        raise _billing_unavailable() from exc
    url = portal.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise _billing_unavailable()
    return {"url": url}


async def _apply_subscription(session, user_id: int, subscription: dict[str, Any]) -> None:
    """Write Stripe's current subscription state and the resulting plan."""
    status = str(subscription.get("status") or "none")
    if not subscription_has_pro_price(subscription):
        status = "not_pro"
    start, end = subscription_period(subscription)
    await session.execute(
        update(BillingAccount).where(BillingAccount.user_id == user_id).values(
            stripe_subscription_id=str(subscription.get("id")) if subscription.get("id") else None,
            status=status,
            current_period_start=_ts(start),
            current_period_end=_ts(end),
            updated_at=datetime.now(timezone.utc),
        )
    )
    active = status in PRO_ACTIVE_STATUSES and start is not None
    await session.execute(
        update(User)
        .where(User.id == user_id, User.plan == ("trial" if active else "pro"))
        .values(plan="pro" if active else "trial")
    )


def _subscription_id(event: dict[str, Any]) -> str | None:
    obj = (event.get("data") or {}).get("object") or {}
    if event["type"] == "checkout.session.completed":
        value = obj.get("subscription")
    elif event["type"] in SUBSCRIPTION_EVENTS:
        value = obj.get("id")
    else:
        return None
    return value if isinstance(value, str) and value.startswith("sub_") else None


@webhook_router.post("/stripe-webhook", include_in_schema=False)
async def stripe_webhook(request: Request) -> dict:
    if not billing_enabled():
        raise _billing_unavailable()
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise _problem(413, "payload_too_large", "Webhook payload too large.")
    # Read with the cap applied as the body arrives, so a body without a
    # Content-Length (chunked) is refused once it passes the limit.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BYTES:
            raise _problem(413, "payload_too_large", "Webhook payload too large.")
    payload = bytes(body)
    try:
        event = verify_webhook(payload, request.headers.get("stripe-signature"))
    except ValueError:
        raise _problem(400, "invalid_signature", "Invalid Stripe signature.")

    subscription_id = _subscription_id(event)
    if subscription_id is None:
        return {"received": True, "handled": False}
    try:
        # Fetch current truth; the event body may be older than another event.
        subscription = await stripe_request("GET", f"/v1/subscriptions/{subscription_id}")
    except StripeError as exc:
        logger.warning("stripe webhook: subscription fetch failed: %s", exc)
        raise _problem(503, "billing_unavailable", "Could not read the subscription. Stripe will retry.")
    customer_id = subscription.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    try:
        async with get_session_factory()() as session, session.begin():
            fresh = (await session.execute(
                insert(BillingEvent).values(event_id=event["id"], event_type=event["type"])
                .on_conflict_do_nothing(index_elements=["event_id"]).returning(BillingEvent.event_id)
            )).first()
            if fresh is None:
                return {"received": True, "duplicate": True}
            account = (await session.execute(
                select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id).with_for_update()
            )).scalar_one_or_none()
            if account is None:
                # Only customers created by our checkout map to accounts.
                logger.warning("stripe webhook: subscription for an unknown customer")
                return {"received": True, "handled": False}
            await _apply_subscription(session, account.user_id, subscription)
    except SQLAlchemyError as exc:
        logger.warning("stripe webhook: database write failed")
        raise _problem(503, "billing_unavailable", "Could not record the subscription. Stripe will retry.") from exc
    return {"received": True, "handled": True}
