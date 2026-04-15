"""API-key minting. HMAC + verify are promoted to first-class in 02.B.

This module exports:
  - mint_token(): issue a fresh cv_live_<prefix>_<secret> + Argon2id hash.
  - hmac_index(): compatibility stub used by oauth.py / magic_link.py so the
    callback can persist a lookup index today. Plan 02.B replaces this with
    a verified implementation that shares the same signature.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from argon2 import PasswordHasher

_PH: PasswordHasher | None = None


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
    # token_urlsafe may underfill; pad with CSPRNG alphanum if so.
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
    """Compatibility stub — overwritten in 02.B with pepper validation.

    Uses API_KEY_PEPPER (base64-encoded, >= 32 bytes) to produce an HMAC-SHA256
    hex digest suitable as a unique lookup index in api_keys.hmac_index.
    """
    pepper = base64.b64decode(os.environ["API_KEY_PEPPER"])
    return hmac.new(pepper, token.encode(), hashlib.sha256).hexdigest()
