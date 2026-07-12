"""Per-shop calibration — create/save/load two shop profiles and re-cost one
deterministic calibration part with each.

Run from the backend dir (engine imports `from src...`):
    .venv/bin/python scripts/calibration_demo.py [PART.stl]

Zero network. Writes example profiles to the local store (backend/data/shop_profiles).
"""

from __future__ import annotations

import os
import sys

from src.costing import (
    EstimateOptions, estimate_decision, render_text,
    ShopProfile, save_profile, load_profile, list_profiles,
)
from src.costing.cli import _run_engine
from src.costing.harness import MEDIUM_FLAT_MOUNT, ensure_fixture_parts_dir

PARTS_DIR = ensure_fixture_parts_dir()
DEFAULT_PART = MEDIUM_FLAT_MOUNT


def example_profiles():
    """Two real-shaped shops. Each pins region_multipliers (labor=1.0) because its
    labor_rate is the shop's ABSOLUTE loaded rate — so no regional factor is applied
    twice. Anything a shop leaves unset stays a generic DEFAULT."""
    midwest = ShopProfile(
        name="Midwest Precision CNC",
        region="US",
        labor_rate=52.0,          # real loaded shop-floor rate
        margin=0.30,              # this shop quotes a price, not a should-cost
        overhead=0.15,            # indirect burden on conversion
        utilization=0.80,         # 80% spindle utilization (idle recovered in cost)
        machine_rates={
            "CNC_3AXIS": 95, "CNC_5AXIS": 135, "CNC_TURNING": 85,
            "SLS": 28, "MJF": 30, "FDM": 12, "INJECTION_MOLDING": 60,
        },
        material_prices={
            # exact-name lots + a class sentinel that catches any polymer the
            # router selects (e.g. PP (Polypropylene) for MJF)
            "@polymer": 7.0, "@aluminum": 9.0,
            "Delrin (POM)": 6.5, "PA12 (Nylon 12)": 8.0, "6061-T6 Aluminum": 9.0,
        },
        region_multipliers={"labor": 1.0, "material": 1.0, "tooling": 1.0},
        source="Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)",
        notes="Aerospace/automotive job shop, 8 CNC machines, in-house SLS.",
    )
    shenzhen = ShopProfile(
        name="Shenzhen Contract Mfg",
        region="CN",
        labor_rate=14.0,
        margin=0.10,
        overhead=0.05,
        utilization=0.92,
        machine_rates={
            "CNC_3AXIS": 45, "CNC_5AXIS": 70, "CNC_TURNING": 40,
            "SLS": 15, "MJF": 15, "FDM": 6, "INJECTION_MOLDING": 30,
        },
        material_prices={
            "@polymer": 4.5, "Delrin (POM)": 4.0, "PA12 (Nylon 12)": 5.5,
        },
        # labor pinned to 1.0 (rate is absolute); offshore tooling discount kept
        region_multipliers={"labor": 1.0, "material": 0.98, "tooling": 0.45},
        source="Supplier RFQ packet 2026-05 (quoted hourly + tooling)",
        notes="High-volume contract manufacturer, low-cost region.",
    )
    return [midwest, shenzhen]


def _headline(report):
    dec = report.decision
    q = min(report.quantities)
    r = dec.recommendation.get(q) if dec else None
    return q, (r or {})


def _line_provenance(report, process, qty):
    for e in report.estimates:
        if e["process"] == process and e["quantity"] == qty:
            return e
    return None


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PARTS_DIR, DEFAULT_PART)

    # 1) create + persist profiles, then reload (prove round-trip persistence)
    saved = []
    for p in example_profiles():
        path = save_profile(p)
        saved.append(path)
    print("Saved profiles:", *[os.path.relpath(s) for s in saved], sep="\n  ")
    print("Store now lists:", list_profiles())
    reloaded = load_profile("Midwest Precision CNC")
    assert reloaded.labor_rate == 52.0, "persistence round-trip failed"
    print(f"Reloaded '{reloaded.name}' OK (labor_rate=${reloaded.labor_rate}/hr).\n")

    # 2) re-cost the SAME deterministic part three ways
    result, mesh, feats = _run_engine(part)
    qtys = [50, 5000]
    runs = {
        "DEFAULT (no shop)": EstimateOptions(quantities=qtys),
        "Midwest Precision CNC": EstimateOptions(quantities=qtys, shop="Midwest Precision CNC"),
        "Shenzhen Contract Mfg": EstimateOptions(quantities=qtys, shop="Shenzhen Contract Mfg"),
    }

    print(f"PART: {os.path.basename(part)}")
    print("=" * 78)
    rows = []
    for label, opts in runs.items():
        rep = estimate_decision(result, mesh, feats, opts)
        assert rep.status == "OK", rep.reason
        # Σ invariant on every estimate
        for e in rep.estimates:
            s = round(sum(e["line_items"].values()), 2)
            assert abs(e["unit_cost_usd"] - s) < 0.02, (label, e["process"], e["unit_cost_usd"], s)
        q, r = _headline(rep)
        rows.append((label, r.get("process"), r.get("material"), r.get("unit_cost_usd")))
        print(f"\n### {label}")
        print(f"  headline @ qty {q}: {r.get('process')} / {r.get('material')} "
              f"= ${r.get('unit_cost_usd')}/unit")
        # show provenance of one common process line so DEFAULT vs SHOP is visible
        proc = r.get("process")
        e = _line_provenance(rep, proc, q)
        if e:
            for d in e["drivers"]:
                if d["name"] in ("material_cost", "machine_cost", "labor_cost",
                                 "setup_cost"):
                    print(f"      {d['name']:<14} ${d['value']:<9} [{d['provenance']}]")
            li = e["line_items"]
            print(f"      Σ line_items = ${round(sum(li.values()),2)} == unit "
                  f"${e['unit_cost_usd']}  ✓")

    # 3) zoom on cnc_3axis @ qty 50 — where machine $/hr AND material lot price
    #    both bind, so material_cost flips MEASURED -> SHOP
    print("\n" + "-" * 78)
    print("CNC_3AXIS @ qty 50 — material price + machine rate binding:")
    for label, opts in runs.items():
        rep = estimate_decision(result, mesh, feats, opts)
        e = _line_provenance(rep, "cnc_3axis", 50)
        if not e:
            continue
        mat = next(d for d in e["drivers"] if d["name"] == "material_cost")
        mac = next(d for d in e["drivers"] if d["name"] == "machine_cost")
        print(f"  {label:<24} unit ${e['unit_cost_usd']:<8} "
              f"material ${mat['value']} [{mat['provenance']}]  "
              f"machine ${mac['value']} [{mac['provenance']}]")

    print("\n" + "=" * 78)
    print("HEADLINE COST BY PROFILE (same part, same geometry):")
    base = rows[0][3]
    for label, proc, mat, cost in rows:
        delta = f"({(cost/base-1)*100:+.0f}% vs DEFAULT)" if base else ""
        print(f"  {label:<24} {proc:<16} ${cost:>8}/unit  {delta}")
    print("\nSwitching the profile visibly changes the cost — bucket #1 bound + measured.")


if __name__ == "__main__":
    main()
