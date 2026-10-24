"""Email-link sign-in: the link reaches only the account it signs into, and the
legacy GET never sets a session for an account that owes a two-step code.

Security review R1:

- R1-1: ``POST /auth/magic/start`` mailed the link to the address as typed but
  minted it for ``normalize_email(...)``, which drops "+tag" on every domain. A
  link mailed to victim+x@corp signed into victim@corp, so whoever reads the
  "+x" mailbox (a catch-all, a literal-"+" mail system) took the account. The
  link now goes to the normalised address, and the answer names it.
- R1-5: the legacy ``GET /auth/magic/verify`` set ``dash_session`` for whatever
  ``_consume`` returned, even a result carrying a two-step challenge.

Live Postgres and Redis (``REDIS_URL``); only Turnstile and the email provider
are stubbed.
"""
from __future__ import annotations

import os

import httpx
import pytest
from fastapi import Depends, FastAPI

from tests.test_two_step import World, _cleanup, _cookie, _enrol, _signup, clock, env  # noqa: F401

_LIVE = os.environ.get("DATABASE_URL", "").startswith("postgresql") and bool(os.environ.get("REDIS_URL"))
requires_live = pytest.mark.skipif(not _LIVE, reason="requires Postgres and Redis (DATABASE_URL, REDIS_URL)")


def _app() -> FastAPI:
    from src.auth.magic_link import router as magic_router
    from src.auth.password import router as password_router
    from src.auth.require_api_key import AuthedUser, require_api_key

    app = FastAPI()
    app.include_router(password_router, prefix="/auth")
    app.include_router(magic_router, prefix="/auth")

    @app.get("/protected")
    async def protected(user: AuthedUser = Depends(require_api_key)):  # noqa: ANN001
        return {"user_id": user.user_id}

    return app


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t")


@pytest.fixture
def mail(monkeypatch):
    """Every email the start route sends, with Turnstile and soft flags stubbed."""
    import src.auth.magic_link as ml
    import src.auth.signup_limits as sl

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM", "ScaleCAD <login@cadverify.com>")
    ml._r.cache_clear()
    sl._r.cache_clear()

    async def ok(*_a, **_k):
        return None

    async def no_soft():
        return set()

    sent: list[dict] = []
    monkeypatch.setattr(ml, "verify_turnstile", ok)
    monkeypatch.setattr(ml, "get_soft_flag_set", no_soft)
    monkeypatch.setattr(ml.resend.Emails, "send", lambda payload: sent.append(payload) or {"id": "x"})
    yield sent
    ml._r.cache_clear()
    sl._r.cache_clear()


@requires_live
@pytest.mark.asyncio
async def test_email_link_for_a_plus_address_never_signs_into_the_base_account(env, mail):
    w = World()
    try:
        async with _client() as ac:
            victim_email = w.email("victim")
            victim_id, _ = await _signup(ac, victim_email)  # an existing account, no two-step
            local, domain = victim_email.split("@")
            other_mailbox = f"{local}+x@{domain}"  # a DIFFERENT mailbox
            w.emails.append(other_mailbox)
            r = await ac.post("/auth/magic/start", data={"email": other_mailbox, "cf_turnstile_response": "t"})
            assert r.status_code == 200, r.text
            # The link signs into victim@...; so it goes there, and the answer says so.
            assert r.json() == {"status": "sent", "sent_to": victim_email}
            assert [p["to"] for p in mail] == [victim_email], f"a link for {victim_email} was mailed to {mail[-1]['to']}"
            assert other_mailbox not in repr(mail)
            # Whoever holds the link reads the base mailbox: it opens that account, and only that one.
            token = mail[-1]["text"].split("#token=", 1)[1].split("&", 1)[0].strip()
            r = await ac.post("/auth/magic/exchange", json={"token": token})
            assert r.status_code == 200, r.text
            who = (await ac.get("/auth/me", headers=_cookie(r.json()["session"]))).json()
            assert who["id"] == victim_id and who["email"] == victim_email
    finally:
        await _cleanup(w)


@requires_live
@pytest.mark.asyncio
async def test_legacy_magic_verify_never_sets_a_session_for_an_account_that_owes_a_code(env, clock, mail, monkeypatch):
    """magic_verify checks _owes_two_step() and then _consume(); if the account's
    state changes between the two (or the pre-check is wrong), _consume returns a
    MagicLogin carrying a challenge. That result never becomes a cookie."""
    import src.auth.magic_link as ml

    w = World()
    try:
        async with _client() as ac:
            email = w.email("pat")
            _uid, s0 = await _signup(ac, email)
            await _enrol(ac, s0, clock)  # two-step ON: every sign-in owes a code
            norm = email.lower()
            token = ml._mint(norm)
            await ml._rotate_magic_token(ml._r(), ml._active_token_key(norm), ml._token_key(token, norm), ml.magic_generation_key(norm))

            async def stale_precheck(_token):  # the state read before _consume
                return False

            monkeypatch.setattr(ml, "_owes_two_step", stale_precheck)
            r = await ac.get("/auth/magic/verify", params={"token": token}, follow_redirects=False)
            assert r.status_code == 303
            assert r.headers["location"].endswith("/login"), r.headers["location"]
            assert "dash_session" not in r.headers.get("set-cookie", ""), "a session without the code"
            assert r.cookies.get("dash_session") is None
    finally:
        await _cleanup(w)
