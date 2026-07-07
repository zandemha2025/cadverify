"""S3: SSO logins mint an API key only when the account has none active.

Covers the shared models helper plus all three call sites (SAML is exercised
in test_saml.py; Google OAuth callback and magic-link verify here).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeSessionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _patch_session_factory(session):
    """Return a stand-in for models._session: _session()() -> async CM."""
    factory = MagicMock(return_value=_FakeSessionCM(session))
    return MagicMock(return_value=factory)


# ---------------------------------------------------------------------------
# models.user_has_active_api_key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_has_active_api_key_true():
    from src.auth import models

    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = (1,)
    session.execute = AsyncMock(return_value=result)

    with patch.object(models, "_session", _patch_session_factory(session)):
        assert await models.user_has_active_api_key(5) is True


@pytest.mark.asyncio
async def test_user_has_active_api_key_false():
    from src.auth import models

    session = AsyncMock()
    result = MagicMock()
    result.first.return_value = None
    session.execute = AsyncMock(return_value=result)

    with patch.object(models, "_session", _patch_session_factory(session)):
        assert await models.user_has_active_api_key(5) is False


# ---------------------------------------------------------------------------
# Google OAuth callback
# ---------------------------------------------------------------------------


def _oauth_app():
    from src.auth.oauth import router

    app = FastAPI()
    app.include_router(router, prefix="/auth")
    return app


_TOKEN = {"userinfo": {"email": "user@example.com", "sub": "sub-123"}}


def test_google_callback_mints_when_no_active_key():
    app = _oauth_app()
    with patch("src.auth.oauth.oauth") as mock_oauth, patch(
        "src.auth.oauth.upsert_user", new_callable=AsyncMock, return_value=5
    ) as mock_upsert, patch(
        "src.auth.oauth.user_has_active_api_key",
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        "src.auth.oauth.create_api_key", new_callable=AsyncMock, return_value=1
    ) as mock_create, patch(
        "src.auth.oauth.get_user_session_version",
        new_callable=AsyncMock,
        return_value=0,
    ):
        mock_oauth.google.authorize_access_token = AsyncMock(return_value=_TOKEN)
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/auth/google/callback")

    assert resp.status_code == 303
    assert "new=1" in resp.headers["location"]
    assert "cv_mint_once" in resp.headers.get("set-cookie", "")
    mock_upsert.assert_awaited_once_with(
        "user@example.com", "sub-123", "user@example.com", auth_provider="google"
    )
    mock_create.assert_awaited_once()


def test_google_callback_skips_when_key_exists():
    app = _oauth_app()
    with patch("src.auth.oauth.oauth") as mock_oauth, patch(
        "src.auth.oauth.upsert_user", new_callable=AsyncMock, return_value=5
    ) as mock_upsert, patch(
        "src.auth.oauth.user_has_active_api_key",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.auth.oauth.create_api_key", new_callable=AsyncMock
    ) as mock_create, patch(
        "src.auth.oauth.get_user_session_version",
        new_callable=AsyncMock,
        return_value=0,
    ):
        mock_oauth.google.authorize_access_token = AsyncMock(return_value=_TOKEN)
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/auth/google/callback")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/developer"
    assert "new=1" not in resp.headers["location"]
    assert "cv_mint_once" not in resp.headers.get("set-cookie", "")
    mock_upsert.assert_awaited_once_with(
        "user@example.com", "sub-123", "user@example.com", auth_provider="google"
    )
    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# Magic-link verify
# ---------------------------------------------------------------------------


def _magic_app():
    from src.auth.magic_link import router

    app = FastAPI()
    app.include_router(router, prefix="/auth")
    return app


def test_magic_verify_mints_when_no_active_key():
    app = _magic_app()
    fake_redis = AsyncMock()
    fake_redis.getdel = AsyncMock(return_value="user@example.com")
    with patch("src.auth.magic_link._verify", return_value="user@example.com"), patch(
        "src.auth.magic_link._r", return_value=fake_redis
    ), patch(
        "src.auth.magic_link.upsert_user", new_callable=AsyncMock, return_value=5
    ) as mock_upsert, patch(
        "src.auth.magic_link.user_has_active_api_key",
        new_callable=AsyncMock,
        return_value=False,
    ), patch(
        "src.auth.magic_link.create_api_key", new_callable=AsyncMock, return_value=1
    ) as mock_create, patch(
        "src.auth.magic_link.get_user_session_version",
        new_callable=AsyncMock,
        return_value=0,
    ):
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/auth/magic/verify?token=abc")

    assert resp.status_code == 303
    assert "new=1" in resp.headers["location"]
    mock_upsert.assert_awaited_once_with(
        "user@example.com", None, "user@example.com", auth_provider="magic_link"
    )
    mock_create.assert_awaited_once()


def test_magic_verify_skips_when_key_exists():
    app = _magic_app()
    fake_redis = AsyncMock()
    fake_redis.getdel = AsyncMock(return_value="user@example.com")
    with patch("src.auth.magic_link._verify", return_value="user@example.com"), patch(
        "src.auth.magic_link._r", return_value=fake_redis
    ), patch(
        "src.auth.magic_link.upsert_user", new_callable=AsyncMock, return_value=5
    ) as mock_upsert, patch(
        "src.auth.magic_link.user_has_active_api_key",
        new_callable=AsyncMock,
        return_value=True,
    ), patch(
        "src.auth.magic_link.create_api_key", new_callable=AsyncMock
    ) as mock_create, patch(
        "src.auth.magic_link.get_user_session_version",
        new_callable=AsyncMock,
        return_value=0,
    ):
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/auth/magic/verify?token=abc")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/developer"
    assert "cv_mint_once" not in resp.headers.get("set-cookie", "")
    mock_upsert.assert_awaited_once_with(
        "user@example.com", None, "user@example.com", auth_provider="magic_link"
    )
    mock_create.assert_not_called()
