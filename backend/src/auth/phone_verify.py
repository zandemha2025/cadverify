"""SMS phone verification for free accounts (Twilio Verify).

Mounted at /api/v1/account/phone. When SMS_VERIFICATION_REQUIRED is on, a
free account must verify a phone before its first check
(src.auth.validation_caps). One number backs one account, which closes the
"new email, new free checks" loop.

Twilio sends and checks the code; we never store codes. Phone numbers are
never logged. Sends are throttled per account, per number and per IP, and
SMS_ALLOWED_PREFIXES (for example "+1,+44") limits destinations.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from functools import lru_cache

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.auth.client_ip import client_ip
from src.auth.redis_util import register_redis_client, require_redis_url
from src.auth.require_api_key import AuthedUser, require_api_key
from src.db.engine import get_session_factory
from src.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter()
TWILIO_VERIFY = "https://verify.twilio.com"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_CODE = re.compile(r"^\d{4,10}$")
# (limit, window seconds)
SEND_LIMITS = {"user": (5, 3600), "phone": (5, 3600), "ip": (10, 3600)}
CHECK_LIMIT = (10, 3600)


class PhoneStartIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)


class PhoneCheckIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)
    code: str = Field(min_length=4, max_length=10)


def _problem(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def sms_configured() -> bool:
    return all(os.getenv(name, "").strip() for name in
               ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"))


def normalize_phone(raw: str) -> str | None:
    """Return E.164 or None. Ten-digit numbers are read as North American."""
    text = raw.strip()
    plus = text.startswith("+") or text.startswith("00")
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    if not plus:
        if len(digits) == 10:
            digits = "1" + digits
        elif not (len(digits) == 11 and digits.startswith("1")):
            return None
    candidate = f"+{digits}"
    return candidate if _E164.match(candidate) else None


def _allowed_destination(phone: str) -> bool:
    prefixes = [p.strip() for p in os.getenv("SMS_ALLOWED_PREFIXES", "").split(",") if p.strip()]
    return not prefixes or any(phone.startswith(prefix) for prefix in prefixes)


def _verify_base() -> str:
    override = os.getenv("TWILIO_VERIFY_BASE", "").strip().rstrip("/")
    return override if override and not os.getenv("RELEASE") else TWILIO_VERIFY


@lru_cache(maxsize=1)
def _r() -> aioredis.Redis:
    client = aioredis.from_url(require_redis_url(), decode_responses=True)
    return register_redis_client(client, _r.cache_clear)


async def _hit(key: str, limit: int, window: int) -> None:
    r = _r()
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, window)
    if count > limit:
        raise _problem(429, "phone_rate_limited", "Too many code requests. Wait a few minutes and try again.")


async def _twilio(path: str, data: dict[str, str]) -> dict:
    service = os.environ["TWILIO_VERIFY_SERVICE_SID"].strip()
    auth = (os.environ["TWILIO_ACCOUNT_SID"].strip(), os.environ["TWILIO_AUTH_TOKEN"].strip())
    async with httpx.AsyncClient(base_url=_verify_base(), timeout=_TIMEOUT, auth=auth) as client:
        try:
            response = await client.post(f"/v2/Services/{service}/{path}", data=data)
        except httpx.HTTPError as exc:
            raise _problem(503, "sms_unavailable", "We couldn't send a text right now. Try again shortly.") from exc
    if response.status_code == 404 and path == "VerificationCheck":
        # Twilio returns 404 once a verification expired or was used up.
        return {"status": "expired"}
    if response.status_code == 429:
        raise _problem(429, "phone_rate_limited", "Too many code requests. Wait a few minutes and try again.")
    if response.status_code == 400:
        raise _problem(400, "phone_not_supported", "We can't send a code to that number. Check it, or try a mobile number.")
    if response.status_code >= 400:
        logger.warning("twilio verify %s failed with %s", path, response.status_code)
        raise _problem(503, "sms_unavailable", "We couldn't send a text right now. Try again shortly.")
    return response.json()


async def _phone_owner(phone: str) -> int | None:
    async with get_session_factory()() as session:
        return (await session.execute(select(User.id).where(User.verified_phone == phone))).scalar_one_or_none()


def _session_user(user: AuthedUser) -> None:
    if user.key_prefix != "session":
        raise _problem(403, "browser_session_required", "Verify your phone from the ScaleCAD web app.")


@router.post("/start")
async def phone_start(body: PhoneStartIn, request: Request, user: AuthedUser = Depends(require_api_key)) -> dict:
    _session_user(user)
    if not sms_configured():
        raise _problem(503, "sms_unavailable", "Phone verification isn't available right now.")
    phone = normalize_phone(body.phone)
    if phone is None:
        raise _problem(400, "invalid_phone", "Enter a mobile number with its country code, like +1 555 123 4567.")
    if not _allowed_destination(phone):
        raise _problem(400, "phone_not_supported", "We can't send codes to that country yet. Email us and we'll help.")
    try:
        owner = await _phone_owner(phone)
    except SQLAlchemyError as exc:
        raise _problem(503, "sms_unavailable", "Phone verification isn't available right now.") from exc
    if owner == user.user_id:
        return {"status": "verified"}
    if owner is not None:
        raise _problem(409, "phone_in_use", "That number is already linked to another ScaleCAD account.")
    await _hit(f"phone:send:user:{user.user_id}", *SEND_LIMITS["user"])
    await _hit(f"phone:send:num:{hashlib.sha256(phone.encode()).hexdigest()[:32]}", *SEND_LIMITS["phone"])
    await _hit(f"phone:send:ip:{client_ip(request)}", *SEND_LIMITS["ip"])
    await _twilio("Verifications", {"To": phone, "Channel": "sms"})
    return {"status": "pending"}


@router.post("/check")
async def phone_check(body: PhoneCheckIn, user: AuthedUser = Depends(require_api_key)) -> dict:
    _session_user(user)
    if not sms_configured():
        raise _problem(503, "sms_unavailable", "Phone verification isn't available right now.")
    phone = normalize_phone(body.phone)
    code = body.code.strip()
    if phone is None or not _CODE.match(code):
        raise _problem(400, "invalid_code", "That code didn't work. Check it and try again.")
    await _hit(f"phone:check:user:{user.user_id}", *CHECK_LIMIT)
    result = await _twilio("VerificationCheck", {"To": phone, "Code": code})
    if result.get("status") == "expired":
        raise _problem(400, "code_expired", "That code expired. Send a new one.")
    if result.get("status") != "approved":
        raise _problem(400, "invalid_code", "That code didn't work. Check it and try again.")
    try:
        async with get_session_factory()() as session, session.begin():
            await session.execute(
                update(User).where(User.id == user.user_id)
                .values(verified_phone=phone, phone_verified_at=datetime.now(timezone.utc))
            )
    except IntegrityError as exc:
        raise _problem(409, "phone_in_use", "That number is already linked to another ScaleCAD account.") from exc
    except SQLAlchemyError as exc:
        raise _problem(503, "sms_unavailable", "Phone verification isn't available right now.") from exc
    return {"status": "verified"}

