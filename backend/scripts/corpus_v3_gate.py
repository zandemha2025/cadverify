#!/usr/bin/env python3
"""Corpus v3 gate (GLM seat 2026-09-14), extends the trap-corpus v1.2 contract.

Differences from v1.2 gate (backend/scripts/trap_corpus_gate.py):
- Expectations assert raw Issue codes (codes_trip / codes_absent) for ANY
  registered process, not only the six FDM/SLA gate names.
- Optional severity_of pins an expected severity per code.
- Fixture integrity is verified against SHA256SUMS.txt before analysis.
- KNOWN-GAP semantics unchanged: rows that hold a known divergence open are
  reported loudly but do not break CI; a KNOWN-GAP row turning green is
  reported as promotable.

Run from the repo root:  python backend/scripts/corpus_v3_gate.py
Exit 0 = all non-KNOWN-GAP rows green and hashes intact; exit 1 otherwise.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import trimesh  # noqa: E402
try:
    import rtree  # noqa: E402
except ImportError as exc:  # pragma: no cover - exercised by the CI import guard
    raise SystemExit(
        "corpus v3 requires locked rtree==1.4.1; install requirements-prod.lock"
    ) from exc

if rtree.__version__ != "1.4.1":
    raise SystemExit(
        f"corpus v3 requires locked rtree==1.4.1, found {rtree.__version__}"
    )

from src.analysis.base_analyzer import analyze_geometry  # noqa: E402
from src.analysis.context import GeometryContext  # noqa: E402
from src.analysis.features import detect_all as detect_features  # noqa: E402
from src.analysis.models import ProcessType, Severity  # noqa: E402
from src.analysis.processes import get_analyzer  # noqa: E402  (import registers all)

CORPUS_DIR = BACKEND / "tests" / "corpus-v3"


def verify_hashes() -> list[str]:
    sums_file = CORPUS_DIR / "SHA256SUMS.txt"
    failures: list[str] = []
    expected = {}
    for line in sums_file.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        expected[name.strip()] = digest.strip()
    for name, digest in expected.items():
        path = CORPUS_DIR / name
        if not path.exists():
            failures.append(f"missing fixture {name}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            failures.append(f"hash mismatch {name}: manifest {digest[:12]}... != actual {actual[:12]}...")
    return failures


def run_fixture(entry: dict) -> list[str]:
    failures: list[str] = []
    path = CORPUS_DIR / entry["file"]
    mesh = trimesh.load(str(path))
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_geometry()
    geometry = analyze_geometry(mesh)
    ctx = GeometryContext.build(mesh, geometry)
    ctx.features = detect_features(ctx.mesh)

    expect = entry.get("expect", {})
    geo_exp = expect.get("geometry", {})
    if "is_watertight" in geo_exp:
        if bool(geometry.is_watertight) != bool(geo_exp["is_watertight"]):
            failures.append(
                f"geometry.is_watertight expected {geo_exp['is_watertight']}, got {geometry.is_watertight}"
            )

    for proc_name, rules in expect.items():
        if proc_name == "geometry":
            continue
        analyzer = get_analyzer(ProcessType(proc_name))
        if analyzer is None:
            failures.append(f"no analyzer registered for process {proc_name!r}")
            continue
        issues = analyzer.analyze(ctx)
        by_code = {}
        for i in issues:
            by_code.setdefault(i.code, i)
        codes = set(by_code)

        for code in rules.get("codes_trip", []):
            if code not in codes:
                failures.append(
                    f"{proc_name}: code {code} expected to trip, codes present: {sorted(codes) or 'none'}"
                )
        for code in rules.get("codes_absent", []):
            if code in codes:
                failures.append(f"{proc_name}: code {code} expected absent, but tripped")
        for code, want_sev in rules.get("severity_of", {}).items():
            issue = by_code.get(code)
            if issue is None:
                failures.append(f"{proc_name}: severity pin for {code} but code did not trip")
            elif issue.severity != Severity[want_sev]:
                failures.append(
                    f"{proc_name}: {code} severity expected {want_sev}, got {issue.severity.name}"
                )
    return failures


def main() -> int:
    hash_failures = verify_hashes()
    manifest = json.loads((CORPUS_DIR / "manifest_v3.json").read_text())
    known_gap_failures: list[str] = []
    hard_failures: list[str] = []
    promotable: list[str] = []

    for entry in manifest["fixtures"]:
        cls = entry.get("class", "")
        failures = run_fixture(entry)
        if cls == "KNOWN-GAP":
            if failures:
                known_gap_failures.append(f"  KNOWN-GAP {entry['file']}: " + "; ".join(failures))
            else:
                promotable.append(entry["file"])
                print(f"  NOTE: KNOWN-GAP {entry['file']} unexpectedly green - capability landed; promote this row")
        elif failures:
            hard_failures.append(f"  FAIL {entry['file']} [{cls}]: " + "; ".join(failures))
        else:
            print(f"  ok   {entry['file']} [{cls}]")

    print()
    coverage = {}
    for entry in manifest["fixtures"]:
        for proc in entry.get("expect", {}):
            if proc != "geometry":
                coverage[proc] = coverage.get(proc, 0) + 1
    print("COVERAGE (processes with at least one v3 expectation):", ", ".join(sorted(coverage)))
    uncovered = [p.value for p in ProcessType if p.value not in coverage]
    if uncovered:
        print("STILL UNCOVERED:", ", ".join(sorted(uncovered)))
    print()
    if known_gap_failures:
        print("KNOWN-GAP REPORT (divergences held open, do not break CI):")
        for line in known_gap_failures:
            print(line)
        print()
    if hash_failures:
        print("FIXTURE INTEGRITY FAILURES:")
        for line in hash_failures:
            print(" ", line)
    if hard_failures:
        print("CORPUS V3 FAILURES:")
        for line in hard_failures:
            print(line)
    if hard_failures or hash_failures:
        return 1
    print("corpus v3 green (KNOWN-GAP rows above stay open until their fix lands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
