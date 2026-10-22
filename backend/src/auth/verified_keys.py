"""API-key secrets checked off the event loop, and remembered briefly once verified.

``require_api_key`` looks every Bearer key up by its HMAC index on every request,
so revocation, expiry, rotation, scope, the org's two-step rule and deactivation
apply at once. What this module saves is only the Argon2id check of the secret
against the row's stored hash (t=3, 64 MiB, p=4: 0.3-0.6 s of CPU), which ran on
the event loop and stalled every other request while it did:

* the check runs in a worker thread (``asyncio.to_thread``), at most
  ``VERIFY_SLOTS`` at once per process (64 MiB each), and concurrent requests
  presenting the same key share one check;
* a passed check is remembered for ``TTL_S`` seconds, at most ``MAX_ENTRIES``
  keys. An entry is keyed by HMAC-SHA256 of the presented token under a random
  per-process secret and holds the key row's id and a SHA-256 of the row's
  stored hash, so it counts only for that row with that stored hash (a key
  re-hashed or replaced checks again). The token itself is never stored.

A failed check is not remembered.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import OrderedDict
from typing import Callable


def _ttl_from_env() -> float:
    try:
        return max(0.0, float(os.getenv("API_KEY_VERIFY_CACHE_TTL_S", "60")))
    except ValueError:
        return 60.0


TTL_S = _ttl_from_env()  # 0 turns the cache off: every request checks the secret again
MAX_ENTRIES = 4096
VERIFY_SLOTS = 2

_now = time.monotonic
_secret = secrets.token_bytes(32)
_lock = threading.Lock()
# HMAC(token) -> (api key id, SHA-256 of its stored hash, monotonic expiry)
_entries: "OrderedDict[bytes, tuple[int, bytes, float]]" = OrderedDict()
# (HMAC(token), key id, SHA-256 of stored hash) -> the check in progress
_inflight: dict[tuple[bytes, int, bytes], asyncio.Task] = {}
_slots = threading.BoundedSemaphore(VERIFY_SLOTS)


def _token_key(token: str) -> bytes:
    return hmac.new(_secret, token.encode(), hashlib.sha256).digest()


def _hash_digest(secret_hash: str) -> bytes:
    return hashlib.sha256((secret_hash or "").encode()).digest()


def _hit(tk: bytes, key_id: int, hd: bytes) -> bool:
    with _lock:
        entry = _entries.get(tk)
        if entry is None:
            return False
        if entry[2] <= _now():
            del _entries[tk]
            return False
        _entries.move_to_end(tk)
        return entry[0] == key_id and hmac.compare_digest(entry[1], hd)


def _remember(tk: bytes, key_id: int, hd: bytes) -> None:
    if TTL_S <= 0:
        return
    with _lock:
        _entries[tk] = (key_id, hd, _now() + TTL_S)
        _entries.move_to_end(tk)
        while len(_entries) > MAX_ENTRIES:
            _entries.popitem(last=False)


def _check(verify: Callable[[str, str], bool], secret_hash: str, token: str) -> bool:
    with _slots:
        return bool(verify(secret_hash, token))


def _landed(flight: tuple, task: asyncio.Task) -> None:
    if _inflight.get(flight) is task:
        del _inflight[flight]
    if not task.cancelled():
        task.exception()  # retrieved: a check every caller stopped waiting for never logs as unretrieved


def forget_all() -> None:
    """Drop every remembered check (tests; an operator flushing after a pepper change)."""
    with _lock:
        _entries.clear()


async def verified(key_id: int, secret_hash: str, token: str, verify: Callable[[str, str], bool]) -> bool:
    """True when ``token`` matches the key row's ``secret_hash``; the Argon2 check runs off the loop.

    The caller has already looked the row up for this request; a remembered
    pass skips only the hash check, never the lookup or its refusals.
    """
    tk, hd = _token_key(token), _hash_digest(secret_hash)
    if _hit(tk, key_id, hd):
        return True
    loop = asyncio.get_running_loop()
    flight = (tk, key_id, hd)
    task = _inflight.get(flight)
    if task is None or task.get_loop() is not loop:
        task = loop.create_task(asyncio.to_thread(_check, verify, secret_hash, token))
        _inflight[flight] = task
        task.add_done_callback(lambda t, f=flight: _landed(f, t))
    ok = await asyncio.shield(task)
    if ok:
        _remember(tk, key_id, hd)
    return ok
