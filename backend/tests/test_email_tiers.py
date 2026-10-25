import pytest

from src.auth import email_tiers


@pytest.mark.parametrize("email,tier", [
    ("someone@gmail.com", "personal"),
    ("someone@GoogleMail.com", "personal"),
    ("a.b@outlook.com", "personal"),
    ("x@icloud.com", "personal"),
    ("x@proton.me", "personal"),
    ("eng@acme-aero.com", "work"),
    ("buyer@aramco.com", "work"),
    ("eng@gmail.com.evil.io", "work"),
    ("not-an-email", "personal"),
    ("", "personal"),
    (None, "personal"),
])
def test_email_tier(email, tier):
    assert email_tiers.email_tier(email) == tier


def test_tier_sizes_default_and_clamp(monkeypatch):
    monkeypatch.delenv("FREE_CHECKS_WORK", raising=False)
    monkeypatch.delenv("FREE_CHECKS_PERSONAL", raising=False)
    assert (email_tiers.tier_checks("work"), email_tiers.tier_checks("personal")) == (15, 3)
    monkeypatch.setenv("FREE_CHECKS_WORK", "not-a-number")
    monkeypatch.setenv("FREE_CHECKS_PERSONAL", "-4")
    assert (email_tiers.tier_checks("work"), email_tiers.tier_checks("personal")) == (15, 0)
