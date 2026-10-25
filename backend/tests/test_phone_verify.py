"""SMS phone verification: one number per account, throttled, never stored codes.

Real PostgreSQL schema (DATABASE_URL), fakeredis throttles, Twilio mocked.
"""
import os
from urllib.parse import parse_qs
from uuid import uuid4

import fakeredis.aioredis as far
import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.auth import phone_verify as pv
from src.auth.require_api_key import AuthedUser, require_api_key

VERIFY = "https://verify.twilio.com/v2/Services/VA_test"


@pytest_asyncio.fixture
async def db(monkeypatch):
    url = os.environ.get("DATABASE_URL", "")
    assert url.startswith("postgresql"), "Set DATABASE_URL to local/CI PostgreSQL to test phone verification."
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    schema = "phone_test_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE users (id bigint PRIMARY KEY, phone text, verified_phone text, phone_verified_at timestamptz)"))
            await connection.execute(text("CREATE UNIQUE INDEX uq_phone ON users (verified_phone) WHERE verified_phone IS NOT NULL"))
            await connection.execute(text("INSERT INTO users (id) VALUES (1), (2)"))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(pv, "get_session_factory", lambda: factory)
        fake = far.FakeRedis(decode_responses=True)
        monkeypatch.setattr(pv, "_r", lambda: fake)
        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token_test")
        monkeypatch.setenv("TWILIO_VERIFY_SERVICE_SID", "VA_test")
        monkeypatch.delenv("SMS_ALLOWED_PREFIXES", raising=False)
        monkeypatch.delenv("TWILIO_VERIFY_BASE", raising=False)
        yield factory
        await fake.aclose()
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin.dispose()


def _client(user_id: int = 1, prefix: str = "session") -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(pv.router, prefix="/api/v1/account/phone")
    app.dependency_overrides[require_api_key] = lambda: AuthedUser(user_id=user_id, api_key_id=0, key_prefix=prefix)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _phone(db, user_id):
    async with db() as session:
        return (await session.execute(text("SELECT verified_phone FROM users WHERE id = :id"), {"id": user_id})).scalar_one()


@pytest.mark.asyncio
@respx.mock
async def test_send_check_and_link_one_number_to_one_account(db):
    send = respx.post(f"{VERIFY}/Verifications").mock(return_value=httpx.Response(201, json={"status": "pending"}))
    check = respx.post(f"{VERIFY}/VerificationCheck").mock(side_effect=[
        httpx.Response(200, json={"status": "pending"}),
        httpx.Response(200, json={"status": "approved"}),
    ])
    async with _client() as client:
        started = await client.post("/api/v1/account/phone/start", json={"phone": "(555) 123-4567"})
        assert started.json() == {"status": "pending"}
        form = parse_qs(send.calls[0].request.content.decode())
        assert form == {"To": ["+15551234567"], "Channel": ["sms"]}
        assert send.calls[0].request.headers["Authorization"].startswith("Basic ")
        wrong = await client.post("/api/v1/account/phone/check", json={"phone": "+1 555 123 4567", "code": "000000"})
        assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "invalid_code"
        right = await client.post("/api/v1/account/phone/check", json={"phone": "+1 555 123 4567", "code": "123456"})
        assert right.json() == {"status": "verified"}
        assert parse_qs(check.calls[1].request.content.decode()) == {"To": ["+15551234567"], "Code": ["123456"]}
        # The owner asking again is a no-op, without another text.
        again = await client.post("/api/v1/account/phone/start", json={"phone": "+15551234567"})
        assert again.json() == {"status": "verified"} and send.call_count == 1
    assert await _phone(db, 1) == "+15551234567"
    async with _client(user_id=2) as client:
        taken = await client.post("/api/v1/account/phone/start", json={"phone": "555-123-4567"})
    assert taken.status_code == 409 and taken.json()["detail"]["code"] == "phone_in_use"
    assert send.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_verification_of_one_number_links_only_one_account(db):
    respx.post(f"{VERIFY}/VerificationCheck").mock(return_value=httpx.Response(200, json={"status": "approved"}))
    async with _client(1) as first, _client(2) as second:
        ok = await first.post("/api/v1/account/phone/check", json={"phone": "+447700900123", "code": "123456"})
        raced = await second.post("/api/v1/account/phone/check", json={"phone": "+447700900123", "code": "654321"})
    assert ok.json() == {"status": "verified"}
    assert raced.status_code == 409 and raced.json()["detail"]["code"] == "phone_in_use"
    assert await _phone(db, 2) is None


