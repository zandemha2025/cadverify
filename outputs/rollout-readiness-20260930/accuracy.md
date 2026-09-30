# Accuracy readiness — 2026-09-30

**Status: regression checks pass; real manufacturing and supplier-price validation remains blocked by missing evidence.** Work is local to `codex/rollout-readiness-20260930`, based on PR #107 commit `772f3b5`. No production writes, quote requests, customer data imports, commits, or deployments were performed in this lane.

## Evidence actually available

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| `backend/src/costing/calibration_fixtures.py`; fresh `accuracy-regression.md` in this directory | Twelve internally authored geometry coupons; 200 cost comparisons against independently authored reference formulas; 163/200 within the reference bands; all five regression criteria pass | Supplier pricing, actual manufacturing outcomes, or commercial accuracy |
| `outputs/groundtruth-report.md` | Ground-truth workflow demonstrated with **48 stand-in records and zero real records** | Real residual error, supplier quotes, or a customer-approved corpus |
| `outputs/accuracy-report.md` | Historical external automotive geometry benchmark, explicitly labeled as lacking supplier quotes and complete per-model redistribution licensing | Provenance-approved commercial holdout |
| `backend/data/shop_profiles/*.json` | Two demonstration shop profiles; `backend/scripts/calibration_demo.py:example_profiles()` authors these exact examples | Independent accounting/RFQ evidence, despite their realistic `source` strings |
| `docs/training/fixtures/ground-truth-mixed.csv`; source-artifact tests | Demonstration CSV and source-bound calibration mechanics | Production prices: the fixture is marked demo; successful tests explicitly flip isolated in-memory copies to exercise the real-data code branch |
| `outputs/zoox-calibration-protocol.md` | An earlier preparation protocol for obtaining the first real measurements | Evidence that the meeting occurred or real quotes were supplied |

The inspected checkout contains no retained real quote/invoice corpus, quote-backed calibration bundle, or approved release-bound supplier summary. This inspection did not read a production database or any external confidential evidence repository. Both `CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64` and `CADVERIFY_RELEASE_SHA` are absent from this process environment; configured values in protected GitHub environments were not inspected here.

## Fixed accuracy-claim defect

Previously, SLS-only quotes could supply a global correction multiplier and pooled residuals to CNC or injection molding. The new regression reproduced a **1.66017× CNC correction learned entirely from SLS**. An unrelated process could consequently receive `validated=true` without three observations for that process.

`Calibration.factor_for()` now returns the identity multiplier for an unrepresented process. `ResidualModel` requires the requested process's own observations; pooling remains available only for an explicitly process-agnostic report (`process=None`). Recalibration's summary and persisted bundle require at least one process that can actually produce a real empirical band, and the response lists `validated_processes`. The headline names those processes and excludes sparse processes from its claimed accuracy calculation. Old persisted bundles that passed only the pooled floor now fail closed on reload.

Independent review caught a legacy-data consequence: previously stored residuals could have been measured around the old global correction. `CalibrationBundle.residual_model()` now recomputes residuals from the retained measured baseline/actual costs and the correction the current code serves, also keeping persisted factor rounding coherent. No file migration or loss of matching-process evidence is required. Served correction factors are additionally restricted to processes with sufficient real held-out observations, so a synthetic-only CNC tuning factor cannot move CNC costs merely because SLS validated. The stored historical report/metrics are not rewritten; recalibration is needed to regenerate them under current semantics.

The regression exercises persistence/reload and `estimate_decision`: an SLS process with sufficient real test residuals remains validated, a CNC process with one test residual and a synthetic-only 100× tuning factor stays unvalidated with its original cost center, and an absent injection-molding process stays unvalidated. Another test proves eight total records spread across sparse processes cannot produce a globally validated summary. The legacy-bundle regression verifies that a retained actual cost of $20 with baseline $10 and old corrected prediction $20 still produces a coherent $20 empirical interval after the global fallback is removed.

These are **mechanics tests with explicitly simulated facts**, not newly acquired real evidence.

## Exact gates and their limits

| Gate | Existing threshold retained |
| --- | --- |
| Start an org recalibration | At least **8 non-stand-in records overall**; this is a record count, not eight independent parts per process |
| Validate a specific estimate | At least **3 real costable held-out residual records for that exact process**; synthetic rows cannot validate it; no other process can fill its shortfall |
| Recalibration summary / served persisted bundle | At least one process meets that same empirical-band threshold; `validated_processes` scopes the claim |
| Commercial promotion | At least **20 independent quoted parts**, at least **3 suppliers overall**, and at least **5 independent parts plus 3 suppliers in each** of `additive`, `cnc`, `injection_molding` |
| Commercial error limits | MAPE ≤ **0.30**, P90 absolute percentage error ≤ **0.50**, absolute median signed bias ≤ **0.25 for every covered family**; values in the secret use fractions, not percentages |
| Commercial provenance / release | Exact release SHA; provenance, license review, and exclusion from tuning all true; four retained-evidence SHA-256 digests; non-placeholder reviewer and approval identifiers |
| Freshness | Generated no more than 30 days ago or 5 minutes in the future; unexpired; validity window no more than 90 days |

