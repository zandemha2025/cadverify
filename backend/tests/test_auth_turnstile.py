import httpx
import pytest
import respx
from fastapi import HTTPException

from src.auth.turnstile import SITEVERIFY, verify_turnstile


@pytest.mark.asyncio
@respx.mock
async def test_turnstile_success(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET", "test-secret")
    respx.post(SITEVERIFY).mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await verify_turnstile("client-token", "1.2.3.4")


@pytest.mark.asyncio
@respx.mock
async def test_turnstile_failure_raises_400(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET", "test-secret")
    respx.post(SITEVERIFY).mock(
        return_value=httpx.Response(
            200, json={"success": False, "error-codes": ["invalid-input-response"]}
        )
    )
    with pytest.raises(HTTPException) as exc:
        await verify_turnstile("bad", None)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "captcha_failed"


@pytest.mark.asyncio
@respx.mock
async def test_turnstile_non_200_raises_400(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET", "test-secret")
    respx.post(SITEVERIFY).mock(return_value=httpx.Response(500, text="upstream down"))
    with pytest.raises(HTTPException) as exc:
        await verify_turnstile("x", None)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "captcha_failed"