@pytest.mark.asyncio
@respx.mock
async def test_throttles_country_limits_and_expired_codes(db, monkeypatch):
    send = respx.post(f"{VERIFY}/Verifications").mock(return_value=httpx.Response(201, json={"status": "pending"}))
    respx.post(f"{VERIFY}/VerificationCheck").mock(return_value=httpx.Response(404, json={"code": 20404}))
    async with _client() as client:
        for _ in range(5):
            assert (await client.post("/api/v1/account/phone/start", json={"phone": "+15551230000"})).status_code == 200
        limited = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230000"})
        assert limited.status_code == 429 and limited.json()["detail"]["code"] == "phone_rate_limited"
        expired = await client.post("/api/v1/account/phone/check", json={"phone": "+15551230000", "code": "123456"})
        assert expired.json()["detail"]["code"] == "code_expired"
    assert send.call_count == 5
    monkeypatch.setenv("SMS_ALLOWED_PREFIXES", "+1, +966")
    async with _client(user_id=2) as client:
        blocked = await client.post("/api/v1/account/phone/start", json={"phone": "+447700900123"})
    assert blocked.status_code == 400 and blocked.json()["detail"]["code"] == "phone_not_supported"
    assert send.call_count == 5


@pytest.mark.asyncio
async def test_refuses_api_keys_bad_input_and_missing_configuration(db, monkeypatch):
    async with _client(prefix="cv_live_abc") as client:
        key = await client.post("/api/v1/account/phone/start", json={"phone": "+15551234567"})
    assert key.status_code == 403
    async with _client() as client:
        bad = await client.post("/api/v1/account/phone/start", json={"phone": "12345"})
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "invalid_phone"
        monkeypatch.delenv("TWILIO_AUTH_TOKEN")
        off = await client.post("/api/v1/account/phone/start", json={"phone": "+15551234567"})
    assert off.status_code == 503 and off.json()["detail"]["code"] == "sms_unavailable"


@pytest.mark.parametrize("raw,expected", [
    ("+1 (555) 123-4567", "+15551234567"),
    ("5551234567", "+15551234567"),
    ("1-555-123-4567", "+15551234567"),
    ("0044 7700 900123", "+447700900123"),
    ("+966 50 123 4567", "+966501234567"),
    ("123", None),
    ("+0 555 123 4567", None),
    ("07700 900123", None),  # national format without a country code is ambiguous
    ("+1555123456789012", None),
])
def test_normalize_phone(raw, expected):
    assert pv.normalize_phone(raw) == expected


@pytest.mark.asyncio
@respx.mock
async def test_phone_check_fills_in_the_number_typed_at_signup(db):
    async with db() as session, session.begin():
        await session.execute(text("UPDATE users SET phone = '(616) 555-0142' WHERE id = 1"))
    async with _client(1) as client:
        assert (await client.get("/api/v1/account/phone")).json() == {"phone": "+16165550142", "verified": False}
    async with _client(2) as client:
        assert (await client.get("/api/v1/account/phone")).json() == {"phone": None, "verified": False}
    async with _client(1, prefix="cv_live") as client:
        refused = await client.get("/api/v1/account/phone")
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "browser_session_required"

    respx.post(f"{VERIFY}/Verifications").mock(return_value=httpx.Response(201, json={"status": "pending"}))
    respx.post(f"{VERIFY}/VerificationCheck").mock(return_value=httpx.Response(200, json={"status": "approved"}))
    async with _client(1) as client:
        assert (await client.post("/api/v1/account/phone/start", json={"phone": "+1 616 555 0142"})).status_code == 200
        assert (await client.post("/api/v1/account/phone/check", json={"phone": "+1 616 555 0142", "code": "123456"})).status_code == 200
        assert (await client.get("/api/v1/account/phone")).json() == {"phone": "+16165550142", "verified": True}


