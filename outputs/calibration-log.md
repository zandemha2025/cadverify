# Calibration-Builder — build log

**Agent:** Calibration-Builder (Cost-Truth cycle) · **Date:** 2026-06-29 · **Egress:** zero

## Goal
Kill error-bucket #1 (generic default rates, measured ±44–47% in
`outputs/error-decomposition.md`) by binding every cost DEFAULT to ONE shop's real
numbers — a persisted, glass-box `ShopProfile` — without regressing the existing layer.

## Status: DONE (RUNS on real parts)

## What was built
- `backend/src/costing/shop_profile.py` — `ShopProfile` dataclass (labor, per-process
  machine $/hr, material lot prices, utilization, overhead, margin, region), JSON
  save/load/list to a local store (`backend/data/shop_profiles/`, no egress), and
  `resolve_shop`/`to_shop_overrides`.
- `backend/src/costing/provenance.py` — added `Provenance.SHOP` (4th tag).
- `backend/src/costing/rates.py` — `overhead` (default 0) + `utilization` (default 1)
  global levers (no-ops at default); `material_prices` map; `RateCard` now tracks
  `shop_keys`/`shop_name`/`shop_region`, with `prov_tag` returning SHOP, plus
  `material_price()` and `region_prov()`; `build_rate_card(..., shop_overrides=...)`
  applies SHOP bindings then USER overrides (USER wins).
- `backend/src/costing/cost_model.py` — material uses the shop lot price when bound
  (flips MEASURED→SHOP); machine cost ÷ utilization; machine/labor/setup × (1+overhead);
  region_split provenance via `rates.region_prov`.
- `backend/src/costing/estimate.py` — `EstimateOptions.shop` + `region_is_user`;
  binds the shop, selects its region, adds overhead/utilization/shop assumptions + a
  "calibrated to shop X" note listing which rates are SHOP-bound (gaps stay DEFAULT).
- `backend/src/costing/cli.py` — `--shop <name|path>` flag.
- `backend/tests/test_costing_calibration.py` — 12 new tests.
- `backend/scripts/calibration_demo.py` — reproducible end-to-end demo (creates two
  example profiles, re-costs a real part three ways).
- `backend/data/shop_profiles/{midwest-precision-cnc,shenzhen-contract-mfg}.json`.
- `outputs/calibration-readme.md` — full docs + real captured before/after.

## Verification (all run, real outputs)
- `test_costing_calibration.py` — **12 passed** (persistence round-trip, provenance
  DEFAULT→SHOP, USER-beats-SHOP precedence, unset-keys-stay-DEFAULT, material exact-name
  vs @class, overhead/utilization no-op-at-default + raises-when-set, region binding,
  Σ-invariant).
- `test_costing_model.py` — **14 passed** (no regression).
- `test_cost_api.py` — **18 passed** (no regression; API default path stays
  MEASURED/USER/DEFAULT).
- `test_costing_gates.py` (real parts) — **16 passed**.
- `test_costing_accuracy.py` (real parts, harness, zero-egress) — **10 passed**.
- `scripts/calibration_demo.py` on the real ECU Firewall Mount — runs; headline MJF
  @ qty 50: DEFAULT **$44.13** → Midwest **$110.49 (+150%)** → Shenzhen **$35.29 (−20%)**;
  every line tagged SHOP/DEFAULT/MEASURED; `unit_cost == Σ(line_items)` holds in all.

## Acceptance test — PASS
With a shop profile loaded, real repo parts re-cost using the shop's numbers; every
line item shows profile (SHOP) vs generic (DEFAULT); switching profiles visibly changes
the cost; `unit_cost == Σ(line_items)` holds; existing tests still pass.

## Notes / coordination
- Built on top of the existing rate-card override path — no rebuild. SHOP bindings reuse
  the exact dotted-key mechanism USER overrides already used.
- Concurrent cycle agent (Routing-Builder) was editing `rates.py`/`cost_model.py`/
  `estimate.py`/`report.py` in parallel (adding SHEET_METAL/geometric routing). Their
  changes integrated cleanly around this calibration code; all my edits survived and the
  combined suite is green. (One transient mid-write moment of their routing block was
  observed and self-resolved on their next save — not a calibration defect.)
- No accuracy claim is made. Calibration removes the *rate* error (bucket #1); it does
  not validate against real quotes. The real ±Y% remains PENDING ground truth.
