"""Authenticator-app codes: RFC 6238 TOTP (HMAC-SHA1, 30-second steps, 6 digits).

Pure functions, no I/O. A code is accepted for the current step or one step
either side (clock drift), and never for a step at or before the last step the
account already used, so a code read over someone's shoulder can't be replayed
inside its own 30 seconds.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PERIOD = 30
DIGITS = 6
DRIFT_STEPS = 1
SECRET_BYTES = 20  # 160 bits, the RFC 4226 recommendation
ISSUER = "ScaleCAD"


def new_secret() -> str:
    """A fresh base32 secret (32 characters, no padding)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret_b32: str) -> bytes:
    clean = secret_b32.replace(" ", "").upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def step_at(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def code_at_step(secret_b32: str, step: int) -> str:
    """HOTP(secret, step) truncated to six digits (RFC 4226 section 5.3)."""
    digest = hmac.new(_key(secret_b32), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def clean_code(raw: object) -> str | None:
    """Six digits from what a person typed ("123 456", "123-456"), else None.

    ASCII digits only: ``str.isdigit`` also accepts other scripts' digits
    ("١٢٣٤٥٦"), which no authenticator app shows and which the constant-time
    compare refuses with a TypeError.
    """
    if not isinstance(raw, str):
        return None
    digits = "".join(ch for ch in raw if not ch.isspace() and ch != "-")
    if len(digits) != DIGITS or not (digits.isascii() and digits.isdigit()):
        return None
    return digits


def matching_step(
    secret_b32: str,
    code: str,
    *,
    last_used_step: int | None = None,
    now: float | None = None,
) -> int | None:
    """The time step ``code`` belongs to (within the drift window), else None.

    Steps at or before ``last_used_step`` never match: each step's code works
    once per account.
    """
    typed = clean_code(code)
    if typed is None:
        return None
    current = step_at(now)
    found: int | None = None
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        # Compare every candidate in constant time; don't stop at the first hit.
        if hmac.compare_digest(code_at_step(secret_b32, step), typed):
            if last_used_step is None or step > last_used_step:
                found = step
    return found


def manual_key(secret_b32: str) -> str:
    """The secret in groups of four, as people type it into an app."""
    clean = secret_b32.replace(" ", "").upper()
    return " ".join(clean[i:i + 4] for i in range(0, len(clean), 4))


def otpauth_uri(secret_b32: str, account: str, *, max_len: int | None = None) -> str:
    """The ``otpauth://`` link an authenticator app reads from the QR code.

    SHA1, six digits and 30 seconds are the defaults every app assumes, so they
    are left out to keep the QR code small. When ``max_len`` is given and the
    account name would push the link past it, the label falls back to the
    issuer alone (the secret and issuer never change).
    """
    secret = secret_b32.replace(" ", "").upper()
    issuer = quote(ISSUER, safe="")
    tail = f"?secret={secret}&issuer={issuer}"
    uri = f"otpauth://totp/{issuer}:{quote(account, safe='@')}{tail}"
    if max_len is not None and len(uri) > max_len:
        uri = f"otpauth://totp/{issuer}{tail}"
    return uri
