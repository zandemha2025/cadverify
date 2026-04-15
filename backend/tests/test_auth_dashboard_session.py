import base64
import os
import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response


def setup_module():
    os.environ["DASHBOARD_SESSION_SECRET"] = base64.b64encode(os.urandom(32)).decode()


def test_sign_unsign_roundtrip():
    from src.auth.dashboard_session import sign, unsign

    c = sign(42)
    assert unsign(c) == 42


def test_unsign_rejects_tampered():
    from src.auth.dashboard_session import sign, unsign

    c = sign(42)
    tampered = c[:-1] + ("a" if c[-1] != "a" else "b")
    assert unsign(tampered) is None


def test_unsign_rejects_expired():
    from src.auth.dashboard_session import MAX_AGE, sign, unsign

    c = sign(42, issued_at=int(time.time()) - MAX_AGE - 10)
    assert unsign(c) is None


def test_set_session_cookie_has_correct_flags():
    from src.auth.dashboard_session import COOKIE_NAME, MAX_AGE, set_session_cookie

    r = Response()
    set_session_cookie(r, 42)
    sc = r.headers["set-cookie"]
    assert "Secure" in sc
    assert "HttpOnly" in sc
    assert "samesite=lax" in sc.lower()
    assert f"Max-Age={MAX_AGE}" in sc
    assert f"{COOKIE_NAME}=" in sc


@pytest.mark.asyncio
async def test_require_dashboard_session_valid():
    from src.auth.dashboard_session import (
        COOKIE_NAME,
        require_dashboard_session,
        sign,
    )

    req = MagicMock()
    req.cookies = {COOKIE_NAME: sign(7)}
    assert await require_dashboard_session(req) == 7


@pytest.mark.asyncio
async def test_require_dashboard_session_missing_raises_401():
    from src.auth.dashboard_session import require_dashboard_session

    req = MagicMock()
    req.cookies = {}
    with pytest.raises(HTTPException) as exc:
        await require_dashboard_session(req)
    assert exc.value.status_code == 401
