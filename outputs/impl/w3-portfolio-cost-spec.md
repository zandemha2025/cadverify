# W3 SPEC — Batch-cost job type + Portfolio roll-up API (backend only)

**Written 2026-07-03 by the orchestrator, grounded in a code-scout pass. Builder: follow this literally; document every deviation in your impl note.**

Goal (long-horizon-plan §W3): the batch pipeline is DFM-only today; make it able to COST a portfolio, and expose an org-scoped portfolio roll-up (savings ranking) so the FE portfolio door's honest "coming" savings state can become real. **NO frontend changes in this build** (UI waits for the design world; also avoids the package.json merge gotcha). You may READ `frontend/src` (the catalog/portfolio door components) to align API field names.

## Ground truth from the scout (verified against code 2026-07-03)

- `backend/src/jobs/batch_tasks.py::run_batch_item` (line ~214) calls ONLY `analysis_service.run_analysis`. There is no cost path.
- Batch dispatch is hardcoded to task names `run_batch_coordinator`/`run_batch_item` (batch_router.py ~line 181). The `_JOB_TYPE_TO_TASK` registry in `arq_backend.py` is a SEPARATE generic Job-table queue (sam3d/reconstruction) — **do not touch it; do not conflate the two job systems.**
- `Batch` (models.py ~422) and `BatchItem` (~484) have NO job-type column and NO qty/region/material/shop fields. `BatchItem.analysis_id` FK exists; there is NO `cost_decision_id`.
- Costing single public entrypoint: `estimate_decision(result, mesh, features, options)` — `backend/src/costing/estimate.py:138`; serialize ONLY via `report_to_dict` (`costing/report.py:15`). `CostEstimate.assert_sums()` (provenance.py ~74) enforces Σ(line_items)==unit_cost — never construct estimates outside `cost_breakdown`/`estimate_decision`.
- The live cost route: `POST /validate/cost` → `routes.py::_run_cost_decision` (~line 616) → `_parse_mesh_async` → `EstimateOptions` → **binds W5 org calibration via `resolve_org` + `groundtruth_service.load_served_calibration(org_id)`** → runs engine + `estimate_decision` in an executor under `asyncio.wait_for` → persists via `cost_decision_service.persist_cost_decision` (dedup key `(user_id, mesh_hash, params_hash)`).
- Org scoping: rows carry `org_id`; `BatchItem`/`WebhookDelivery` derive org via `src.auth.org_context.resolve_org_via_batch`; reads filter via `caller_org_subquery(user.user_id)`; foreign org → **404, never 403**.
- Worker: `WorkerSettings.functions` in `jobs/worker.py` (~66), `job_timeout=600` hard ceiling, coordinator is a self-re-enqueueing tick (NOT a loop). Task functions use **local imports inside the function body** (deliberate, import-order at worker startup) — follow this convention.
- Catalog is a runtime fold (NO parts table): `catalog_service.build_catalog(session, org_id)` scans `Analysis` + `CostDecision` capped at `CATALOG_SCAN_CAP=2000` each, folds by `mesh_hash`, carries a `truncated` honesty flag. `make_now_estimate(cost_json)` withholds unit_cost when `dfm_ready==False`.
- Webhooks: `create_webhook_delivery(session, batch_id, event_type, payload)` — payload is free-form JSONB; reusable as-is.
- Migrations: latest `0011_create_ground_truth_records` (style: full descriptive revision id, `SET statement_timeout='5000'` first, org_id-leading composite indexes, downgrade reverses).
- JSONB gotcha: `result_json.decision.recommendation` / `if_redesigned` keys become STRINGS after round-trip — handle accordingly.
- Dedup gotcha: a ZIP with duplicate parts (same mesh, same params) will hit the `(user_id, mesh_hash, params_hash)` unique constraint on second persist — the cost item path must handle this gracefully (reuse the existing decision row; item still completes, pointing at it).

## Deliverables

