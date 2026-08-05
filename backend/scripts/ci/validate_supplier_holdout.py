#!/usr/bin/env python3
"""Block commercial promotion unless protected supplier evidence passes."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

# Load the stdlib-only contract by file path. Importing ``src.costing`` normally
# executes its dependency-heavy package initializer; the promotion runner has
# intentionally not installed the application, and this gate must not add a
# mutable dependency-install step before deployment.
BACKEND_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = BACKEND_ROOT / "src" / "costing" / "supplier_holdout.py"
_spec = importlib.util.spec_from_file_location(
    "cadverify_supplier_holdout_contract", CONTRACT_PATH
)
if _spec is None or _spec.loader is None:
    raise RuntimeError("could not load supplier holdout contract")
_contract = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _contract
_spec.loader.exec_module(_contract)

SupplierHoldoutError = _contract.SupplierHoldoutError
load_protected_evidence = _contract.load_protected_evidence


def _append_github_file(env_name: str, line: str) -> None:
    destination = os.getenv(env_name)
    if destination:
        with Path(destination).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def main() -> int:
    try:
        _evidence, evidence_sha256 = load_protected_evidence()
    except SupplierHoldoutError as exc:
        print(f"Supplier holdout promotion gate BLOCKED: {exc}", file=sys.stderr)
        return 1

    _append_github_file("GITHUB_OUTPUT", f"evidence_sha256={evidence_sha256}")
    _append_github_file(
        "GITHUB_ENV",
        f"CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_SHA256={evidence_sha256}",
    )
    print(
        "Supplier holdout promotion gate PASS "
        f"(evidence_sha256={evidence_sha256})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
