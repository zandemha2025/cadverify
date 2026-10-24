"""Free-check tiers by email domain.

A work address gets the larger free allowance; consumer mailboxes get the
smaller one. Both sizes are operator settings (FREE_CHECKS_WORK,
FREE_CHECKS_PERSONAL). Classification uses the normalized address stored in
users.email_lower, so Gmail dot/+tag aliases already resolve to one account.
"""
from __future__ import annotations

import os

# Consumer mailbox providers. Anything else is treated as a work domain.
PERSONAL_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com", "passport.com",
    "yahoo.com", "yahoo.co.uk", "yahoo.ca", "yahoo.com.au", "yahoo.co.in", "yahoo.fr", "yahoo.de", "ymail.com", "rocketmail.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com", "aim.com",
    "proton.me", "protonmail.com", "pm.me",
    "tuta.io", "tutanota.com", "tutamail.com",
    "fastmail.com", "fastmail.fm",
    "gmx.com", "gmx.net", "gmx.de", "web.de",
    "mail.com", "email.com", "zoho.com", "zohomail.com",
    "yandex.com", "yandex.ru", "mail.ru",
    "qq.com", "163.com", "126.com", "sina.com", "foxmail.com",
    "naver.com", "hanmail.net", "daum.net",
    "comcast.net", "verizon.net", "att.net", "sbcglobal.net", "bellsouth.net", "cox.net", "charter.net", "earthlink.net",
    "hey.com", "duck.com", "mailfence.com", "hushmail.com", "inbox.com", "rediffmail.com",
    "btinternet.com", "orange.fr", "free.fr", "laposte.net", "libero.it", "t-online.de",
})

DEFAULT_WORK_CHECKS = 15
DEFAULT_PERSONAL_CHECKS = 3


def _env_checks(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(10_000, max(0, value))


def work_checks() -> int:
    return _env_checks("FREE_CHECKS_WORK", DEFAULT_WORK_CHECKS)


def personal_checks() -> int:
    return _env_checks("FREE_CHECKS_PERSONAL", DEFAULT_PERSONAL_CHECKS)


def email_tier(email: str | None) -> str:
    """Return 'personal' or 'work'. A malformed address gets the smaller tier."""
    domain = (email or "").rsplit("@", 1)[-1].strip().lower().rstrip(".")
    if not domain or "@" not in (email or "") or domain in PERSONAL_EMAIL_DOMAINS:
        return "personal"
    return "work"


def tier_checks(tier: str) -> int:
    return work_checks() if tier == "work" else personal_checks()
