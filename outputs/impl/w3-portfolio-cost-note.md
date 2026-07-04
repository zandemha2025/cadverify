# W3 builder note — batch-cost job type + portfolio roll-up API (backend only)

Branch `feat/w3-portfolio-cost` (off `dev`), worktree
`/private/tmp/claude-501/-Users-nazeem/6899cc99-6b1c-4537-8bff-73144abaa6dd/scratchpad/wt/w3`.
Head `70dd27e`. No frontend touched. No merge/push.

## What I built (D1–D6)

**D1 — migration `0012_batch_cost`** (`backend/alembic/versions/0012_batch_cost.py`).
`batches.job_type` Text NOT NULL `server_default='dfm'`; `batch_items` gains
`quantities`/`region`/`material_class`/`shop` (Text, nullable) + `cost_decision_id`
BigInteger FK→`cost_decisions.id` `ondelete=SET NULL` and index
`ix_batch_items_cost_decision_id`. 0011 style (SET statement_timeout first,
descriptive revision id, reversible downgrade). Applied clean to a throwaway PG
through head; existing DFM rows unaffected (server_default). Model columns added in
`backend/src/db/models.py`.

**D2 — create API** (`batch_router.py`, `batch_service.py`). `POST /batch` gains
`job_type` Form (default `dfm`; invalid → **422** `INVALID_JOB_TYPE`). Flag
`BATCH_COST_ENABLED` (default ON) → cost batch **501** `BATCH_COST_NOT_ENABLED`
when off (mirrors `S3_INPUT_NOT_IMPLEMENTED`); DFM never gated, flag-off
byte-identical. Cost manifests parse+validate optional `quantities`
(semicolon ints), `region`, `material_class`, `shop` against the same vectors
`/validate/cost` accepts — per-row **400** `INVALID_COST_MANIFEST`. DFM manifest
parsing (`validate_cost=False`) is untouched.

**D3 — worker cost path** (`batch_tasks.py`). `run_batch_item` branches on
`batch.job_type=='cost'` → `_run_cost_item`; coordinator + DFM path unchanged
(DFM body only re-indented under `else:`). `_run_cost_item` (local imports)
reuses the **live route's** `_parse_mesh` + `_run_cost_engine` (via
`_compute_cost_report`) and mirrors `_run_cost_decision`: EstimateOptions,
org-calibration bind, bounded executor (`ANALYSIS_TIMEOUT_SEC`, ≪600s ceiling),
`estimate_decision` → `report_to_dict` → `persist_cost_decision`. Sets
`item.cost_decision_id`/status/counters/heartbeat/webhook exactly like DFM.
`GEOMETRY_INVALID` → item `failed` with `report.reason`, no persist. Dedup
conflict handled by `persist_cost_decision` returning the existing row (item still
completes pointing at it).

**D4 — cost results CSV** (`batch_service.generate_results_csv`). Branches on
`job_type`; cost header
`filename,status,make_now_process,crossover_qty,quantities,unit_cost_usd,validated,cost_decision_url,error`.
`unit_cost_usd` withheld (empty) when the make-now estimate `dfm_ready==False`;
`validated` copied from the estimate's confidence band.

**D5 — portfolio roll-up** (`catalog_service.build_portfolio` + `derive_savings`,
`api/catalog.py::get_portfolio`). `GET /api/v1/catalog/portfolio`, `Role.viewer`,
org-scoped via `resolve_org`, rate-limited like the catalog route. A second
derivation pass over the SAME org fold the catalog uses (extracted
`_fold_org_parts`; no new tables, no GROUP BY). Costed parts → rows ranked by
`save_pct` desc (ties → larger qty); drafted-only parts excluded and counted in
`excluded_no_cost_count`. `truncated` carried through (+ a `note` when true).

**D6 — tests** (all green): `test_portfolio_service` (pure + mock-session),
`test_batch_cost_tasks` (mock worker), `test_batch_cost_manifest` (parse + CSV),
`test_batch_cost_router` (gate), `test_portfolio_api` (live-PG), `test_migration_0012`.

## How to exercise it

Cost batch: `POST /api/v1/batch` multipart with `job_type=cost`, a ZIP of
STL/STEP, and optionally a CSV manifest with columns
`filename,quantities,region,material_class,shop` (e.g. `part.stl,1;100;1000,EU,aluminum`).
Poll `GET /api/v1/batch/{ulid}`, export `GET /api/v1/batch/{ulid}/results/csv`
(cost columns). Each costed item persists a `cost_decision` (dedup on
`(user_id, mesh_hash, params_hash)`) linked via `batch_items.cost_decision_id`.
Portfolio: `GET /api/v1/catalog/portfolio` returns `{summary, rows[]}`.

Live-PG suite (throwaway DB, never the dev DB):
```
createdb -h localhost -U cadverify w3_test
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/w3_test .venv/bin/python -m alembic upgrade head
DATABASE_URL=postgresql://cadverify:localdev@localhost:5432/w3_test .venv/bin/python -m pytest tests/test_portfolio_api.py tests/test_catalog_api.py tests/test_cross_tenant_isolation.py -q
```

