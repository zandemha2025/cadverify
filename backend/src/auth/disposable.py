"""Disposable email classification + normalization.

- hard_reject: curated sub-list of known-throwaway domains → 400
- soft_flag:   domain in soft_flag_set (sourced from Redis cache in 02.D)
- ok:          everything else (including _NEVER_BLOCK allowlist override,
               which wins even if a domain appears on any other list; this
               honors D-11 override for proton.me / tuta.io / fastmail.*)
"""
from __future__ import annotations

_HARD_REJECT: frozenset[str] = frozenset({
    "mailinator.com", "10minutemail.com", "10minutemail.net",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "yopmail.com", "temp-mail.org", "sharklasers.com", "spam4.me",
    "getnada.com", "trashmail.com", "maildrop.cc", "dispostable.com",
    "mintemail.com", "tempmail.com", "fakeinbox.com", "mytrashmail.com",
    "mailnesia.com", "throwaway.email",
})

_NEVER_BLOCK: frozenset[str] = frozenset({
    "proton.me", "protonmail.com", "pm.me", "tuta.io", "tutanota.com",
    "fastmail.com", "fastmail.fm", "gmail.com", "outlook.com",
    "hotmail.com", "icloud.com", "yahoo.com",
})


def classify(email: str, soft_flag_set: set[str]) -> str:
    """Return one of: 'ok' | 'soft_flag' | 'hard_reject'.

    Allowlist (_NEVER_BLOCK) overrides everything.
    """
    domain = email.rsplit("@", 1)[-1].strip().lower()
    if domain in _NEVER_BLOCK:
        return "ok"
    if domain in _HARD_REJECT:
        return "hard_reject"
    if domain in soft_flag_set:
        return "soft_flag"
    return "ok"


def normalize_email(email: str) -> str:
    """Lowercase, strip +tags, collapse gmail dots.

    Non-gmail domains retain dots in the local part (per RFC they can be
    significant), but +tags are always stripped for rate-limit parity.
    """
    local, _, domain = email.partition("@")
    local = local.lower()
    domain = domain.lower()
    if domain == "gmail.com":
        local = local.split("+", 1)[0].replace(".", "")
    else:
        local = local.split("+", 1)[0]
    return f"{local}@{domain}"