### D1 — Migration `0012_batch_cost`
- `batches.job_type` Text NOT NULL `server_default='dfm'` (values `'dfm'|'cost'`).
- `batch_items` new nullable columns: `quantities` Text (semicolon-separated ints, e.g. `"1;100;1000"`), `region` Text, `material_class` Text, `shop` Text, `cost_decision_id` BigInteger FK→`cost_decisions.id` `ondelete='SET NULL'` + index.
- Follow the 0011 style exactly; `upgrade`/`downgrade` both clean; existing DFM rows unaffected.

### D2 — Batch create API (`batch_router.py`, `batch_service.py`)
- `POST /batch` gains Form field `job_type: str = "dfm"`; validate ∈ {dfm, cost} else 422 structured.
- Feature flag `BATCH_COST_ENABLED` (per-module `os.getenv`, default ON): when off, `job_type=cost` → 501 structured (mirror the `S3_INPUT_NOT_IMPLEMENTED` pattern). Flag-off must leave every existing behavior byte-identical.
- CSV manifest for cost batches gains optional columns: `quantities` (semicolon-separated ints inside the cell), `region`, `material_class`, `shop`. Invalid values reject at create time with a structured 400 (per-row error message incl. row number). Missing values → engine defaults.
- DFM batches: behavior byte-identical (existing tests must pass untouched).

### D3 — Worker cost path (`batch_tasks.py`)
- Branch inside `run_batch_item` on parent `batch.job_type == "cost"` → new `_run_cost_item(...)` helper (local imports). Coordinator stays untouched.
- Per item: read bytes (zip mode only; s3 stays NotImplemented) → parse mesh via the SAME parse path the cost route uses → build `EstimateOptions`: quantities from item (else mirror `/validate/cost`'s default qty handling EXACTLY — read `_run_cost_decision`'s defaults, do not invent your own), `*_is_user=True` ONLY for manifest-supplied values → **bind org calibration exactly like `_run_cost_decision` does** (parity rule: a batch-costed part must produce the same numbers as the same part through `/validate/cost` with the same params — this is the core honesty invariant of this build) → run engine + `estimate_decision` in an executor bounded by the same timeout mechanism the route uses (well within the 600s worker ceiling) → `report_to_dict` → persist via `cost_decision_service.persist_cost_decision` (user = batch.user_id; handle the dedup conflict by reusing the existing row) → set `item.cost_decision_id`, `item.status`, counters, heartbeat, webhook exactly like the DFM path.
- `report.status=="GEOMETRY_INVALID"` → item `failed` with the structured reason in `error_message` (not a crash, not a fake success).
- Webhook payload for cost items may add `cost_decision_id`, `make_now_process`, and engine-computed cost fields — engine numbers ONLY, copied from `report_to_dict` output.

### D4 — Cost results CSV
- `generate_results_csv` branches on `batch.job_type`. Cost columns: `filename,status,make_now_process,crossover_qty,quantities,unit_cost_usd,validated,cost_decision_url,error`.
- `unit_cost_usd` follows catalog honesty: withheld (empty) when the make-now estimate has `dfm_ready==False`; `validated` copied from the artifact (never computed here).

### D5 — Portfolio roll-up API (`api/catalog.py` + `services/catalog_service.py`)
- `GET /api/v1/catalog/portfolio` — `Role.viewer`, org-scoped via `resolve_org`, rate-limited like the catalog route.
- Implementation: a second derivation pass over `build_catalog(session, org_id)` rows (NO new tables, no SQL GROUP BY). Carry the `truncated` flag through; if truncated, the response must say the roll-up is over a capped scan.
- Response: `summary` {parts, costed, drafted, truncated, excluded_no_cost_count, posture aggregate (MEASURED/SHOP/USER/DEFAULT driver counts across costed parts)} + `rows` ranked by savings descending, each: `part_key`, `filename`, `lifecycle_state`, `make_now_process`, `unit_cost` (same withholding rule as catalog rows), `quantities`, `validated`, `posture`, `savings`.
- **SAVINGS HONESTY (the crux):** `savings` may contain ONLY numbers the engine already computed and persisted in `result_json` — e.g. an `if_redesigned` delta or a make-vs-buy delta at a quoted qty, whichever `decision.py`/`report.py` actually provide (READ them first; ground every field you expose in a specific persisted field). Each savings object must carry `basis` (which engine field it came from) and the qty it applies to. A costed part with no engine-computed savings signal → `savings: null` + `reason` string. NEVER a fabricated %/$/heuristic. Do NOT invent a "portfolio total spend" number — demand quantities are unknown; if you expose any aggregate $ figure it must be Σ of engine-quoted values with an explicit label of exactly what it sums, or be omitted.
- Read the FE portfolio door component(s) to align field NAMES (read-only) — but never add a number the engine didn't compute just because the FE has a slot for it.

