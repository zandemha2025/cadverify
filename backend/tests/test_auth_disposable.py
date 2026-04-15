from src.auth.disposable import classify, normalize_email


def test_hard_reject():
    assert classify("x@mailinator.com", set()) == "hard_reject"


def test_soft_flag():
    assert classify("x@sketchy.example", {"sketchy.example"}) == "soft_flag"


def test_ok():
    assert classify("x@company.com", set()) == "ok"


def test_allowlist_beats_hard():
    # Even if proton.me lands on some list, allowlist wins.
    assert classify("x@proton.me", {"proton.me"}) == "ok"


def test_allowlist_covers_providers():
    for domain in ("proton.me", "tuta.io", "fastmail.com", "fastmail.fm", "pm.me"):
        assert classify(f"u@{domain}", {domain}) == "ok"


def test_normalize_gmail_dots_and_plus():
    assert normalize_email("Foo.Bar+tag@Gmail.com") == "foobar@gmail.com"


def test_normalize_non_gmail_keeps_dots():
    assert normalize_email("foo.bar+tag@Company.COM") == "foo.bar@company.com"
