# Error-Decomposition agent — run log

**Status:** DONE (not blocked). **Date:** 2026-06-29. **Network:** zero.

## What ran
- Engine sequence `src.costing.cli._run_engine` + `estimate_decision` on 4 real parts
  (thin flat panel `Art2SideCover`, flat bracket `ECU_Firewall_mount`, large rotational
  `FD3S_throttle_body`, small rotational `Ford_Parktronik`) at qty {1, 100, 1000, 5000}.
- Independent STAND-IN yardsticks via `src.costing.harness` reference bands (R1 AM
  volumetric / R2 CNC MRR / R3 IM tooling) — different math than the engine.
- Bucket-1 rate-sensitivity sweep (labor 25–60, margin 0–50%, machine ±40%, region US/CN/EU,
  realistic-price combo) on each headline process at qty 100 + 1000.
- Bucket-2 routing probe: rotational parts re-run as `aluminum` vs default `polymer`;
  confirmed `SHEET_METAL` ∈ `ProcessType` but ∉ `COSTED_PROCESSES`, and its analyzer
  returns fail/score 0 on the solid panel STL.

## Outputs
- Deliverable: `outputs/error-decomposition.md`
- Driver: `scratchpad/decomp.py`; raw capture: `scratchpad/decomp_out.txt`

## Headline result
Absolute-$ error (engine self-declares ±40–60%) decomposes as: **(1) default rates ±44–47%
+ structural −20–33% from margin=0 — biggest removable, killed by per-shop calibration; (2)
routing ≈0 when right but 2×–6× on the misrouted class (panel→stamping gap; polymer→aluminum
class guess); (3) cycle-time/process-model ±30–60% per-process (MJF/SLS −50%, FDM +40–180%,
turning −30%); (4) irreducible business variance ~±20–35% (stand-in), only removed by
binding to a shop + measuring held-out residuals.** No real ground truth used; all
yardsticks labeled STAND-IN; real ±X% PENDING Zoox.
