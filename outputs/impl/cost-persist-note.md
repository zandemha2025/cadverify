# Cost-decision persistence — backend impl note (Phase 2 gap #3)

Branch: `feat/cost-persist` (worktree `cadverify-wt-cost`, off `dev`).

## What this closes

Gap #3 (the #1 product hole): the flagship should-cost / make-vs-buy decision
was computed in-memory by `POST /validate/cost` and **thrown away** — it could
not be saved, PDF-exported, shared, versioned, or compared, and the only PDF was
DFM-only. This change turns the decision into a **durable, exportable,
shareable, comparable artifact** while preserving its honesty: the persisted and
exported copies carry the same provenance tags and the same confidence band that
is **always** labeled "assumption-based, not yet validated" — never "validated".
Persistence does not launder an unvalidated number into a certified one.

## 1. Model + migration

- **Model** `CostDecision` — `backend/src/db/models.py` (mirrors `Analysis`
  exactly for type-compat on Postgres JSONB + the SQLite test DB).
  Columns: `id`, `ulid` (public id), `user_id` (FK CASCADE), `api_key_id`
  (FK SET NULL), `mesh_hash`, `params_hash`, `engine_version`, `filename`,
  `file_type`, `result_json` (JSONB = full `report_to_dict(report)` verbatim),
  denormalized `make_now_process` / `crossover_qty` / `quantities` (for
  listing/filtering only), optional `label`, `is_public`, `share_short_id`,
  `created_at`.
  Table args: `ix_cost_decisions_user_created (user_id, created_at)`;
  dedup `UniqueConstraint(user_id, mesh_hash, params_hash)` =
  `uq_cost_decisions_dedup`; partial unique `ix_cost_decisions_share` on
  `share_short_id WHERE share_short_id IS NOT NULL`. `User.cost_decisions`
  relationship added.
- **Migration** `backend/alembic/versions/0008_create_cost_decisions.py`
  (`revision="0008_create_cost_decisions"`, `down_revision="0007"`). Real
  Postgres types (JSONB), the partial share index, and the dedup constraint via
  raw SQL — mirrors migration 0002. `upgrade()` + `downgrade()` both tested.
- `params_hash` = SHA-256 of the canonical cost params
  `{quantities, region, cavities, complexity, material_class, shop, overrides}`
  (`cost_decision_service.compute_params_hash`). Same file + same params = one
  row (dedup).

## 2. Save on cost

- `POST /api/v1/validate/cost` (auth: `require_role(analyst)`, unchanged) now
  takes a DB session and **persists** the decision for the authed user, adding
  `saved: {id, url}` to the returned decision JSON. Only the decision is stored;
  the raw CAD blob is never retained.
- Persist happens in the shared `_run_cost_decision` helper *after* the
  `GEOMETRY_INVALID` guard, so only valid priced decisions are saved. Wrapped in
  try/except: **persistence never breaks the live decision** the buyer sees.
- `POST /api/v1/validate/cost/demo` is **unchanged / ephemeral** — passes no
  user/session, so nothing is persisted (honest to its docstring).
- **Feature flag** `COST_PERSIST_ENABLED` (env, default **ON** for the authed
  route; `cost_decision_service.cost_persist_enabled()`).

## 3. Routes + auth (API contract for the frontend builder)

