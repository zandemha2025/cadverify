import pytest
from src.auth.email_tier import free_checks

@pytest.mark.parametrize("email, expected", [
    ("person@gmail.com", 3), (" Person@OUTLOOK.COM ", 3),
    ("person@proton.me", 3), ("person@fastmail.com", 3),
    ("engineer@factory.example", 15), ("person@gmail.com.example.org", 15),
])
def test_email_allowance(email, expected):
    assert free_checks(email) == expected
