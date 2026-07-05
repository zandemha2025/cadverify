"""Tests for the email + password auth router (src.auth.password).

Two layers:
  * Pure unit tests (no DB): Argon2 hashing, password policy, email shape, and
    the require_api_key dashboard-session cookie fallback.
  * One self-contained async integration test exercising the full flow
    (signup -> duplicate -> weak -> login -> me -> protected) against the real
    local Postgres. Skipped automatically when DATABASE_URL is not a Postgres
    URL, because the helpers use `ON CONFLICT ... RETURNING` + `email_lower`
    semantics that sqlite does not reproduce.

Run the integration test with:
    DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/cadverify \
        .venv/bin/python -m pytest tests/test_auth_password.py -q
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI, HTTPException

from src.auth.dashboard_session import sign
from src.auth.hashing import (
    hash_password,
    password_needs_rehash,
    verify_password,
)
from src.auth.password import _clean_email, _validate_password

_PG = os.environ.get("DATABASE_URL", "").startswith("postgresql")
_requires_pg = pytest.mark.skipif(
    not _PG, reason="requires local Postgres (set DATABASE_URL=postgresql://...)"
)


# ──────────────────────────────────────────────────────────────
# Argon2 password hashing — no DB
# ──────────────────────────────────────────────────────────────


def test_hash_password_is_argon2id_not_plaintext():
    h = hash_password("Passw0rd!")
    assert h != "Passw0rd!"
    assert h.startswith("$argon2id$")
    # Salt is random: two hashes of the same password differ.
    assert hash_password("Passw0rd!") != h


def test_verify_password_roundtrip():
    h = hash_password("Sup3rSecret")
    assert verify_password(h, "Sup3rSecret") is True
    assert verify_password(h, "wrong-password") is False


def test_verify_password_never_raises_on_garbage():
    assert verify_password("not-a-real-hash", "whatever") is False
    assert verify_password("", "x") is False


def test_password_needs_rehash_returns_bool():
    assert password_needs_rehash(hash_password("Passw0rd")) is False


# ──────────────────────────────────────────────────────────────
# Password policy + email shape — no DB
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pw",
    [
        "short1",          # < 8
        "alllettersxyz",   # no digit
        "12345678",        # no letter
        "a1" + "x" * 130,  # > 128
    ],
)
def test_validate_password_rejects_weak(pw):
    with pytest.raises(HTTPException) as exc:
        _validate_password(pw)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "weak_password"


def test_validate_password_accepts_policy_valid():
    # No exception => valid.
    _validate_password("Passw0rd")
    _validate_password("a1bcdefg")


def test_clean_email_trims_and_validates():
    assert _clean_email("  USER@Example.com ") == "USER@Example.com"
    for bad in ["", "no-at-sign", "a@b", "a@@b.com", "a b@c.com"]:
        with pytest.raises(HTTPException) as exc:
            _clean_email(bad)
        assert exc.value.detail["code"] == "invalid_email"


# ──────────────────────────────────────────────────────────────
# require_api_key dashboard-session cookie fallback — no DB
# (lookup_user_role mocked, like test_require_api_key.py)
# ──────────────────────────────────────────────────────────────


class _Req:
    def __init__(self, cookies=None):
        self.client = type("C", (), {"host": "1.2.3.4"})()
        self.state = type("S", (), {})()
        self.cookies = cookies or {}


@pytest.mark.asyncio
async def test_require_api_key_accepts_session_cookie(monkeypatch):
    from src.auth import require_api_key as rak

    monkeypatch.setattr(rak, "lookup_user_role", AsyncMock(return_value="analyst"))
    # §39 added an account-active check on the session-cookie path. This is a
    # no-DB unit test (like test_require_api_key.py) — mock the active read too,
    # else it opens the global engine and binds its asyncpg pool to THIS test's
    # event loop, poisoning the next live-PG test (a stale cross-loop pool).
    monkeypatch.setattr(rak, "user_is_active", AsyncMock(return_value=True))
    req = _Req(cookies={"dash_session": sign(7)})
    user = await rak.require_api_key(req, authorization=None)
    assert user.user_id == 7
    assert user.api_key_id == 0          # session sentinel
    assert user.key_prefix == "session"
    assert user.role == "analyst"
    assert req.state.authed_user is user


@pytest.mark.asyncio
async def test_require_api_key_rejects_bad_session_cookie():
    from src.auth import require_api_key as rak

    with pytest.raises(HTTPException) as exc:
        await rak.require_api_key(
            _Req(cookies={"dash_session": "tampered.garbage"}), authorization=None
        )
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_missing"


@pytest.mark.asyncio
async def test_require_api_key_rejects_no_credential():
    from src.auth import require_api_key as rak

    with pytest.raises(HTTPException) as exc:
        await rak.require_api_key(_Req(), authorization=None)
    assert exc.value.detail["code"] == "auth_missing"


# ──────────────────────────────────────────────────────────────
# Full integration flow against real Postgres
# ──────────────────────────────────────────────────────────────


def _build_app() -> FastAPI:
    from src.auth.password import router as password_router
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.include_router(password_router, prefix="/auth")

    @app.get("/protected")
    async def protected(user: AuthedUser = Depends(require_api_key)):  # noqa: ANN001
        return {
            "user_id": user.user_id,
            "api_key_id": user.api_key_id,
            "role": user.role,
        }

    return app


@_requires_pg
@pytest.mark.asyncio
async def test_full_signup_login_me_protected_flow():
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text

    import src.db.engine as eng
    from src.auth.disposable import normalize_email

    email = f"pwtest-{uuid.uuid4().hex[:12]}@example.com"
    email_norm = normalize_email(email)
    password = "Passw0rd123"
    app = _build_app()
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. signup -> 200 + token + user
            r = await ac.post(
                "/auth/signup", json={"email": email, "password": password}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            token = body["session"]
            assert token
            uid = body["user"]["id"]
            assert body["user"]["role"] == "analyst"

            # Argon2 hash persisted, NOT plaintext.
            async with eng.get_session_factory()() as s:
                row = (
                    await s.execute(
                        text(
                            "SELECT password_hash, auth_provider FROM users "
                            "WHERE id = :u"
                        ),
                        {"u": uid},
                    )
                ).first()
            assert row is not None
            assert row[0].startswith("$argon2id$")
            assert password not in row[0]
            assert row[1] == "password"

            # 2. duplicate email -> 409
            r = await ac.post(
                "/auth/signup", json={"email": email, "password": password}
            )
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "email_taken"

            # 3. weak password -> 400
            r = await ac.post(
                "/auth/signup",
                json={"email": f"x-{uuid.uuid4().hex[:8]}@example.com", "password": "weak"},
            )
            assert r.status_code == 400
            assert r.json()["detail"]["code"] == "weak_password"

            # 4. login wrong password -> 401 generic
            r = await ac.post(
                "/auth/login", json={"email": email, "password": "WrongPass99"}
            )
            assert r.status_code == 401
            assert r.json()["detail"]["code"] == "invalid_credentials"

            # 5. login success -> 200 + token
            r = await ac.post(
                "/auth/login", json={"email": email, "password": password}
            )
            assert r.status_code == 200, r.text
            login_token = r.json()["session"]
            assert login_token

            # 6. /auth/me with cookie -> 200 user
            r = await ac.get(
                "/auth/me", headers={"Cookie": f"dash_session={login_token}"}
            )
            assert r.status_code == 200, r.text
            me = r.json()
            assert me["id"] == uid
            assert me["email"] == email
            assert me["auth_provider"] == "password"

            # 7. /auth/me WITHOUT cookie -> 401
            r = await ac.get("/auth/me")
            assert r.status_code == 401
            assert r.json()["detail"]["code"] == "dashboard_auth_required"

            # 8. protected route accepts the session cookie (api_key_id=0)
            r = await ac.get(
                "/protected", headers={"Cookie": f"dash_session={login_token}"}
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_key_id"] == 0
            assert r.json()["user_id"] == uid

            # 9. protected route WITHOUT any credential -> 401
            r = await ac.get("/protected")
            assert r.status_code == 401
            assert r.json()["detail"]["code"] == "auth_missing"

            # 10. logout -> 200 ok
            r = await ac.post("/auth/logout")
            assert r.status_code == 200
            assert r.json()["ok"] is True
    finally:
        # Clean up the test user + dispose the engine (same loop).
        try:
            async with eng.get_session_factory()() as s:
                await s.execute(
                    text("DELETE FROM users WHERE email_lower = :el"),
                    {"el": email_norm},
                )
                await s.commit()
        finally:
            await eng.dispose_engine()
