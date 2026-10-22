def _collect_route_paths(routes, prefix=""):
    paths = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(f"{prefix}{path}")

        nested = getattr(route, "routes", None)
        if nested:
            paths.update(
                _collect_route_paths(nested, f"{prefix}{getattr(route, 'prefix', '')}")
            )

    return paths


def test_oauth_router_importable():
    from src.auth.oauth import router
    paths = _collect_route_paths(router.routes)
    assert "/google/start" in paths
    assert "/google/callback" in paths


def test_magic_router_importable():
    from src.auth.magic_link import router
    paths = _collect_route_paths(router.routes)
    assert "/magic/start" in paths
    assert "/magic/verify" in paths


def test_main_wires_auth_routers():
    import os
    from unittest.mock import AsyncMock, patch

    os.environ.setdefault("SESSION_SECRET", "test-only")
    import importlib
    from fastapi.responses import RedirectResponse
    from fastapi.testclient import TestClient

    import main as mainmod
    importlib.reload(mainmod)

    # Hermetic: /auth/google/start would otherwise call authlib's
    # authorize_redirect, which performs a REAL network GET to
    # https://accounts.google.com/.well-known/openid-configuration
    # (OIDC discovery, via server_metadata_url) before it can even build the
    # redirect — independent of whether the test client follows redirects.
    # Mock the authlib call so this route-existence check never touches the
    # network, and disable follow_redirects as defense in depth so a 302 to
    # a real external host is never dereferenced by the test client either.
    with patch(
        "src.auth.oauth.oauth.google.authorize_redirect", new_callable=AsyncMock
    ) as mock_authorize_redirect:
        mock_authorize_redirect.return_value = RedirectResponse(
            "https://accounts.google.com/mock-authorize", status_code=302
        )
        client = TestClient(
            mainmod.app, raise_server_exceptions=False, follow_redirects=False
        )
        assert client.get("/auth/google/start").status_code != 404
        mock_authorize_redirect.assert_awaited_once()

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.get("/auth/google/callback").status_code != 404
    assert client.post("/auth/magic/start").status_code != 404
    assert client.get("/auth/magic/verify").status_code != 404


def test_password_mode_with_magic_config_mounts_magic_without_google(monkeypatch):
    """Launch config: AUTH_MODE=password + the magic-link trio configured
    (RESEND_API_KEY/MAGIC_LINK_SECRET/DASHBOARD_ORIGIN) must mount
    /auth/magic/* WITHOUT any Google credentials — magic-link is decoupled
    from AUTH_MODE (see main._magic_link_enabled)."""
    import importlib

    from fastapi.testclient import TestClient

    import main as mainmod

    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    # MAGIC_LINK_SECRET and DASHBOARD_ORIGIN are already set to valid values
    # by the autouse _auth_env fixture in conftest.py.
    importlib.reload(mainmod)

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.post("/auth/magic/start").status_code != 404
    assert client.get("/auth/magic/verify").status_code != 404
    # Google is NOT mounted — password+magic must not require it.
    assert client.get("/auth/google/start").status_code == 404
    assert client.get("/auth/google/callback").status_code == 404
    # Password auth stays mounted unconditionally.
    assert client.post("/auth/login").status_code != 404


