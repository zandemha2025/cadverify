#!/usr/bin/env python3
"""Enforce hook attestation on new commits and reject checked-in bypasses.

Git does not record whether `git commit --no-verify` was used. The enforceable
signal is a trailer written only after the repository pre-commit gate succeeds.
The introducing PR is a bootstrap exception; every later commit in CI range must
carry the trailer. CI also rejects operational uses of --no-verify/hooksPath.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
POLICY = pathlib.Path(__file__).relative_to(ROOT).as_posix()
HOOKS = {".githooks/pre-commit", ".githooks/commit-msg"}
SCAN_ROOTS = (".github", "scripts")
BYPASS = re.compile(r"(?:--no-verify|core\.hooksPath)")
ATTESTATION = "ProofShape-Hooks: passed"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def commit_range() -> str:
    base = os.getenv("GITHUB_BASE_REF")
    before = os.getenv("GITHUB_EVENT_BEFORE")
    if base:
        subprocess.run(["git", "fetch", "origin", base, "--depth=1"], cwd=ROOT, check=False)
        return f"origin/{base}..HEAD"
    if before and set(before) != {"0"}:
        return f"{before}..HEAD"
    return "HEAD~1..HEAD"


def main() -> int:
    working_tree_only = "--working-tree-only" in sys.argv[1:]
    missing = [p for p in HOOKS if not (ROOT / p).is_file()]
    if missing:
        print(f"FAIL: missing committed hooks: {missing}")
        return 1
    found: list[str] = []
    for root in SCAN_ROOTS:
        for path in (ROOT / root).rglob("*"):
            if not path.is_file() or path.relative_to(ROOT).as_posix() in {POLICY, ".github/workflows/ci.yml"}:
                continue
            try:
                text = path.read_text(errors="strict")
            except (UnicodeDecodeError, OSError):
                continue
            for no, line in enumerate(text.splitlines(), 1):
                if BYPASS.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{no}")
    if found:
        print("FAIL: operational git-hook bypass text found: " + ", ".join(found))
        return 1

    if working_tree_only:
        print("commit-hook-policy OK (working tree)")
        return 0

    rng = commit_range()
    commits = git("rev-list", "--no-merges", rng).splitlines()
    base_ref = rng.split("..", 1)[0]
    bootstrap = subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}:.githooks/commit-msg"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode != 0
    if bootstrap:
        print("commit-hook-policy OK (bootstrap: base predates attestation hooks)")
        return 0
    bad = [sha for sha in commits if ATTESTATION not in git("show", "-s", "--format=%B", sha)]
    if bad:
        print("FAIL: commits lack hook attestation: " + ", ".join(bad))
        return 1
    print(f"commit-hook-policy OK ({len(commits)} attested commit(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
