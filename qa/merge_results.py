#!/usr/bin/env python3
"""Merge qa/results/*.json test verdicts into qa/user-stories.csv, then
regenerate the tracker xlsx via compile_tracker.

Each results file: JSON array of {"id", "status", "error_found", "notes"}.
Valid statuses: TESTED-PASS, TESTED-FAIL, BLOCKED, FIXED, RETEST-PASS, RETEST-FAIL.
Later files never silently overwrite a FAIL with a PASS from a different file:
a conflict on the same id is reported and the FAIL wins unless --force-last.
"""
import csv
import json
import sys
from pathlib import Path

QA = Path(__file__).parent
RESULTS = QA / "results"
CSV_PATH = QA / "user-stories.csv"
VALID = {"TESTED-PASS", "TESTED-FAIL", "BLOCKED", "FIXED", "RETEST-PASS", "RETEST-FAIL", "N/A"}
# RETEST-* statuses always supersede first-pass statuses.
RANK = {"RETEST-FAIL": 5, "RETEST-PASS": 4, "TESTED-FAIL": 3, "BLOCKED": 2,
        "FIXED": 1, "TESTED-PASS": 0, "N/A": 0}


def main() -> None:
    with CSV_PATH.open() as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames
        rows = {r["id"]: r for r in reader}

    updates = {}
    for path in sorted(RESULTS.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception as exc:
            print(f"SKIP {path.name}: unparseable ({exc})", file=sys.stderr)
            continue
        for item in data:
            sid = item.get("id", "").strip()
            status = item.get("status", "").strip().upper()
            if sid not in rows:
                print(f"WARN {path.name}: unknown story id {sid}", file=sys.stderr)
                continue
            if status not in VALID:
                print(f"WARN {path.name}: bad status {status} for {sid}", file=sys.stderr)
                continue
            prev = updates.get(sid)
            if prev and RANK.get(prev["status"], 0) > RANK.get(status, 0):
                print(f"CONFLICT {sid}: keeping {prev['status']} over {status}", file=sys.stderr)
                continue
            updates[sid] = {
                "status": status,
                "error_found": (item.get("error_found") or "").strip(),
                "notes": (item.get("notes") or "").strip(),
                "src": path.name,
            }

    for sid, upd in updates.items():
        row = rows[sid]
        row["status"] = upd["status"]
        if upd["error_found"]:
            row["error_found"] = upd["error_found"]
        if upd["notes"]:
            row["notes"] = upd["notes"]

    with CSV_PATH.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows.values())

    counts = {}
    for r in rows.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"merged {len(updates)} verdicts into {CSV_PATH}")
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}")

    import subprocess
    subprocess.run([sys.executable, str(QA / "compile_tracker.py")], check=True)


if __name__ == "__main__":
    main()