async def _count(key_part: str) -> dict[str, int]:
    fake = pv._r()
    keys = await fake.keys(f"phone:*{key_part}*")
    return {k: int(await fake.get(k)) for k in keys}


@pytest.mark.asyncio
@respx.mock
async def test_a_refused_request_counts_toward_nothing(db):
    """it-01: a refusal (per-number limit) must not eat the account's or the network's allowance."""
    send = respx.post(f"{VERIFY}/Verifications").mock(return_value=httpx.Response(201, json={"status": "pending"}))
    async with _client() as client:
        for _ in range(5):
            assert (await client.post("/api/v1/account/phone/start", json={"phone": "+15551230001"})).status_code == 200
        for _ in range(4):
            refused = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230001"})
            assert refused.status_code == 429 and refused.json()["detail"]["limit"] == "phone"
        user = await _count("user:1")
        ip = await _count("send:ip:")
        assert list(user.values()) == [5] and list(ip.values()) == [5]
        # The account still has its own allowance for a corrected number.
        for _ in range(3):
            assert (await client.post("/api/v1/account/phone/start", json={"phone": "+15551230002"})).status_code == 200
        over = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230003"})
        assert over.status_code == 429 and over.json()["detail"]["limit"] == "user"
    assert send.call_count == 8


@pytest.mark.asyncio
@respx.mock
async def test_the_refusal_gives_the_real_wait(db):
    respx.post(f"{VERIFY}/Verifications").mock(return_value=httpx.Response(201, json={"status": "pending"}))
    async with _client() as client:
        for _ in range(5):
            await client.post("/api/v1/account/phone/start", json={"phone": "+15551230004"})
        (key,) = [k for k in (await pv._r().keys("phone:send:num:*"))]
        await pv._r().expire(key, 9 * 60 - 5)
        refused = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230004"})
    detail = refused.json()["detail"]
    assert refused.status_code == 429
    assert detail["message"] == "Too many codes sent to this number. Try again in 9 minutes."
    assert "few minutes" not in detail["message"]
    assert 500 <= detail["retry_after_seconds"] <= 540 and refused.headers["retry-after"] == str(detail["retry_after_seconds"])


@pytest.mark.asyncio
@respx.mock
async def test_an_office_behind_one_address_can_verify_together(db):
    """30 colleagues behind one NAT each get their code; the per-IP limit is 60 an hour."""
    send = respx.post(f"{VERIFY}/Verifications").mock(return_value=httpx.Response(201, json={"status": "pending"}))
    for i in range(30):
        async with _client(user_id=100 + i) as client:
            r = await client.post("/api/v1/account/phone/start", json={"phone": f"+1555124{i:04d}"})
            assert r.status_code == 200, r.text
    assert send.call_count == 30
    assert pv._ip_limit() == (60, 3600)


@pytest.mark.asyncio
@respx.mock
async def test_a_send_twilio_refuses_gives_its_slot_back(db):
    respx.post(f"{VERIFY}/Verifications").mock(side_effect=[
        httpx.Response(503, json={}),
        httpx.Response(429, json={"code": 60203}),
        httpx.Response(201, json={"status": "pending"}),
    ])
    async with _client() as client:
        failed = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230005"})
        assert failed.status_code == 503
        provider = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230005"})
        assert provider.status_code == 429
        assert provider.json()["detail"]["message"].endswith("Try again in 10 minutes.")
        assert set((await _count("user:1")).values()) == {0}
        ok = await client.post("/api/v1/account/phone/start", json={"phone": "+15551230005"})
        assert ok.status_code == 200
        assert list((await _count("user:1")).values()) == [1]
