"""A client-supplied X-Request-ID is used only when it is short and plain.

The id is echoed in the response header and bound into structured logs and the
Sentry scope, so it is kept only when it is at most 128 characters of letters,
digits and ``- _ . :``. Anything else is replaced by a fresh UUID.
"""
from __future__ import annotations

import uuid

import pytest
import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.middleware import RequestIDMiddleware


def _app():
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/rid")
    async def rid():
        return {"bound": structlog.contextvars.get_contextvars().get("request_id")}

    return app


async def _call(header: str | None):
    headers = {"X-Request-ID": header.encode("utf-8")} if header is not None else {}
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/rid", headers=headers)
    return r.headers["X-Request-ID"], r.json()["bound"]


def _is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [
    "a" * 129,
    "id with spaces",
    "id<script>alert(1)</script>",
    'quoted"id',
    "id;other=1",
    "naïve-id",
    "%0d%0aSet-Cookie:x",
    "",
])
async def test_unsafe_or_long_ids_are_replaced(header):
    echoed, bound = await _call(header)
    assert echoed == bound
    assert _is_uuid(echoed)
    assert header not in echoed or header == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [
    "otel-test-req",
    "01JZQ8R7S5V3W2X1Y0Z9A8B7C6",
    str(uuid.uuid4()),
    "fly:req.42_a",
    "a" * 128,
])
async def test_plain_ids_are_kept(header):
    assert await _call(header) == (header, header)


@pytest.mark.asyncio
async def test_a_missing_id_gets_a_uuid():
    echoed, bound = await _call(None)
    assert echoed == bound and _is_uuid(echoed)
