from __future__ import annotations

import ast
from pathlib import Path


def test_attestation_range_excludes_ci_synthetic_merge_commits():
    source = Path("scripts/ci/check_commit_hook_policy.py").read_text()
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    rev_lists = [
        node for node in calls
        if isinstance(node.func, ast.Name) and node.func.id == "git"
        and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "rev-list"
    ]
    assert len(rev_lists) == 1
    literals = [arg.value for arg in rev_lists[0].args if isinstance(arg, ast.Constant)]
    assert "--no-merges" in literals