### D6 — Tests
- Unit (mock style of `tests/test_batch_tasks.py`): cost-item happy path, GEOMETRY_INVALID → failed item, dedup-conflict reuse, DFM regression (job_type=dfm hits `run_analysis`, never the cost path), flag-off create rejection, manifest parsing (good + malformed rows), cost CSV shape + withholding.
- Pure unit (style of `tests/test_catalog_service.py`): portfolio derivation — ranking order, savings basis extraction, null-savings reason, truncated flag propagation, posture aggregate.
- Live-PG (style of `tests/test_catalog_api.py` / `test_cross_tenant_isolation.py`, raw-SQL seeds, two orgs): portfolio endpoint isolation (foreign org's parts never aggregated; foreign access patterns → 404 where applicable), cost-batch rows org-derived correctly.
- Migration test if the `test_migration_*` pattern covers new migrations.

## Constraints (non-negotiable)
1. NO STUB MASQUERADING AS REAL. No fabricated numbers. `validated` is NEVER set by batch/portfolio code — it flows from `ConfidenceInterval` untouched.
2. Every DEFAULT-provenance driver keeps the literal `[assumption, not shop-validated]` convention — you get this for free by calling `estimate_decision`/`report_to_dict` unmodified; do not post-process driver/source strings.
3. Local-import convention inside arq task functions.
4. 600s worker ceiling respected; per-item compute bounded like the live route.
5. Backward compat: existing DFM batch tests pass untouched; flag-off byte-identical.
6. You do NOT merge or push. Work in your worktree, commit to `feat/w3-portfolio-cost`, leave everything in place, report back.

## Environment / how to build & test
- Main repo: `/Users/nazeem/Desktop/developer/cadverify` (checked out on `dev` — do not touch it).
- Create your worktree: `git -C /Users/nazeem/Desktop/developer/cadverify worktree add /private/tmp/claude-501/-Users-nazeem/6899cc99-6b1c-4537-8bff-73144abaa6dd/scratchpad/wt/w3 -b feat/w3-portfolio-cost dev`
- Symlink gitignored data (else shop-profile tests fail): `ln -sfn /Users/nazeem/Desktop/developer/cadverify/backend/data <worktree>/backend/data`
- Tests: from `<worktree>/backend`, run `/Users/nazeem/Desktop/developer/cadverify/backend/.venv/bin/python -m pytest` (main venv, worktree src). Full suite ~4.5–7.5 min.
- KNOWN env-only failures: 24 tests in `test_costing_gates`/`test_costing_accuracy` fail when `CADVERIFY_PARTS_DIR` is unset (missing STL corpus). NOT regressions; do not chase them; everything else must be green.
- Live-PG tests: follow the docstring command inside `test_cross_tenant_isolation.py` (throwaway database pattern) — do NOT run alembic against the main dev database.
- Local Postgres (`:5432`, role/db `cadverify`) and Redis are up.

## Report back (structured)
Branch head SHA, worktree path, files changed, migration id, test summary (counts incl. the known-24 delta), the exact `result_json` fields your savings extraction reads, FE field names you aligned to, and every deviation from this spec with a one-line why.
