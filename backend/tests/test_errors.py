"""Tests for structured error responses."""

import pytest
from httpx import AsyncClient, ASGITransport
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
        assert data["doc_url"].startswith("https://docs.cadverify.com/errors/")


@pytest.mark.asyncio
async def test_error_codes_are_upper_snake():
    """All error codes in the registry are UPPER_SNAKE_CASE."""
    from src.api.errors import ERROR_CODES

    for status, code in ERROR_CODES.items():
        assert code == code.upper(), f"Code {code} for {status} is not uppercase"
        assert " " not in code, f"Code {code} contains spaces"
