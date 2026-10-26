"""Protected CI rejects skips, including previously optional coverage."""

from __future__ import annotations

import pytest


def _run_policy_case(pytester, monkeypatch, source: str):
    monkeypatch.setenv("CADVERIFY_ENFORCE_SKIP_POLICY", "1")
    pytester.makeconftest('pytest_plugins = ("tests.ci_skip_policy", "pytester")')
    pytester.makepyfile(source)
    return pytester.runpytest_inprocess("-q")


def test_runtime_skip_fails_protected_ci(pytester, monkeypatch):
    result = _run_policy_case(
        pytester,
        monkeypatch,
        """
        import pytest

        def test_new_runtime_skip():
            pytest.skip("new dependency disappeared")
        """,
    )

    assert result.ret != 0
    result.stdout.fnmatch_lines(["*UNEXPECTED SKIPS (protected CI policy)*"])


def test_collection_skip_fails_protected_ci(pytester, monkeypatch):
    result = _run_policy_case(
        pytester,
        monkeypatch,
        """
        import pytest

        pytest.skip("module dependency disappeared", allow_module_level=True)
        """,
    )

    assert result.ret != 0
    result.stdout.fnmatch_lines(["*UNEXPECTED SKIPS (protected CI policy)*"])


@pytest.mark.parametrize("reason", [
    "OCP XDE not available",
    "real corpus manifest not present",
    "could not import 'OCP'",
])
def test_former_optional_skips_fail_protected_ci(pytester, monkeypatch, reason):
    result = _run_policy_case(
        pytester, monkeypatch,
        f"import pytest\ndef test_optional():\n    pytest.skip({reason!r})\n",
    )
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*UNEXPECTED SKIPS (protected CI policy)*"])


def test_nested_session_cannot_clear_parent_skips(pytester, monkeypatch):
    result = _run_policy_case(
        pytester, monkeypatch,
        '''
        import pytest

        def test_first():
            pytest.skip("must survive the nested session")

        def test_nested(pytester):
            pytester.makeconftest('pytest_plugins = ("tests.ci_skip_policy", "pytester")')
            pytester.makepyfile("def test_ok(): pass")
            assert pytester.runpytest_inprocess("-q").ret == 0
        ''',
    )
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*must survive the nested session*"])
