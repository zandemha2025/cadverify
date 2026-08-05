"""Tests for structured error responses."""

import json

import pytest
from httpx import AsyncClient, ASGITransport
from starlette.exceptions import HTTPException
from main import app


@pytest.mark.asyncio
async def test_404_structured():
    """Non-existent route returns structured error."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/nonexistent")
    assert resp.status_code in (404, 405)
    data = resp.json()
    assert "code" in data
    assert "message" in data
    assert "doc_url" in data


@pytest.mark.asyncio
async def test_error_has_doc_url():
    """Error response doc_url follows expected pattern."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/nonexistent")
    data = resp.json()
    if "doc_url" in data:
        assert data["doc_url"].startswith("https://cadverify.com/docs#")


@pytest.mark.asyncio
async def test_429_preserves_retry_after_header():
    """Regression (gauntlet F2): the structured handler must copy exc.headers so
    Retry-After survives on 429/503 (per-org rate limit, quota, kill-switch,
    signup). Both handler return paths — dict-with-code and plain — are covered."""
    from starlette.requests import Request

    from src.api.errors import structured_http_error_handler

    req = Request({"type": "http", "method": "GET", "path": "/x", "headers": []})

    # dict-with-code path (the shape src/auth/org_limits._org_err produces)
    exc_dict = HTTPException(
        status_code=429,
        detail={"code": "org_rate_limited", "message": "slow down"},
        headers={"Retry-After": "1800"},
    )
    resp_dict = await structured_http_error_handler(req, exc_dict)
    assert resp_dict.status_code == 429
    assert resp_dict.headers.get("retry-after") == "1800"

    # plain-detail path
    exc_plain = HTTPException(
        status_code=503, detail="unavailable", headers={"Retry-After": "5"}
    )
    resp_plain = await structured_http_error_handler(req, exc_plain)
    assert resp_plain.headers.get("retry-after") == "5"


@pytest.mark.asyncio
async def test_error_codes_are_upper_snake():
    """All error codes in the registry are UPPER_SNAKE_CASE."""
    from src.api.errors import ERROR_CODES

    for status, code in ERROR_CODES.items():
        assert code == code.upper(), f"Code {code} for {status} is not uppercase"
        assert " " not in code, f"Code {code} contains spaces"


@pytest.mark.asyncio
async def test_wrapped_dict_detail_is_preserved():
    """Dict details without a custom code remain machine-readable."""
    from src.api.errors import structured_http_error_handler

    resp = await structured_http_error_handler(
        None,
        HTTPException(
            status_code=422,
            detail={"reason": "below floor", "n_real": 4, "min_real": 8},
        ),
    )
    data = json.loads(resp.body)
    assert data["code"] == "VALIDATION_ERROR"
    assert data["message"] == "below floor"
    assert data["detail"] == {"reason": "below floor", "n_real": 4, "min_real": 8}
