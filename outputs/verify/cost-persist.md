# Verify — Item 4A: Persist/export/share/compare cost decision (BACKEND) — product audit gap #3

**Verdict: CLOSED + PRODUCTION-WORTHY → MERGED to dev** (prod ff deferred until frontend 4B completes the artifact).
Branch `feat/cost-persist` (builder commit d38190f). Both adversarial verifiers high-confidence PASS, validated on **real Postgres**.

## The finding (closed)
The should-cost / make-vs-buy decision was computed in-memory and thrown away — couldn't be saved, PDF-exported, shared, versioned, or compared. Now it is a durable, exportable, shareable, comparable artifact.

## Evidence (real Postgres, not mocks)
- **e2e verifier (high conf):** migration 0008 applied to real Postgres (full 0001→0008 chain clean). Full lifecycle via TestClient + real DB session: `POST /validate/cost` → 200 with `saved:{id,url}` + real row in Postgres; list; detail; `export.json`; `export.csv` (18 rows); a 2nd decision + `compare?ids=a,b` → structured diff (`make_now_process ['mjf','cnc_turning']`, `crossover_qty [4658,None]`); share round-trip (noindex, revoke→404); dedup returns same id. Demo endpoint persists NOTHING; `COST_PERSIST_ENABLED=0` disables persist but still returns the decision.
- **HONESTY holds on every persisted/exported surface:** `confidence.validated=false`, label "assumption-based, not yet validated", PDF footer "not a validated quote", CSV `confidence_validated=False` on all rows, public share `validated=false`. **No "VALIDATED" stamp anywhere**; provenance tags (DEFAULT/MEASURED) preserved. Persistence does not launder an unvalidated number into a certified one.
- **security verifier (high conf, 44/44 checks on real Postgres):** public `/s/cost/{short_id}` leaks NO PII (allow-list sanitizer, no user_id/email/mesh_hash/ids), `X-Robots-Tag: noindex` + `Cache-Control: private,no-store`, revocable→404. Owner-scoping: user B → **404** on all of A's endpoints (never 403/200); list user-scoped. Input validation: `compare` bad ids → 400/404/422, never 500. Migration up/down/re-up clean; JSONB round-trip handles the string-key `decision.recommendation`. Route-auth CI guard passes; `/validate/cost/demo` legitimately public (kill-switch only); `/validate/cost` role-gated (analyst).
- **Full-suite gate:** 594 passed / 7 skipped / 0 failed (orchestrator run). (A verifier saw 1 intermittent `test_auth_dashboard_session` flake — pre-existing, env-dependent, non-reproducing; also seen by the item-3 verifier; not from this change.)

## Non-blocking notes (tracked)
1. `/{id}/pdf` binary render needs WeasyPrint system libs (absent locally, present in the Docker image that already ships the DFM PDF). Same stack as the working DFM PDF — not a stub. **Follow-up:** a real-PDF smoke test in the Docker image.
2. Persist wrapped in a bare `except` (graceful degradation so a save failure never breaks the live decision) — a persistence regression would be invisible except for the absent `saved` key. **Follow-up:** a soft-warning field / metric.
3. Cosmetic: model `__table_args__` index decl omits DESC that migration 0008 uses (real DB built from migration — correct; create_all unused, JSONB doesn't compile on SQLite anyway).

## Next
Frontend builder 4B (save/export/share on the cost surface + cost history + public cost share page + compare view) builds against this API contract (in outputs/impl/cost-persist-note.md), then the complete Phase-2 artifact ff's to prod.

Merged: feat/cost-persist → dev.
