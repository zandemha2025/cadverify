import base64
import os


def setup_module(module):
    os.environ.setdefault("MAGIC_LINK_SECRET", base64.b64encode(b"x" * 32).decode())


def test_roundtrip():
    from src.auth.magic_link import _mint, _verify
    t = _mint("alice@example.com")
    assert _verify(t) == "alice@example.com"


def test_tampered_signature():
    from src.auth.magic_link import _mint, _verify
    t = _mint("alice@example.com")
    tampered = t[:-1] + ("a" if t[-1] != "a" else "b")
    assert _verify(tampered) is None


def test_expired(monkeypatch):
    import src.auth.magic_link as m
    t = m._mint("alice@example.com")
    real_time = m.time.time()
    monkeypatch.setattr(m.time, "time", lambda: real_time + 16 * 60)
    assert m._verify(t) is None


def test_garbage_token_returns_none():
    from src.auth.magic_link import _verify
    assert _verify("not-a-token") is None
    assert _verify("") is None
