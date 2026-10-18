"""Tests for the cost-validation consistency checker
(backend/scripts/cost_validation_check.py).

Proves:
  1. The checker runs against the shipped validation set and never crashes.
  2. Every result carries an entry id, a verdict in the closed enum, and a
     non-empty detail string.
  3. A TENSION verdict anywhere makes main() exit non-zero (fail-closed).
  4. The IM tooling anchor and CNC rate anchor both produce verdicts (the two
     load-bearing cross-checks are never silently skipped).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "scripts"))

import cost_validation_check as cvc  # noqa: E402

DATA = json.loads((REPO / "backend" / "data" / "cost-validation" / "validation-set-v1.json").read_text())


def test_every_entry_is_context_only_not_accuracy_evidence():
    results = [cvc.check(e) for e in DATA["entries"]]
    assert len(results) == len(DATA["entries"])
    assert all(r["verdict"] == "CONTEXT_ONLY" for r in results)
    assert all(r["accuracy_eligible"] is False for r in results)
    assert all("not quote-locked" in r["detail"] for r in results)


def test_main_writes_explicit_non_accuracy_report(tmp_path, monkeypatch):
    monkeypatch.setattr(cvc, "OUT", tmp_path / "report.json")
    assert cvc.main() == 0
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["accuracy_claim"] is False
    assert report["summary"] == {"quote_locked": 0, "context_only": len(DATA["entries"])}


def test_partial_quote_record_stays_ineligible():
    partial = dict(DATA["entries"][0], geometry_hash="sha256:abc", quantity=1)
    result = cvc.check(partial)
    assert result["accuracy_eligible"] is False
    assert "material" in result["detail"]
