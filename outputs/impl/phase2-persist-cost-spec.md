# Phase 2 spec — Persist + export/share/compare the should-cost decision

**Finding (product audit gap #3, routes.py "nothing is persisted"):** the flagship should-cost / make-vs-buy decision is computed in-memory and thrown away — it can't be saved, PDF-exported, shared, versioned, or compared. The product's headline deliverable leaves no artifact a buyer can keep. PDF export is DFM-only; there is no cost report.

**DoD:** the cost decision becomes a durable, exportable, shareable, comparable artifact. Corrected behavior on the demo path; WIP flagged; tests; adversarial verify; merge to prod.

## The object to persist
`report_to_dict(report)` (backend/src/costing/report.py:15) → dict:
`{ filename, status, reason, geometry, material_class, quantities, estimates[], engine_feasibility, routing, notes, assumptions[{name,value,unit,provenance,source}], decision{make_now_process, make_now_material, tooling_process, crossover_qty, recommendation, if_redesigned, note} }`.
This is the full glass-box artifact (drivers, provenance, CI, crossover, assumptions) — persist it verbatim as JSONB.

## Patterns to MIRROR (do not reinvent)
- Persistence: `Analysis` model (db/models.py:100) — user_id, mesh_hash, `result_json` JSONB, dedup UniqueConstraint, `share_short_id` with partial unique index, created_at index. 7 clean Alembic migrations at head 0007.
- PDF: `src/api/pdf.py` + `src/services/pdf_service.py` + `templates/pdf/analysis_report.html` (WeasyPrint+Jinja, file-cached, semaphore-bounded) — DFM-only today; add a cost template.
- Share: `src/api/share.py` + `src/services/share_service.py` + public `GET /s/{short_id}` (sanitized, noindex).
- History: `src/api/history.py` (cursor pagination).
- Frontend affordances wired only to `/analyses/[id]`: `PdfDownloadButton`, `ShareButton`, `ShareModal`; cost surface (`LivingInstrument`) has none.

## Decomposition (2 coordinated builders; backend first, verify, then frontend)

### Builder 4A — Backend platform (feature branch `feat/cost-persist`)
1. **Migration + `CostDecision` model** mirroring `Analysis`: `user_id`, `mesh_hash`, `result_json` (JSONB = report_to_dict output), `make_now_process`, `crossover_qty`, `quantities`, optional `label`, `share_short_id` (partial unique index), created_at index, a sensible dedup key (user_id + mesh_hash + params hash). New Alembic migration `0008_*` (real Postgres types; test it upgrades/downgrades).
2. **Persist on cost**: `POST /api/v1/validate/cost` saves the decision for authed users and returns `{id, url}`. Keep `/validate/cost/demo` IP-local/ephemeral (honest to its docstring) OR save-behind-flag. Feature flag `COST_PERSIST_ENABLED` (default ON for the authed route).
3. **List/detail**: `GET /api/v1/cost-decisions` (cursor pagination, filter by process/date) + `GET /{id}` (owner-scoped, 404-not-403).
4. **Export**: cost PDF `GET /{id}/pdf` — NEW `templates/pdf/cost_report.html` rendering geometry, routing, per-process estimates with **line items + provenance tags**, **confidence band (honest "not yet validated")**, **make-vs-buy crossover**, and the **assumptions log**. Plus `GET /{id}/export.json` and `GET /{id}/export.csv` (estimates/line-items table).
5. **Share**: `POST/DELETE /{id}/share` + public `GET /s/cost/{short_id}` (sanitized payload, noindex) — mirror share_service.
6. **Compare**: `GET /api/v1/cost-decisions/compare?ids=a,b` → structured diff (unit cost by qty, make/tooling process, crossover, key driver deltas).
7. Tests: model/migration, save+dedup, list/detail ownership, PDF renders (non-empty, has cost+crossover+assumptions sections), JSON/CSV, share round-trip + sanitization, compare. Full suite green.

### Builder 4B — Frontend (after 4A verified; branch `feat/cost-persist-ui` off updated dev)
1. Save / Export (PDF, JSON, CSV) / Share affordances on the cost surface (`LivingInstrument` cost mode) — reuse `PdfDownloadButton`/`ShareButton`/`ShareModal`.
2. Cost history (list saved decisions) + detail view.
3. Public cost share page (mirror `app/s/[shortId]/page.tsx`).
4. Minimal compare view (pick 2 saved decisions → side-by-side). NONSTANDARD Next.js — read `frontend/node_modules/next/dist/docs/` before touching pages.
5. Tests (unit for any pure logic) + `tsc`/`next build` green.

## Honesty guardrails (the #1 rule)
- The persisted/exported artifact MUST carry the same honesty as the live decision: provenance tags, and the confidence band labeled "assumption-based, not yet validated" (never "validated"). The PDF must not present the ±band as measured. Don't let persistence launder an unvalidated number into something that looks certified.
- No lying stub: every advertised export/share must actually work end-to-end, or not be shown.

## Verify (adversarial)
End-to-end: cost a part → it persists → reload/list shows it → PDF downloads with cost+crossover+assumptions+honest CI → JSON/CSV export → share link opens sanitized public view → compare two decisions. Full suite green. prod stays demo-ready.
