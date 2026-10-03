"""Developer onboarding contract for dashboard API-key mutations."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import Response
from pydantic import ValidationError

from src.auth import keys_api


def test_key_names_are_trimmed_and_bounded():
    assert keys_api.CreateIn(name="  Build server  ").name == "Build server"
    with pytest.raises(ValidationError):
        keys_api.CreateIn(name="   ")
    with pytest.raises(ValidationError):
        keys_api.CreateIn(name="x" * 81)


@pytest.mark.asyncio
async def test_create_returns_secret_once_without_browser_cookie(monkeypatch):
    monkeypatch.setattr(keys_api, "mint_token", lambda: ("cv_live_prefix_secret", "prefix", "hash"))
    monkeypatch.setattr(keys_api, "hmac_index", lambda _token: "index")
    create = AsyncMock(return_value=42)
    monkeypatch.setattr(keys_api, "create_api_key", create)

    response = Response()
    body = await keys_api.create_key(keys_api.CreateIn(name="  Production  "), response, user_id=7)

    assert body == {"id": 42, "prefix": "prefix", "token": "cv_live_prefix_secret"}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    create.assert_awaited_once_with(7, "Production", "prefix", "index", "hash")
