"""Scrub cv_live_* tokens and Authorization headers from logs + Sentry."""
from __future__ import annotations

import json
import re

_KEY_RE = re.compile(r"cv_live_[A-Za-z0-9_]+")
_REDACTED = "cv_live_***REDACTED***"
_AUTH_KEY_LC = {"authorization", "x-api-key", "x-authorization"}


def _scrub_str(s: str) -> str:
    return _KEY_RE.sub(_REDACTED, s)


def _scrub_mapping(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        if str(k).lower() in _AUTH_KEY_LC:
            out[k] = "***REDACTED***"
        elif isinstance(v, str):
            out[k] = _scrub_str(v)
        elif isinstance(v, dict):
            out[k] = _scrub_mapping(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [_scrub_str(x) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


def scrub_processor(_logger, _method, event_dict):
    for k in list(event_dict.keys()):
        v = event_dict[k]
        if k.lower() in _AUTH_KEY_LC:
            event_dict[k] = "***REDACTED***"
        elif isinstance(v, str):
            event_dict[k] = _scrub_str(v)
        elif isinstance(v, dict):
            event_dict[k] = _scrub_mapping(v)
        elif isinstance(v, (list, tuple)):
            event_dict[k] = [_scrub_str(x) if isinstance(x, str) else x for x in v]
    return event_dict


def sentry_before_send(event, _hint):
    s = json.dumps(event, default=str)
    if "cv_live_" not in s and "Bearer " not in s:
        return event
    # scrub via JSON roundtrip — catches deeply nested structures
    s = _KEY_RE.sub(_REDACTED, s)
    s = re.sub(r'"Bearer\s+[^"]+"', '"Bearer ***REDACTED***"', s)
    try:
        return json.loads(s)
    except Exception:
        return event  # best-effort; structlog processor is the primary layer
