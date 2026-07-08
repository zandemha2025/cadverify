# W1 Step 1 — Org/Team Schema + Backfill (spec)

**Scope:** the tenant data model ONLY. No route changes, no RBAC redesign (steps 2–3). After this merges, every user-scoped row carries `org_id`, unused by behavior — a pure foundation layer.

## Schema (migration 0009, additive)

- `organizations`: `id` (ulid pk) · `name` · `slug` (unique) · `created_at`
- `teams`: `id` · `org_id` (fk) · `name` · `created_at` — created but unused in v1 flows
- `memberships`: `id` · `org_id` (fk) · `user_id` (fk) · `org_role` (`admin|member|viewer`) · unique `(org_id, user_id)`
- `org_id` (fk, indexed) added to ALL TEN user-scoped tables, explicitly: `users` (as `current_org_id`), `api_keys`, `analyses`, `cost_decisions`, `jobs`, `usage_events`, `batches`, `batch_items`, `webhook_deliveries`, `audit_log`. Composite index `(org_id, user_id)` on the hot query tables (`analyses`, `cost_decisions`, `batches`, `jobs`).
- Platform-level `users.role` stays untouched (future superadmin split is step 2).

## Migration discipline

Three-phase within 0009: (1) add nullable columns + new tables → (2) backfill: per existing user create a personal org (`slug = email-local + '-' + short-ulid`), an admin membership, and stamp `org_id` on every one of their rows (batch_items/webhook_deliveries derive via their `batch_id`) → (3) set NOT NULL + FK constraints. Downgrade reverses cleanly (drop constraints → columns → tables). Must pass **up → down → up on real Postgres with seeded multi-user data** — the CI smoke (merged today) will run it; the builder must also prove it locally on a scratch DB with ≥3 users × ≥4 object types seeded.

## Code changes (minimal by design)

- `backend/src/db/models.py`: new models + `org_id` columns.
- New `backend/src/auth/org_context.py`: `resolve_org(user) -> org_id` helper (reads the user's membership; single-org assumption in v1) — created and unit-tested but NOT yet wired into routes (step 3 does the threading).
- Row-creation paths (analysis/cost-decision/batch/key/audit writes) populate `org_id` via the helper so new rows are never null — behavior otherwise identical.

## Verification bars

- Verifier A (data-integrity lens): seeded up/down/up with zero loss; 100% org_id coverage post-backfill; orphan-free FKs; downgrade leaves the pre-0009 schema byte-equivalent.
- Verifier B (no-behavior-change + honesty lens): full suite ≥ 719 passed / 0 failed; API responses byte-identical on the demo path; no query yet filters by org (grep-proven) — this step must not half-implement isolation.

## Explicitly out of scope (steps 2–3, separate branches)

RBAC redesign · route threading (~43 routes) · Catalog API · admin UI · any org switcher UX.
