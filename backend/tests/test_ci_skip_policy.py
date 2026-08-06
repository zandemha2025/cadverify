"""Protected CI accepts only exact, documented optional-test skips."""

from __future__ import annotations

from tests.ci_skip_policy import is_expected_ci_skip


def test_expected_optional_skip_requires_matching_node_and_reason():
    nodeid = "tests/test_step_ap242_parser.py::test_ap242_document_has_pmi_flag"

    assert is_expected_ci_skip(nodeid, "Skipped: OCP XDE not available")
    assert not is_expected_ci_skip(nodeid, "Skipped: fixture disappeared")
    assert not is_expected_ci_skip(
        "tests/test_other.py::test_ap242_document_has_pmi_flag",
        "Skipped: OCP XDE not available",
    )


def test_local_corpus_skip_is_narrowly_allowlisted():
    nodeid = (
        "tests/test_eval_harness.py::"
        "test_smoke_seed_is_one_part_per_key_in_real_corpus"
    )

    assert is_expected_ci_skip(nodeid, "Skipped: real corpus manifest not present")
    assert not is_expected_ci_skip(nodeid, "Skipped: generated fixtures missing")


def _run_policy_case(pytester, monkeypatch, source: str):
    monkeypatch.setenv("CADVERIFY_ENFORCE_SKIP_POLICY", "1")
    pytester.makeconftest('pytest_plugins = ("tests.ci_skip_policy",)')
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