## Savings field grounding (the honesty crux)

`derive_savings(cost_result_json)` reads ONLY persisted engine fields from
`report_to_dict` output:
- `result_json["decision"]["recommendation"][q]["unit_cost_usd"]` — tier-1
  make-as-is unit cost at qty `q` (the make-now baseline; the engine's coherence
  invariant pins `make_now_process == recommendation[q_lo].process`).
- `result_json["decision"]["if_redesigned"][q]["unit_cost_usd"]` — tier-2
  cheaper-if-redesigned unit cost at qty `q`.
- `result_json["decision"]["if_redesigned"][q]["process"]` / `["caveat"]` — the
  alternative process + the engine's own caveat (rendered verbatim).
- `result_json["quantities"]` — the row's `quantities`.
- unit_cost / `validated` / posture ride `derive_row` (catalog): `estimates[*]`
  `unit_cost_usd`/`dfm_ready`/`dfm_blockers`/`confidence.validated`/`drivers[*].provenance`.
- row `crossover_qty` = `decision["crossover_qty"]`.

Savings = `round(make_now_usd - redesigned_usd, 2)` (per unit), `save_pct` of the
baseline, at the qty with the deepest pct. Each savings object carries
`basis="decision.if_redesigned"` + `qty`. No cheaper redesign at any qty →
`savings: null` + `reason`. No fabricated %/$; no "portfolio total spend"
(demand qtys unknown) — the only aggregate exposed is the driver-provenance
`posture` (counts). JSONB stringifies int qty keys on round-trip; the
recommendation lookup is string-key tolerant.

## FE field names aligned (read-only, `frontend/src/lib/portfolio.ts`)

Mirrored `RedesignSaving` semantics field-for-field (snake_case for the JSON API):
`qty`, `make_now_unit_usd`↔`makeNowUsd`, `redesigned_unit_usd`↔`redesignedUsd`,
`save_unit_usd`↔`saveUsd`, `save_pct`↔`savePct`, `redesigned_process`↔`redesignedProcess`,
`caveat`. Ranking (deepest `save_pct`, tie→larger qty) matches
`bestRedesignSaving`/`rankRedesignSavings`. Posture keys
(`measured`/`shop`/`user`/`default`/`grounded`/`grounded_pct`) match
`CatalogMetrics.posture` / `PortfolioPulse`. Row `crossover_qty` + `quantities`
supply the FE's `crossoverFragility` inputs.

## Deviations from the spec (with why)

1. **Cost `_is_user` vs the live route's `!= default` proxy.** Per the spec's
   parity rule I set `material_class_is_user = (manifest supplied it)` and
   `region_is_user = (region is not None)`. The route uses `material_class !=
   "polymer"` (it can't distinguish "explicitly polymer" from "defaulted" — Form
   always has a value). Only affects the *provenance tag* in the explicit-default
   edge case (e.g. a manifest cell literally `polymer`), never the numbers, so the
   parity-of-numbers invariant holds. The batch path is strictly more precise here.
2. **Timeout on overrun.** The route raises 504; a batch item that overruns
   `ANALYSIS_TIMEOUT_SEC` is marked `failed` (item-level failure via the outer
   `except`), not a 504 — the honest batch analog of the route's refusal.
3. **`build_portfolio` reuses the fold, not the derived rows.** The spec says
   "second derivation pass over `build_catalog` rows"; those derived rows don't
   carry the raw `decision` needed for savings. I extracted the shared
   `_fold_org_parts` (single org-scoped scan+fold, behaviour-preserving for
   `build_catalog`) and derive portfolio rows from it — same rows, same fold, no
   second DB round-trip, no new tables. Intent honoured.
4. **`job_type` invalid → 422 via explicit check** (not FastAPI enum coercion),
   returning the structured `INVALID_JOB_TYPE` body; `VALID_JOB_TYPES` is imported
   into the router at module load so a test that mocks `batch_service` can't
   accidentally trip the check.

## Test summary

Full backend suite (no `DATABASE_URL`, no `CADVERIFY_PARTS_DIR`):
**24 failed, 796 passed, 16 skipped**. The 24 are exactly the known
`test_costing_gates` (16) + `test_costing_accuracy` (8) `CADVERIFY_PARTS_DIR`
env-only failures (`os.path.join(PARTS_DIR, …)` with `PARTS_DIR` unset) — not
regressions. New W3 unit tests (82 in the batch/catalog/portfolio group) pass.
Live-PG (throwaway DB at head): `test_portfolio_api` + `test_catalog_api` +
`test_cross_tenant_isolation` all pass (3/3). Fixed 4 self-introduced regressions
mid-build (`test_batch_router` ×3 + `test_url_guard` ×1) caused by referencing
`batch_service.VALID_JOB_TYPES` through the mocked module; now import-bound.
