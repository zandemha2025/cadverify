"""Unit tests for src.auth.require_api_key (AUTH-06)."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.auth.hashing import hmac_index, mint_token
from src.auth.require_api_key import require_api_key


@dataclass
class _Row:
    id: int
    user_id: int
    prefix: str
    hmac_index: str
    secret_hash: str
    revoked_at: object


class _Req:
    def __init__(self):
        self.client = type("C", (), {"host": "1.2.3.4"})()
        self.state = type("S", (), {})()


@pytest.mark.asyncio
async def test_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        await require_api_key(_Req(), authorization=None)
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_missing"
    assert "doc_url" in exc.value.detail


@pytest.mark.asyncio
async def test_wrong_scheme_raises_401():
    with pytest.raises(HTTPException) as exc:
        await require_api_key(_Req(), authorization="Basic abcd")
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "auth_missing"


@pytest.mark.asyncio
async def test_unknown_key_raises_401(monkeypatch):
    monkeypatch.setattr(
        "src.auth.require_api_key.lookup_api_key", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.touch_last_used", AsyncMock()
    )
    token, _, _ = mint_token()
    with pytest.raises(HTTPException) as exc:
        await require_api_key(_Req(), authorization=f"Bearer {token}")
    assert exc.value.detail["code"] == "auth_invalid"


@pytest.mark.asyncio
async def test_revoked_key_raises_401(monkeypatch):
    token, prefix, sh = mint_token()
    row = _Row(
        id=1,
        user_id=1,
        prefix=prefix,
        hmac_index=hmac_index(token),
        secret_hash=sh,
        revoked_at="2026-01-01",
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.lookup_api_key", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.touch_last_used", AsyncMock()
    )
    with pytest.raises(HTTPException) as exc:
        await require_api_key(_Req(), authorization=f"Bearer {token}")
    # Same code as unknown — no user enumeration.
    assert exc.value.detail["code"] == "auth_invalid"


@pytest.mark.asyncio
async def test_valid_key_returns_authed_user(monkeypatch):
    token, prefix, sh = mint_token()
    row = _Row(
        id=7,
        user_id=42,
        prefix=prefix,
        hmac_index=hmac_index(token),
        secret_hash=sh,
        revoked_at=None,
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.lookup_api_key", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.touch_last_used", AsyncMock()
    )
    req = _Req()
    u = await require_api_key(req, authorization=f"Bearer {token}")
    assert u.user_id == 42
    assert u.api_key_id == 7
    assert u.key_prefix == prefix
    assert req.state.authed_user is u


@pytest.mark.asyncio
async def test_tampered_token_raises_401(monkeypatch):
    token, prefix, sh = mint_token()
    row = _Row(
        id=1,
        user_id=1,
        prefix=prefix,
        hmac_index=hmac_index(token),
        secret_hash=sh,
        revoked_at=None,
    )
    # Tamper AFTER computing index — fake hmac_index so the lookup matches
    # but argon2 verify fails. Confirms verify_token is the real gate.
    monkeypatch.setattr(
        "src.auth.require_api_key.hmac_index", lambda t: row.hmac_index
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.lookup_api_key", AsyncMock(return_value=row)
    )
    monkeypatch.setattr(
        "src.auth.require_api_key.touch_last_used", AsyncMock()
    )
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(HTTPException) as exc:
        await require_api_key(_Req(), authorization=f"Bearer {tampered}")
    assert exc.value.detail["code"] == "auth_invalid"
