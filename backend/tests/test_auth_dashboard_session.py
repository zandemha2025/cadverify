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


def test_token_is_two_base64url_segments():
    # JWT-style layout: exactly one "." delimiter, and each segment is pure
    # base64url (no "." can leak into a segment, ever).
    from src.auth.dashboard_session import sign

    c = sign(123456789)
    parts = c.split(".")
    assert len(parts) == 2, c
    alphabet = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    for seg in parts:
        assert seg, "empty segment"
        assert set(seg) <= alphabet, seg


def test_stress_5000_roundtrips_zero_failures():
    # Deterministic regression guard for the 0x2e-in-signature split bug.
    # The old format failed ~6% of the time; over 5,000 random-body trials the
    # probability of surviving with zero failures was astronomically small
    # (~(0.94)**5000). A single failure here fails the suite.
    import random

    from src.auth.dashboard_session import MAX_AGE, sign, unsign

    now = int(time.time())
    failures = []
    for _ in range(5000):
        uid = random.randint(0, 2_000_000_000)
        # Random but non-expired issued-at across the full valid window.
        iat = random.randint(now - MAX_AGE + 5, now)
        c = sign(uid, issued_at=iat)
        got = unsign(c)
        if got != uid:
            failures.append((uid, iat, c, got))
    assert not failures, f"{len(failures)}/5000 roundtrips failed; first={failures[0]}"


def test_legacy_single_blob_format_fails_closed():
    # A pre-fix cookie base64url-encodes `body + b"." + sig` as ONE blob, so the
    # resulting string has no "." delimiter. unsign() must reject it (None), not
    # crash and not accept it — the documented one-time forced re-login.
    import base64 as _b64
    import hashlib
    import hmac

    from src.auth.dashboard_session import _secret, unsign

    body = b"42.1700000000"
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()[:16]
    legacy = _b64.urlsafe_b64encode(body + b"." + sig).rstrip(b"=").decode()
    assert "." not in legacy  # old format never contains the delimiter
    assert unsign(legacy) is None


def test_uid_zero_and_large_roundtrip():
    from src.auth.dashboard_session import sign, unsign

    for uid in (0, 1, 2**31 - 1, 2**53):
        assert unsign(sign(uid)) == uid
