"""API-key hashing: HMAC-SHA256 prefix index + Argon2id secret hash.

Public API (final, promoted in 02.B):
  - mint_token() -> (full_token, prefix, secret_hash)
  - hmac_index(token) -> hex digest (64 chars)
  - verify_token(secret_hash, token) -> bool (never raises to the caller)
  - needs_rehash(secret_hash) -> bool
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHash,
    InvalidHashError,
    VerifyMismatchError,
)

_PEPPER: bytes | None = None
_PH: PasswordHasher | None = None


def _pepper() -> bytes:
    global _PEPPER
    if _PEPPER is None:
        raw = os.environ["API_KEY_PEPPER"]
        decoded = base64.b64decode(raw)
        if len(decoded) < 32:
            raise RuntimeError("API_KEY_PEPPER must decode to >= 32 bytes")
        _PEPPER = decoded
    return _PEPPER


def _ph() -> PasswordHasher:
    global _PH
    if _PH is None:
        _PH = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
        )
    return _PH


def _base62_chunk(n_bytes: int, out_len: int) -> str:
    raw = secrets.token_urlsafe(n_bytes)
    cleaned = raw.replace("-", "a").replace("_", "b").replace("=", "")
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    while len(cleaned) < out_len:
        cleaned += secrets.choice(alphabet)
    return cleaned[:out_len]


def mint_token() -> tuple[str, str, str]:
    """Return (full_token, prefix, secret_hash).

    full_token = 'cv_live_' + prefix(8 base62) + '_' + secret(32 base62)
    secret_hash = Argon2id(time_cost=3, memory_cost=65536, parallelism=4)
    """
    prefix = _base62_chunk(6, 8)
    secret = _base62_chunk(24, 32)
    token = f"cv_live_{prefix}_{secret}"
    return token, prefix, _ph().hash(token)


def hmac_index(token: str) -> str:
    """HMAC-SHA256 of the token under API_KEY_PEPPER. Deterministic lookup key."""
    return hmac.new(_pepper(), token.encode(), hashlib.sha256).hexdigest()


def verify_token(secret_hash: str, token: str) -> bool:
    """Return True iff token matches secret_hash. Never raises to the caller."""
    try:
        _ph().verify(secret_hash, token)
        return True
    except (VerifyMismatchError, InvalidHash, InvalidHashError):
        return False
    except Exception:
        # Defensive: argon2-cffi may raise other errors on malformed input.
        return False


def needs_rehash(secret_hash: str) -> bool:
    return _ph().check_needs_rehash(secret_hash)
