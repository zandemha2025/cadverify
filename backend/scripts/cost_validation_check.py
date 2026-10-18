#!/usr/bin/env python3
"""Fail-closed private context audit. This is not an estimate-accuracy test."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "backend/data/cost-validation/validation-set-v1.json"
OUT = REPO / "outputs/cost-validation-check.json"
REQUIRED_QUOTE_LOCK = {"geometry_hash", "quantity", "material", "finish", "location", "lead_time", "quoted_at", "quoted_total"}


def check(entry: dict) -> dict:
    missing = sorted(REQUIRED_QUOTE_LOCK - set(entry))
    if missing:
        return {"entry": entry["id"], "verdict": "CONTEXT_ONLY", "accuracy_eligible": False,
                "detail": "not quote-locked; missing " + ", ".join(missing)}
    return {"entry": entry["id"], "verdict": "QUOTE_LOCKED", "accuracy_eligible": True,
            "detail": "all quote-lock fields present; accuracy evaluation belongs in a separate geometry replay gate"}


def main() -> int:
    data = json.loads(DATA.read_text())
    results = [check(e) for e in data["entries"]]
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "set": data["schema"],
              "accuracy_claim": False, "results": results,
              "summary": {"quote_locked": sum(r["accuracy_eligible"] for r in results),
                          "context_only": sum(not r["accuracy_eligible"] for r in results)}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    for result in results:
        print(f"{result['verdict']:>15}  {result['entry']}: {result['detail']}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