The three-residual application floor is not an independent-part or commercial-accuracy certification. Repeated quotes/quantities on one part must not be counted as separate independent parts for the release holdout. The normal splitter keeps one `part_id` together, but operators must also group aliases/revisions of the same design to prevent leakage. CSV imports default to `source_type=actual`; the importer validates structure, not the authenticity of a quote. Explicit demo/seed/synthetic/stand-in source types cannot count as real.

The protected supplier gate validates an approved aggregate summary and the format of retained-evidence hashes. It does **not** download quote files, recompute results, verify an approval signature, or prove that the source records exist. Independent review of retained evidence remains necessary. The promotion workflow checks the exact release in both staging and production and requires the same evidence digest.

## Repeatable acceptance using the existing importer

1. Freeze the candidate release SHA and a private evidence directory. Obtain actual supplied CAD and quote/invoice records; do not substitute catalog prices, test-generated prices, demonstration shop rates, or published price ranges. Preserve units, part revision, licensing/permission, material/alloy, tolerances, finish, process, lot quantity, supplier identity, quote date/expiry, currency/FX basis, setup/tooling amortization, inspection, shipping/tax scope, and any relevant measured production hours. Match the engine estimate's commercial scope to the quote.
2. Keep a preselected **tuning.csv** and separate **holdout.csv** using the current importer contract. Required CSV columns are `part_id,process,quantity,actual_unit_cost_usd`. For auditable records also fill `source_type=quote|invoice`, `vendor_quote_id`, `invoice_date`, `source`, `material_class`, `region`, `currency`, `source_units`, `part_path`, and retained evidence references. `shop` selects an actual reviewed rate profile when one exists; keep supplier identity separately in the provenance manifest if using generic rates. Never use the demo profiles as if they were the supplier's rates. When using retained source-artifact plumbing, `evidence_sha256` identifies the CAD artifact; retain the quote document and its hash separately.
3. Run the existing CSV parser first. A successful import HTTP status alone is insufficient: require zero parser errors, expected row count, and no stand-in rows. Normalize monetary values to USD before putting them in `actual_unit_cost_usd`; preserve the original currency and conversion evidence outside that USD CSV. Verify source files and quote document hashes independently. Holdout must contain 20+ independent parts, with the per-family and supplier counts above; the **holdout alone** must meet these counts, not tuning plus holdout.
4. In an isolated local validation environment, use the following existing primitives to evaluate the frozen split without writing a database or served calibration. Set the three paths to the private files/directory. It writes detailed results beside the private holdout; do not commit private quote data. Review the results before creating any approval summary.

```bash
cd backend
export CADVERIFY_TUNING_CSV=/private/evidence/tuning.csv
export CADVERIFY_HOLDOUT_CSV=/private/evidence/holdout.csv
export CADVERIFY_PARTS_DIR=/private/evidence/parts
python - <<'PY'
import json
import os
from dataclasses import asdict
from pathlib import Path
from src.services.groundtruth_service import parse_ground_truth_csv
from src.costing.groundtruth import GroundTruthRecord, EngineCostCache, tune, evaluate

def read_csv(name):
    rows, errors = parse_ground_truth_csv(Path(os.environ[name]).read_text(encoding="utf-8-sig"))
    assert rows and not errors, "Empty or invalid CSV; inspect parser errors locally"
    assert all(not r["stand_in"] and r["source_type"] in {"quote", "invoice"}
               and r["currency"] == "USD" for r in rows), "Use real, normalized quote/invoice records"
    assert all(r["vendor_quote_id"] and r["source"] for r in rows), "Retain quote provenance"
    return [GroundTruthRecord.from_dict(r) for r in rows]

tuning = read_csv("CADVERIFY_TUNING_CSV")
holdout = read_csv("CADVERIFY_HOLDOUT_CSV")
assert {r.part_id for r in tuning}.isdisjoint(r.part_id for r in holdout), "Part leakage"
assert len({r.part_id for r in holdout}) >= 20, "Need 20 independent held-out parts"
cache = EngineCostCache(os.environ["CADVERIFY_PARTS_DIR"])
tuning_predictions = [cache.baseline(r) for r in tuning]
holdout_predictions = [cache.baseline(r) for r in holdout]
assert all(p.ok for p in tuning_predictions + holdout_predictions), "Missing/uncostable sources"
calibration = tune(tuning_predictions)
evaluation = evaluate(holdout_predictions, calibration, "frozen supplier holdout")
result_path = Path(os.environ["CADVERIFY_HOLDOUT_CSV"]).with_suffix(".results.json")
result_path.write_text(json.dumps({"calibration": calibration.to_dict(),
    "evaluation": asdict(evaluation)}, indent=2))
print("Saved private holdout results; independently review family/supplier coverage and errors.")
PY
```

