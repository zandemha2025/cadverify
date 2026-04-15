"""Unit tests for src.auth.hashing — Argon2id + HMAC pepper index."""
from __future__ import annotations

import base64
import importlib
import os

import pytest

from src.auth.hashing import hmac_index, mint_token, verify_token


@pytest.fixture(autouse=True)
def pepper(monkeypatch):
    monkeypatch.setenv(
        "API_KEY_PEPPER", base64.b64encode(os.urandom(32)).decode()
    )
    # Reset module-level cached pepper so each test gets fresh config.
    import src.auth.hashing as h

    h._PEPPER = None
    yield
    h._PEPPER = None


def test_mint_format():
    t, p, h = mint_token()
    assert t.startswith("cv_live_")
    assert len(p) == 8
    assert h.startswith("$argon2id$")
    parts = t.split("_")
    assert parts[0] == "cv" and parts[1] == "live"
    assert len(parts[2]) == 8 and len(parts[3]) == 32


def test_hmac_index_deterministic():
    t = "cv_live_abcdefgh_" + "x" * 32
    assert hmac_index(t) == hmac_index(t)
    assert len(hmac_index(t)) == 64


def test_hmac_index_changes_with_pepper(monkeypatch):
    t = "cv_live_abcdefgh_" + "x" * 32
    a = hmac_index(t)
    import src.auth.hashing as h

    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"y" * 32).decode())
    h._PEPPER = None
    b = h.hmac_index(t)
    assert a != b


def test_verify_roundtrip_and_mismatch():
    t, _, h = mint_token()
    assert verify_token(h, t) is True
    assert verify_token(h, t + "tamper") is False
    assert verify_token("$argon2id$not_a_valid_hash", t) is False


def test_short_pepper_raises(monkeypatch):
    monkeypatch.setenv("API_KEY_PEPPER", base64.b64encode(b"short").decode())
    import src.auth.hashing as h

    h._PEPPER = None
    with pytest.raises(RuntimeError):
        h.hmac_index("cv_live_xxxxxxxx_" + "x" * 32)
