#!/usr/bin/env python3
"""Enforce a pyright error-count ratchet so the typecheck gate can be blocking.

Context (F-ARCH-7 CI audit): `pyright src/ --pythonversion 3.12 --pythonpath
<active-ci-python>` currently reports a real, pre-existing 230 errors across
~55 files (Trimesh's
`Geometry` vs `Trimesh` union typing, optional GPU deps like torch/pyrender
that are deliberately absent from requirements.txt, gmsh/OCP/cadquery
possibly-unbound patterns from optional-import guards, and None-safety gaps
in the costing module). Flipping the CI step straight to blocking would turn
every PR red for pre-existing debt unrelated to the change being reviewed —
that is worse than the `continue-on-error: true` it replaces, because a
gate nobody can pass gets bypassed or ignored.

Instead this makes the gate real without lying about the debt: fail CI only
when the error count *regresses* past the checked-in baseline. Fixing errors
and lowering PYRIGHT_BASELINE_FILE in the same PR is how the baseline ratchets
down toward zero over time; introducing new errors that push the count above
baseline fails the build.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASELINE_FILE = Path(__file__).parent / "pyright_baseline.txt"


def load_baseline() -> int:
    text = BASELINE_FILE.read_text(encoding="utf-8").strip()
    return int(text)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_pyright_baseline.py <pyright-outputjson-file>")
        return 2

    report_path = Path(argv[1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    error_count = report["summary"]["errorCount"]
    baseline = load_baseline()

    print(f"pyright: {error_count} error(s) (baseline: {baseline})")

    if error_count > baseline:
        print(
            f"FAIL: pyright error count regressed ({error_count} > {baseline}). "
            "Fix the new error(s) or, if intentional, explain why in the PR — "
            "do not bump the baseline just to silence this."
        )
        return 1

    if error_count < baseline:
        print(
            f"NOTE: pyright error count improved ({error_count} < {baseline}). "
            f"Consider lowering {BASELINE_FILE.name} to {error_count} in this PR "
            "to lock in the fix."
        )

    print("pyright-baseline-check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