All `/api/v1/cost-decisions/*` routes are gated by `require_role` (which composes
`require_api_key`). The public share route is intentionally unauthenticated
(mirrors the analysis public share). New file: `backend/src/api/cost_decisions.py`,
mounted in `main.py` at `/api/v1/cost-decisions` (+ public router at `/s`).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/validate/cost` | analyst | cost + persist; returns decision + `saved:{id,url}` |
| GET | `/api/v1/cost-decisions` | viewer | cursor-paginated list |
| GET | `/api/v1/cost-decisions/compare?ids=a,b` | viewer | structured diff of two owned decisions |
| GET | `/api/v1/cost-decisions/{id}` | viewer | full decision envelope (owner-scoped, 404 for others) |
| GET | `/api/v1/cost-decisions/{id}/pdf` | viewer | cost-report PDF download |
| GET | `/api/v1/cost-decisions/{id}/export.json` | viewer | raw `result_json` (attachment) |
| GET | `/api/v1/cost-decisions/{id}/export.csv` | viewer | estimates/line-items CSV |
| POST | `/api/v1/cost-decisions/{id}/share` | analyst | create public share link |
| DELETE | `/api/v1/cost-decisions/{id}/share` | analyst | revoke share |
| GET | `/s/cost/{short_id}` | **public** | sanitized public view (noindex) |

### Request/response shapes

- **Save** — `POST /api/v1/validate/cost` (multipart form, unchanged fields:
  `file`, `qty`, `region`, `cavities`, `complexity`, `material_class`, `shop`,
  `overrides`). Response = the existing glass-box decision dict **plus**:
  ```json
  { "...decision fields...": "...", "saved": { "id": "<ulid>", "url": "/api/v1/cost-decisions/<ulid>" } }
  ```
  (`saved` is absent when `COST_PERSIST_ENABLED=false` or on the demo route.)
- **List** — `GET /cost-decisions?cursor&limit&process&created_after&created_before`
  → `{ "cost_decisions": [ { id, filename, file_type, label, make_now_process,
  crossover_qty, quantities, created_at, is_public, share_url } ], "next_cursor",
  "has_more" }`. Cursor = last `id` (ulid, desc). `process` filters
  `make_now_process`; `created_after/before` are ISO datetimes.
- **Detail** — `GET /cost-decisions/{id}` → `{ id, filename, file_type, label,
  created_at, engine_version, make_now_process, crossover_qty, quantities,
  is_public, share_url, result: <full result_json> }`. Not owned → **404**.
- **export.json** → `application/json` attachment of `result_json`.
- **export.csv** → `text/csv`; columns: `process, material, quantity,
  unit_cost_usd, fixed_cost_usd, variable_cost_usd, est_error_band_pct,
  confidence_low_usd, confidence_high_usd, confidence_label,
  confidence_validated, dfm_ready, line_items`. The `confidence_validated`
  column is `False` for assumption bands (honest).
- **Share** — `POST .../share` → `{ share_url: "/s/cost/<short>", share_short_id }`
  (idempotent). `DELETE .../share` → `{ message }`.
- **Public** — `GET /s/cost/{short_id}` → sanitized `{ filename, file_type,
  label, created_at, make_now_process, crossover_qty, quantities, geometry,
  material_class, routing, estimates, decision, assumptions, engine_feasibility,
  notes, status }`. **Zero owner PII** (no user_id, api_key_id, mesh_hash,
  params_hash, share_short_id, id, ulid, email). Headers `X-Robots-Tag: noindex`,
  `Cache-Control: private, no-store`.
- **Compare** — `GET /cost-decisions/compare?ids=a,b` → `{ a:{summary}, b:{summary},
  unit_cost_by_qty:[{quantity, a, b, delta_usd, delta_pct}],
  diff:{make_now_process:[a,b], tooling_process:[a,b], crossover_qty:[a,b]},
  unit_costs_by_process:{a,b} }`. Exactly two owned ids required (else 400; a
  non-owned/missing id → 404).

## 4. Export — cost PDF

- `backend/src/services/cost_pdf_service.py` mirrors the DFM `pdf_service`:
  WeasyPrint + Jinja2, **file-cached** (`cost-{ulid}.pdf` under `PDF_CACHE_DIR`),
  **semaphore-bounded** (`asyncio.Semaphore(2)`), rendered off the event loop.
- New template `backend/src/templates/pdf/cost_report.html` (self-contained CSS).
  Sections: **Geometry**; **Geometric Routing**; **Per-Process Estimates** with
  **line items** (Σ = unit cost) and **cost drivers + provenance tags**
  (DEFAULT / SHOP / USER / MEASURED); the **confidence band** rendered honestly;
  **Make-vs-Buy Crossover** (make-now, tooling candidate, crossover qty,
  recommendation-by-qty, cheaper-if-redesigned); **Assumptions Log**; Notes.
- **The honest CI label (critical):** a fixed disclaimer states figures are
  "assumption-based" and confidence bands are **"assumption-based, not yet
  validated"**; each per-estimate band prints `confidence.label` verbatim for
  assumption bands and only shows `MEASURED` when `confidence.validated` is true.
  The footer reads "not a validated quote." The template never emits a
  "VALIDATED" certification for an assumption band (asserted in tests).

## 5. Share

- `cost_decision_service.create_share / revoke_share / get_shared /
  sanitize_for_share` mirror `share_service` (reusing its `generate_short_id`).
  Revocable; public payload is allow-listed and preserves the decision content
  (provenance + honest CI intact) with no owner data.

## 6. Compare

- `cost_decision_service.build_comparison` — owner-scoped structured diff:
  recommended unit cost by quantity (with `delta_usd` / `delta_pct`), make/tooling
  process, crossover qty, and per-process unit-cost maps.

## CI / auth guard

`scripts/ci/check_route_auth.py` only inspects `routes.py`. It was **already
failing on HEAD** for the pre-existing intentionally-public `POST
/validate/cost/demo` (never added to the exemption list). Added it to
`PUBLIC_ROUTES` alongside `/validate/demo` (its authed sibling `/validate/cost`
stays role-gated). Guard now reports `route-auth-coverage OK`. The new
`/api/v1/cost-decisions/*` routes live in their own module and are all
`require_role`-gated; the public `/s/cost/{short_id}` is intentionally exempt
(mirrors `/s/{short_id}`).

## Tests

- `backend/tests/test_migration_0008.py` — revision chain, columns, dedup +
  partial share index, upgrade/downgrade, re-upgrade idempotency.
- `backend/tests/test_cost_persist_api.py` — save returns `{id,url}` + honesty
  preserved; demo stays ephemeral; flag-off; dedup returns existing (no dup
  insert); denormalized columns; list + pagination + auth-required; detail
  owner-ok / wrong-user-404 / nonexistent-404; export.json; export.csv (honest
  columns); PDF endpoint contract (renderer mocked) + PDF **template content is
  honest** (cost + line items + crossover value + assumptions + the honest label,
  and no "VALIDATED" stamp); share create/revoke; public sanitization (no owner
  leak) + 404; compare (service diff + endpoint + 400 on bad ids).

Command: `cd backend && .venv/bin/python -m pytest -q`
New-file result: **27 passed** (`test_migration_0008.py` + `test_cost_persist_api.py`).
Full-suite result: see builder-log / commit message.

## Files changed / added

- `backend/src/db/models.py` (add `CostDecision` + `User.cost_decisions`)
- `backend/alembic/versions/0008_create_cost_decisions.py` (new)
- `backend/src/services/cost_decision_service.py` (new)
- `backend/src/services/cost_pdf_service.py` (new)
- `backend/src/templates/pdf/cost_report.html` (new)
- `backend/src/api/cost_decisions.py` (new)
- `backend/src/api/routes.py` (persist in `_run_cost_decision`; session dep on `validate_cost`)
- `backend/main.py` (mount routers)
- `scripts/ci/check_route_auth.py` (exempt intentionally-public `/validate/cost/demo`)
- `backend/tests/test_migration_0008.py`, `backend/tests/test_cost_persist_api.py` (new)
