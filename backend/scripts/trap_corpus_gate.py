#!/usr/bin/env python3
"""Trap corpus gate (Astra contract 2026-09-12).

Every verifier change must keep this corpus green. Expected verdicts are
code-grounded (thresholds read from fdm.py/sla.py at manifest authoring).
KNOWN-GAP rows hold known missing capability open: they may fail without
breaking CI, but they are always reported loudly.

Run from the repo root:  python backend/scripts/trap_corpus_gate.py
Exit 0 = corpus green; exit 1 = any non-KNOWN-GAP row failed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

import trimesh  # noqa: E402

from src.analysis.base_analyzer import analyze_geometry  # noqa: E402
from src.analysis.context import GeometryContext  # noqa: E402
from src.analysis.features import detect_all as detect_features  # noqa: E402
from src.analysis.models import ProcessType  # noqa: E402
from src.analysis.processes import get_analyzer  # noqa: E402  (import registers all analyzers)

CORPUS_DIR = BACKEND / "tests" / "trap-corpus"

# Manifest gate name -> Issue.code values that check produces
# (backend/src/analysis/processes/checks.py).
GATE_CODES = {
    "wall_thickness": {"THIN_WALL"},
    "overhangs": {"OVERHANG"},
    "small_features": {"SMALL_FEATURES"},
    "build_volume": {"EXCEEDS_BUILD_VOLUME"},
    "aspect_ratio": {"EXTREME_ASPECT_RATIO"},
    "trapped_volumes": {"TRAPPED_VOLUME"},
}


def run_fixture(entry: dict) -> list[str]:
    """Return the list of expectation failures for one fixture (empty = green)."""
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
    if "unit_flag" in geo_exp:
        # T3 capability: unit/scale detection. Absent today by design.
        flag = getattr(geometry, "unit_flag", None)
        if flag != geo_exp["unit_flag"]:
            failures.append(
                f"geometry.unit_flag expected {geo_exp['unit_flag']!r}, got {flag!r} (capability absent)"
            )

    for proc_name, rules in expect.items():
        if proc_name == "geometry":
            continue
        analyzer = get_analyzer(ProcessType(proc_name))
        if analyzer is None:
            failures.append(f"no analyzer registered for process {proc_name!r}")
            continue
        issues = analyzer.analyze(ctx)
        codes = {i.code for i in issues}

        if "issues" in rules:
            want = set(rules["issues"])
            if not want and codes:
                failures.append(f"{proc_name}: expected zero issues, got {sorted(codes)}")

        for gate in rules.get("gates_trip", []):
            gate_codes = GATE_CODES.get(gate)
            if gate_codes is None:
                failures.append(f"unknown gate {gate!r} in manifest")
                continue
            if not (gate_codes & codes):
                failures.append(
                    f"{proc_name}: gate {gate} expected to trip, codes present: {sorted(codes) or 'none'}"
                )
        for gate in rules.get("gates_absent", []):
            gate_codes = GATE_CODES.get(gate)
            if gate_codes is None:
                failures.append(f"unknown gate {gate!r} in manifest")
                continue
            if gate_codes & codes:
                failures.append(f"{proc_name}: gate {gate} expected absent, but tripped")

    return failures


def main() -> int:
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text())
    known_gap_failures: list[str] = []
    hard_failures: list[str] = []

    for entry in manifest["fixtures"]:
        cls = entry.get("class", "")
        failures = run_fixture(entry)
        if cls == "KNOWN-GAP":
            if failures:
                known_gap_failures.append(f"  KNOWN-GAP {entry['file']}: " + "; ".join(failures))
            else:
                print(f"  NOTE: KNOWN-GAP {entry['file']} unexpectedly green - capability landed; promote this row out of KNOWN-GAP")
        elif failures:
            hard_failures.append(f"  FAIL {entry['file']} [{cls}]: " + "; ".join(failures))
        else:
            print(f"  ok   {entry['file']} [{cls}]")

    print()
    if known_gap_failures:
        print("KNOWN-GAP REPORT (gap held open, does not break CI):")
        for line in known_gap_failures:
            print(line)
        print()
    if hard_failures:
        print("TRAP CORPUS FAILURES:")
        for line in hard_failures:
            print(line)
        return 1
    print("trap corpus green (KNOWN-GAP rows reported above stay open until their capability lands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
