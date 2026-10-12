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


def test_pr_range_preserves_base_ancestry(tmp_path, monkeypatch):
    import importlib.util
    import subprocess
    policy_path = Path("scripts/ci/check_commit_hook_policy.py").resolve()
    spec = importlib.util.spec_from_file_location("hook_policy", policy_path)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    source = tmp_path / "source"
    source.mkdir()
    def git(*args, cwd=source):
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()
    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("commit", "--allow-empty", "-m", "old history")
    git("commit", "--allow-empty", "-m", "base")
    git("checkout", "-b", "feature")
    git("commit", "--allow-empty", "-m", "new change")
    expected = git("rev-parse", "HEAD")
    git("checkout", "main")
    git("commit", "--allow-empty", "-m", "main advances")
    git("checkout", "feature")
    git("merge", "--no-edit", "main")
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", str(source), str(checkout)], check=True, capture_output=True)
    monkeypatch.setattr(policy, "ROOT", checkout)
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    rng = policy.commit_range()
    assert policy.git("rev-list", "--no-merges", rng).splitlines() == [expected]