def test_password_mode_without_resend_key_magic_absent(monkeypatch):
    """AUTH_MODE=password with the magic-link trio incomplete (no
    RESEND_API_KEY) → magic routes are NOT mounted (unchanged pre-fix
    behavior for an unconfigured password deployment); password login is
    unaffected."""
    import importlib

    from fastapi.testclient import TestClient

    import main as mainmod

    monkeypatch.setenv("AUTH_MODE", "password")
    monkeypatch.delenv("MAGIC_LINK_ENABLED", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    importlib.reload(mainmod)

    client = TestClient(mainmod.app, raise_server_exceptions=False)
    assert client.post("/auth/magic/start").status_code == 404
    assert client.get("/auth/magic/verify").status_code == 404
    assert client.get("/auth/google/start").status_code == 404
    assert client.post("/auth/login").status_code != 404


# ── Google sign-in against Postgres: its key, and which account it opens ─────
import os as _os
import uuid as _uuid

import pytest as _pytest

_requires_pg = _pytest.mark.skipif(
    not _os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="requires Postgres migrated to head",
)


async def _password_account(email: str) -> int:
    from src.auth.disposable import normalize_email
    from src.auth.models import create_password_user

    uid = await create_password_user(email, normalize_email(email), "x")
    assert uid is not None
    return uid


async def _drop(*emails: str) -> None:
    import src.db.engine as eng
    from sqlalchemy import text

    from src.auth.disposable import normalize_email

    try:
        async with eng.get_session_factory()() as s:
            ids = list((await s.execute(text("SELECT id FROM users WHERE email_lower = ANY(:e)"),
                                        {"e": [normalize_email(e) for e in emails]})).scalars().all())
            orgs = list((await s.execute(text("SELECT org_id FROM memberships WHERE user_id = ANY(:u)"),
                                         {"u": ids})).scalars().all())
            await s.execute(text("DELETE FROM audit_log WHERE user_id = ANY(:u)"), {"u": ids})
            await s.execute(text("DELETE FROM organizations WHERE id = ANY(:o)"), {"o": orgs})
            await s.execute(text("DELETE FROM users WHERE id = ANY(:u)"), {"u": ids})
            await s.commit()
    finally:
        await eng.dispose_engine()


@_requires_pg
@_pytest.mark.asyncio
async def test_the_key_made_at_google_sign_in_is_read_only_and_expires_in_90_days():
    """Google sign-in's key follows the rules for every key made at sign-in
    (provisioning.insert_login_key), never the old no-expiry read-write key."""
    import src.db.engine as eng
    from sqlalchemy import text

    from src.auth.hashing import hmac_index, mint_token
    from src.auth.models import create_api_key, lookup_api_key

    email = f"g-{_uuid.uuid4().hex[:10]}@example.com"
    try:
        uid = await _password_account(email)
        token, prefix, secret_hash = mint_token()
        key_id = await create_api_key(uid, "Default", prefix, hmac_index(token), secret_hash)
        row = await lookup_api_key(hmac_index(token))
        assert row.id == key_id and row.scope == "read" and row.expired is False
        async with eng.get_session_factory()() as s:
            days = (await s.execute(text("SELECT round(extract(epoch FROM expires_at - now()) / 86400) "
                                         "FROM api_keys WHERE id = :k"), {"k": key_id})).scalar_one()
            detail = (await s.execute(text("SELECT detail_json FROM audit_log WHERE action = 'api_key.created' "
                                           "AND resource_id = :k"), {"k": str(key_id)})).scalar_one()
        assert int(days) == 90
        assert detail["scope"] == "read" and detail["expires_in_days"] == 90 and detail["provisioned_with_login"] is True
    finally:
        await _drop(email)


@_requires_pg
@_pytest.mark.asyncio
async def test_google_links_an_account_only_on_its_exact_address_and_its_own_subject():
    """users.email_lower drops "+tag", so "dana+x@corp" names dana@corp's row.
    A Google account for dana+x@corp must never open it; dana@corp's own Google
    account (any case) links once; a different Google account never opens it."""
    import src.db.engine as eng
    from fastapi import HTTPException
    from sqlalchemy import text

    from src.auth.disposable import normalize_email
    from src.auth.models import upsert_user

    tag = _uuid.uuid4().hex[:10]
    email = f"dana-{tag}@corp.example"
    local, domain = email.split("@")
    plus = f"{local}+x@{domain}"

    async def sub_of(uid: int):
        async with eng.get_session_factory()() as s:
            return (await s.execute(text("SELECT google_sub FROM users WHERE id = :u"), {"u": uid})).scalar_one()

    try:
        uid = await _password_account(email)
        with _pytest.raises(HTTPException) as refused:
            await upsert_user(plus, f"sub-plus-{tag}", normalize_email(plus), auth_provider="google")
        assert refused.value.status_code == 409
        assert refused.value.detail["code"] == "google_link_refused"
        assert "different form of this address" in refused.value.detail["message"]
        assert await sub_of(uid) is None

        assert await upsert_user(email.upper(), f"sub-{tag}", normalize_email(email), auth_provider="google") == uid
        assert await sub_of(uid) == f"sub-{tag}"
        assert await upsert_user(email, f"sub-{tag}", normalize_email(email), auth_provider="google") == uid

        with _pytest.raises(HTTPException) as other:
            await upsert_user(email, f"sub-other-{tag}", normalize_email(email), auth_provider="google")
        assert other.value.status_code == 409
        assert "linked to a different Google account" in other.value.detail["message"]
        assert await sub_of(uid) == f"sub-{tag}"
    finally:
        await _drop(email)
