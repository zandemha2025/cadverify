"""/auth/logout ends the session on the server, not only the browser cookie."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_auth_password import _build_app, _requires_pg


@pytest.mark.asyncio
async def test_logout_answers_503_and_still_clears_the_cookie_when_the_account_cant_be_read(monkeypatch):
    from src.auth import password
    from src.auth.dashboard_session import sign

    monkeypatch.setattr(password, "lookup_session_user", AsyncMock(side_effect=RuntimeError("db down")))
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as ac:
        r = await ac.post("/auth/logout", headers={"Cookie": f"dash_session={sign(7)}"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "logout_unavailable"
    assert "dash_session=" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_logout_without_a_session_only_clears_the_cookie(monkeypatch):
    from src.auth import password

    bump = AsyncMock()
    monkeypatch.setattr(password, "bump_session_version", bump)
    async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as ac:
        r = await ac.post("/auth/logout")
        forged = await ac.post("/auth/logout", headers={"Cookie": "dash_session=not-a-session"})
    assert r.status_code == 200 and r.json() == {"ok": True, "session_ended": False}
    assert forged.status_code == 200 and forged.json()["session_ended"] is False
    bump.assert_not_awaited()


@_requires_pg
@pytest.mark.asyncio
async def test_a_copied_cookie_stops_working_after_logout(monkeypatch):
    from sqlalchemy import text

    import src.db.engine as eng
    from src.auth.disposable import normalize_email

    email = f"logout-{uuid.uuid4().hex[:12]}@example.com"
    monkeypatch.setenv("SIGNUP_RATE_LIMIT_DISABLED", "1")
    monkeypatch.delenv("RELEASE", raising=False)
    eng._ENGINE = None
    eng._SESSION_FACTORY = None
    try:
        async with AsyncClient(transport=ASGITransport(app=_build_app()), base_url="http://test") as ac:
            r = await ac.post("/auth/signup", json={"email": email, "password": "Passw0rd123"})
            assert r.status_code == 200, r.text
            token = r.json()["session"]
            cookie = {"Cookie": f"dash_session={token}"}
            assert (await ac.get("/protected", headers=cookie)).status_code == 200

            out = await ac.post("/auth/logout", headers=cookie)
            assert out.status_code == 200
            assert out.json() == {"ok": True, "session_ended": True}
            assert "dash_session=" in out.headers.get("set-cookie", "")

            replay = await ac.get("/protected", headers=cookie)
            assert replay.status_code == 401
            assert replay.json()["detail"]["code"] == "session_revoked"

            # The ended cookie can't end the next session.
            again = await ac.post("/auth/login", json={"email": email, "password": "Passw0rd123"})
            fresh = {"Cookie": f"dash_session={again.json()['session']}"}
            stale = await ac.post("/auth/logout", headers=cookie)
            assert stale.status_code == 200 and stale.json()["session_ended"] is False
            assert (await ac.get("/protected", headers=fresh)).status_code == 200

            # /logout-all keeps working.
            assert (await ac.post("/auth/logout-all", headers=fresh)).status_code == 200
            assert (await ac.get("/protected", headers=fresh)).status_code == 401
    finally:
        try:
            async with eng.get_session_factory()() as s:
                uid = (await s.execute(text("SELECT id FROM users WHERE email_lower = :e"), {"e": normalize_email(email)})).scalar()
                if uid is not None:
                    orgs = (await s.execute(text("SELECT org_id FROM memberships WHERE user_id = :u"), {"u": uid})).scalars().all()
                    for table in ("audit_log", "api_keys", "memberships"):
                        await s.execute(text(f"DELETE FROM {table} WHERE user_id = :u"), {"u": uid})  # fixed names
                    await s.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
                    for org in orgs:
                        await s.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
                await s.commit()
        finally:
            await eng.dispose_engine()
