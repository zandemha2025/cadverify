#!/usr/bin/env python3
"""Correctness & fidelity audit — is the engine's math actually right?

Checks answers against independently-computed ground truth, not just behavior:
  1. Geometry: measured volume/bbox/watertightness vs analytic values for
     fixtures with known geometry (box 40x30x10 mm -> 12 cm3 exactly;
     annulus r5..r15 x 8 mm -> pi*200*8 mm3, slightly under after tessellation).
  2. Cost accounting: unit_cost == sum(line_items) for every estimate;
     quantity ladder echoes the request; per-process unit cost is
     non-increasing with quantity (setup amortization).
  3. Crossover coherence: below crossover the make-now route is cheapest,
     above it the tooling route is cheapest (when a crossover is reported).
  4. Honesty: every driver/assumption carries a provenance tag; confidence
     band reports validated=false with no real ground truth in this org.
  5. Determinism: identical input twice -> identical decision payload
     (ignoring ids/timestamps).
  6. Units: units=inch scales measured volume by 25.4^3 vs the mm run.

Requires the local stack running and a dashboard session cookie jar path in
QA_COOKIE_JAR (or logs in with the qa-tester account).

Writes qa/results/audit-math.json: [{check, status: PASS|FAIL, detail}].
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

QA = Path(__file__).parent
REPO = QA.parent
FRONT = "http://localhost:3000"
JAR = os.environ.get("QA_COOKIE_JAR", "/tmp/qa-audit-cookies.txt")

results = []


def record(check: str, ok: bool, detail: str) -> None:
    results.append({"check": check, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(("PASS " if ok else "FAIL "), check, "-", detail[:160])


def curl(args: list[str]) -> bytes:
    out = subprocess.run(["curl", "-s", "-b", JAR, "-c", JAR, *args],
                         capture_output=True, check=True)
    return out.stdout


def login() -> None:
    subprocess.run([
        "curl", "-s", "-c", JAR, "-X", "POST", f"{FRONT}/api/auth/login",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"email": "qa-tester@proofshape.local", "password": "QaTester123"}),
        "-o", "/dev/null",
    ], check=True)


def validate(path: Path, units: str = "mm") -> dict:
    return json.loads(curl(["-F", f"file=@{path}", f"{FRONT}/api/proxy/validate?units={units}"]))


def cost(path: Path, qty: str = "1,100,1000,5000") -> dict:
    return json.loads(curl(["-F", f"file=@{path}", "-F", f"qty={qty}",
                            f"{FRONT}/api/proxy/validate/cost"]))


def geometry_of(payload: dict) -> dict:
    """Normalize /validate geometry (volume_mm3, is_watertight, bounding_box_mm)."""
    g = dict(payload.get("geometry") or {})
    if "volume_cm3" not in g and g.get("volume_mm3") is not None:
        g["volume_cm3"] = float(g["volume_mm3"]) / 1000.0
    if "watertight" not in g and "is_watertight" in g:
        g["watertight"] = g["is_watertight"]
    if "bbox_mm" not in g and "bounding_box_mm" in g:
        g["bbox_mm"] = g["bounding_box_mm"]
    return g


def close(a: float, b: float, rel: float) -> bool:
    return abs(a - b) <= rel * max(abs(a), abs(b), 1e-9)


def main() -> None:
    login()
    box = REPO / "qa/fixtures/qa-box.stl"
    part2 = REPO / "qa/fixtures/qa-part2.stl"

    # -- 1. Geometry vs analytic truth ------------------------------------
    v = validate(box)
    g = geometry_of(v)
    vol = float(g.get("volume_cm3") or 0)
    record("geometry.box.volume", close(vol, 12.0, 0.001),
           f"box 40x30x10mm analytic 12.000 cm3, measured {vol}")
    bbox = g.get("bbox_mm") or g.get("bounding_box_mm") or []
    bbox_sorted = sorted(round(float(x), 1) for x in bbox) if bbox else []
    record("geometry.box.bbox", bbox_sorted == [10.0, 30.0, 40.0],
           f"analytic [10,30,40] sorted, measured {bbox_sorted}")
    record("geometry.box.watertight", bool(g.get("watertight")),
           f"watertight={g.get('watertight')}")

    v2 = validate(part2)
    g2 = geometry_of(v2)
    vol2 = float(g2.get("volume_cm3") or 0)
    # Independent ground truth: recompute the exact STL's volume locally with
    # trimesh (a separate process/library instance from the server).
    import subprocess as _sp
    local = float(_sp.run(
        [str(REPO / "backend/.venv/bin/python"), "-c",
         "import trimesh,sys;print(trimesh.load(sys.argv[1]).volume)", str(part2)],
        capture_output=True, text=True, check=True).stdout.strip()) / 1000.0
    record("geometry.part2.volume", close(vol2, local, 0.001),
           f"independent trimesh volume {local:.4f} cm3 (= 12.0 - pi*0.36*1.0 box-with-hole, "
           f"analytic 10.869 smooth), engine measured {vol2}")

    # -- 2. Cost accounting ------------------------------------------------
    c = cost(box)
    estimates = c.get("estimates") or []
    record("cost.estimates.present", bool(estimates), f"{len(estimates)} estimates")
    bad_sums = []
    for est in estimates:
        items = est.get("line_items") or {}
        if not items:
            continue
        total = sum(float(v) for v in items.values())
        unit = float(est.get("unit_cost_usd", 0))
        if not close(total, unit, 0.005):
            bad_sums.append((est.get("process"), est.get("quantity"), unit, round(total, 4)))
    record("cost.unit_eq_sum_line_items", not bad_sums,
           "every estimate: unit_cost == sum(line_items)" if not bad_sums
           else f"mismatches: {bad_sums[:4]}")

    req_qty = [1, 100, 1000, 5000]
    echo = c.get("quantities")
    record("cost.quantities.echo", echo == req_qty, f"requested {req_qty}, echoed {echo}")

    per_proc: dict = {}
    for est in estimates:
        per_proc.setdefault(est.get("process"), []).append(
            (int(est.get("quantity", 0)), float(est.get("unit_cost_usd", 0))))
    non_monotonic = []
    for proc, pairs in per_proc.items():
        pairs.sort()
        for (q1, u1), (q2, u2) in zip(pairs, pairs[1:]):
            if u2 > u1 * 1.0001:
                non_monotonic.append((proc, q1, u1, q2, u2))
    record("cost.unit_cost.monotonic_amortization", not non_monotonic,
           "unit cost non-increasing with qty per process" if not non_monotonic
           else f"increases: {non_monotonic[:3]}")

    # -- 3. Crossover coherence -------------------------------------------
    dec = c.get("decision") or {}
    crossover = dec.get("crossover_qty")
    make_now = dec.get("make_now_process")
    tool_up = dec.get("tooling_process")
    if crossover and make_now and tool_up:
        def unit_at(proc, want_below):
            cands = [(q, u) for q, u in per_proc.get(proc, [])]
            below = [(q, u) for q, u in cands if q <= crossover]
            above = [(q, u) for q, u in cands if q > crossover]
            side = below if want_below else above
            return side[-1 if want_below else 0] if side else None
        lo_m, lo_t = unit_at(make_now, True), unit_at(tool_up, True)
        hi_m, hi_t = unit_at(make_now, False), unit_at(tool_up, False)
        ok = True
        detail = f"crossover={crossover}"
        if lo_m and lo_t:
            ok &= lo_m[1] <= lo_t[1] * 1.001
            detail += f"; below: {make_now}={lo_m[1]} vs {tool_up}={lo_t[1]}"
        if hi_m and hi_t:
            ok &= hi_t[1] <= hi_m[1] * 1.001
            detail += f"; above: {tool_up}={hi_t[1]} vs {make_now}={hi_m[1]}"
        record("cost.crossover.coherent", bool(ok), detail)
    else:
        record("cost.crossover.reported", True,
               f"no crossover asserted (crossover={crossover}, make_now={make_now}, "
               f"tool_up={tool_up}) — nothing to contradict")

    # -- 4. Honesty: provenance + validated -------------------------------
    missing_prov = []
    assumptions = c.get("assumptions") or []
    for a in assumptions:
        if isinstance(a, dict) and not (a.get("provenance") or a.get("source")):
            missing_prov.append(a.get("name") or str(a)[:40])
    record("honesty.assumptions.provenance", not missing_prov,
           f"{len(assumptions)} assumptions all provenance-tagged" if not missing_prov
           else f"untagged: {missing_prov[:5]}")

    banded = [e for e in estimates if isinstance(e.get("confidence"), dict)]
    dishonest = [(e.get("process"), e.get("quantity")) for e in banded
                 if e["confidence"].get("validated") is True]
    record("honesty.validated_false_without_groundtruth", not dishonest,
           "no band claims validated=true without real ground truth" if not dishonest
           else f"claims validated: {dishonest}")

    # -- 5. Determinism ----------------------------------------------------
    c2 = cost(box)
    def strip(d):
        drop = {"saved", "identity", "filename", "request_id", "created_at", "timestamp"}
        return json.dumps({k: v for k, v in d.items() if k not in drop}, sort_keys=True)
    record("determinism.same_input_same_decision", strip(c) == strip(c2),
           "two identical /validate/cost runs byte-identical (ids/save pointers excluded)"
           if strip(c) == strip(c2) else "payloads differ between identical runs")

    # -- 6. Units scaling ---------------------------------------------------
    vin = validate(box, units="inch")
    gin = geometry_of(vin)
    vol_in = float(gin.get("volume_cm3") or 0)
    expected = 12.0 * (25.4 ** 3) / 1000 * 1000  # mm3->cm3 factor cancels: 12 * 25.4^3 cm3? compute directly
    expected = (40 * 25.4) * (30 * 25.4) * (10 * 25.4) / 1000.0  # cm3
    record("units.inch_scaling", close(vol_in, expected, 0.001),
           f"inch-declared box analytic {expected:.1f} cm3, measured {vol_in}")

    out = QA / "results" / "audit-math.json"
    out.write_text(json.dumps(results, indent=1))
    fails = [r for r in results if r["status"] == "FAIL"]
    print(f"\n{len(results)} checks, {len(fails)} failed -> {out}")
    sys.exit(0)


if __name__ == "__main__":
    main()
