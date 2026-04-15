"""ACCEPTING_NEW_ANALYSES env-var kill-switch with 30-s in-process cache.

Semantics (AUTH-09):
- True by default.
- Set ACCEPTING_NEW_ANALYSES=false (or 0/no/off, case-insensitive) to reject
  new analyses with 503 + Retry-After: 3600.
- Cached in-process for 30 s so hot requests do not pay an env-read cost,
  and flips propagate within one deploy (deploys take > 30 s).
"""
from __future__ import annotations

import os
import threading
import time

from fastapi import HTTPException

_LOCK = threading.Lock()
_CACHE_TS = 0.0
_CACHE_VAL = True
CACHE_TTL_S = 30.0


def is_accepting() -> bool:
    global _CACHE_TS, _CACHE_VAL
    now = time.time()
    if now - _CACHE_TS < CACHE_TTL_S:
        return _CACHE_VAL
    with _LOCK:
        if now - _CACHE_TS < CACHE_TTL_S:
            return _CACHE_VAL
        raw = os.getenv("ACCEPTING_NEW_ANALYSES", "true").strip().lower()
        _CACHE_VAL = raw not in ("false", "0", "no", "off")
        _CACHE_TS = now
        return _CACHE_VAL


def require_kill_switch_open() -> None:
    if not is_accepting():
        raise HTTPException(
            status_code=503,
            headers={"Retry-After": "3600"},
            detail={
                "code": "service_paused",
                "message": "New analyses temporarily disabled. Retry in an hour.",
                "doc_url": "https://docs.cadverify.com/errors#service_paused",
            },
        )