5. An independent reviewer reconciles every residual to the retained part and quote, proves no held-out labels influenced rates/tuning, and recomputes supplier/family coverage and the three release error statistics. Keep exact engine process IDs for application validation; aggregate additive/CNC processes into the release families explicitly in the review record. The evaluator's `per_process` summary contains **mean** signed error; do not copy it into the release's **median** bias field. Compute that median from each family's residual rows. Do not tune to this holdout after inspecting failures and reuse it as untouched evidence.
6. Produce the exact `cadverify-supplier-holdout-v1` summary specified by `backend/src/costing/supplier_holdout.py`, including reviewed evidence hashes and approval identifiers. Encode the real reviewed summary into the protected `CADVERIFY_SUPPLIER_HOLDOUT_EVIDENCE_B64` value, bound to `CADVERIFY_RELEASE_SHA`. Run `python -S scripts/ci/validate_supplier_holdout.py`; then run `python -m src.costing.harness --require-production-evidence --output <review-output.md>`. Both must pass for that exact release. Do not copy synthetic values from `test_supplier_holdout_gate.py` into a real approval.
7. For org-facing feature acceptance, use an isolated org with analyst access: `GET /api/v1/ground-truth/import/template`, `POST /api/v1/ground-truth/import`, verify `imported/skipped/errors`, then `POST /api/v1/ground-truth/recalibrate`. Confirm source resolution, `validated_processes`, the actual served cost confidence for supported and unsupported processes, and persistence after restart. This validates the product's import/recalibration behavior; its automatic split is separate from the locked commercial evaluation above.
8. Broader manufacturability claims require independent manufacturing-engineer labels and actual part/process outcomes: record expected feature dimensions and tolerances, agreed process feasibility/blockers, then compare findings on those exact parts. Supplier price agreement does not establish DFM accuracy or suitability across unrepresented materials/processes.

## Executed checks

Read-only runtime used: `/Users/nazeem/.codex/worktrees/5c24/cadverify/backend/.venv/bin/python`; source and writable outputs remained in this checkout. Tests used procedural fixtures, mocked services, or temporary directories. No shared database/runtime was modified.

```bash
cd /Users/nazeem/.codex/worktrees/1dfc/cadverify/backend
PYTHONDONTWRITEBYTECODE=1 /Users/nazeem/.codex/worktrees/5c24/cadverify/backend/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_costing_groundtruth.py tests/test_w5_plumbing.py \
  tests/test_calibration_store.py tests/test_supplier_holdout_gate.py \
  tests/test_groundtruth_import.py tests/test_groundtruth_numeric_boundary.py \
  tests/test_costing_calibration.py tests/test_costing_accuracy.py \
  tests/test_source_artifact_service.py
```

Result after the independent-review fixes: **127 passed, 1 skipped**. The skip is the optional real-Postgres import round trip because this focused invocation did not configure a database; it is not a production-acceptance pass. The root rollout lane runs the broader suite against its own isolated Postgres/Redis.

Fresh harness run: `python -m src.costing.harness --output ../outputs/rollout-readiness-20260930/accuracy-regression.md` — **12 coupons, 200 comparisons, all five regression criteria pass; production supplier holdout BLOCKED**.

Protected gate invocation with the actual local environment: `python -S scripts/ci/validate_supplier_holdout.py` — **exit 1**, required protected supplier evidence absent. This is the expected fail-closed result, not a new commercial validation.

## Inputs still required

- Accessible, retained real CAD and an independently approved quote/invoice set meeting the **holdout** part/supplier/family counts, plus a separate tuning set.
- Provenance/permission and supplier identity records; retained quote artifacts; scope normalization; actual supplier rate profiles where calibration is claimed.
- Independent manufacturing labels/outcomes for broader manufacturability claims.
- Reviewer-approved result and provenance hashes bound to the final release, configured through the protected evidence mechanism.

No live accuracy claim, supplier price validation, or production release is asserted by this report.
