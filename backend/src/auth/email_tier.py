"""Lifetime free checks, derived from the account email on the server."""

PERSONAL_DOMAINS = frozenset(["gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.de", "mail.com", "yandex.com", "zoho.com", "fastmail.com", "fastmail.fm", "hey.com", "tuta.io", "tutanota.com"])


def free_checks(email: str) -> int:
    domain = email.strip().rsplit("@", 1)[-1].lower()
    return 3 if domain in PERSONAL_DOMAINS else 15
