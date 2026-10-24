"""The emailed sign-in link never carries a ``next`` that opens another site.

Security review R4 (F1): /magic/verify reads ``next`` from the link fragment,
runs it through the WHATWG URL parser (dot segments removed, ``%2e`` decoded)
and sets ``window.location.href`` to the result. ``/.//evil.example`` became
``//evil.example``, i.e. https://evil.example/. ``_safe_next`` now refuses
"//", a backslash or a dot segment in the path, raw or percent-decoded.
"""
import pytest

from src.auth.magic_link import _safe_next


@pytest.mark.parametrize(
    "raw",
    [
        "/.//evil.example",
        "/..//evil.example",
        "/%2e//evil.example",
        "/a/..//evil.example",
        "/%2e%2e/%2fevil.example",
        "/%2E/x",
        "/a/%2e%2e/b",
        "//evil.example",
        "/\\evil.example",
        "https://evil.example/",
    ],
)
def test_magic_next_refuses_paths_that_normalise_to_another_host(raw):
    assert _safe_next(raw) == "", f"_safe_next kept {raw!r}; the browser lands on //evil.example"


@pytest.mark.parametrize(
    "raw",
    ["/verify", "/app/parts?joined=1", "/app/x.y/z", "/orgs/accept?token=abc&next=%2Fapp%2Fmany%2Fx"],
)
def test_magic_next_keeps_a_plain_local_path(raw):
    assert _safe_next(raw) == raw


def test_magic_next_ignores_a_non_string():
    assert _safe_next(object()) == ""
