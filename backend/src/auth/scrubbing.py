"""Scrub credentials, one-time tokens, and sessions from logs + Sentry."""
from __future__ import annotations

import re

_KEY_RE = re.compile(r"cv_live_[A-Za-z0-9_]+")
_REDACTED = "cv_live_***REDACTED***"
_VALUE_REDACTED = "***REDACTED***"
_BEARER_RE = re.compile(r"\bBearer\s+[^\s\"']+", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(
    r"([?&#](?:token|session|code|api_key)=)[^&#\s\"']+",
    re.IGNORECASE,
)
_SENSITIVE_KEY_LC = {
    "authorization",
    "x-api-key",
    "x-authorization",
    "cookie",
    "set-cookie",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "session",
    "dash_session",
    "mint_once",
    "cv_mint_once",
    "cf_turnstile_response",
    "turnstiletoken",
    "secret",
}


def _scrub_str(value: str) -> str:
    scrubbed = _KEY_RE.sub(_REDACTED, value)
    scrubbed = _BEARER_RE.sub("Bearer ***REDACTED***", scrubbed)
    return _QUERY_SECRET_RE.sub(r"\1***REDACTED***", scrubbed)


def _scrub_value(value):
    if isinstance(value, str):
        return _scrub_str(value)
    if isinstance(value, dict):
        return _scrub_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_scrub_value(item) for item in value]
    return value


def _scrub_mapping(mapping: dict) -> dict:
    out = {}
    for key, value in mapping.items():
        if str(key).lower() in _SENSITIVE_KEY_LC:
            out[key] = _VALUE_REDACTED
        else:
            out[key] = _scrub_value(value)
    return out


def scrub_processor(_logger, _method, event_dict):
    for key in list(event_dict.keys()):
        value = event_dict[key]
        if key.lower() in _SENSITIVE_KEY_LC:
            event_dict[key] = _VALUE_REDACTED
        else:
            event_dict[key] = _scrub_value(value)
    return event_dict


def sentry_before_send(event, _hint):
    scrubbed = _scrub_mapping(event)
    return event if scrubbed == event else scrubbed
