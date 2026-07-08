# Phase D — triage at scale on the makeability verdict (builder note)

**Branch:** `feat/phase-d-triage-scale` (off `dev` @ c600b09) · worktree
`…/scratchpad/wt/phased` · **no merge/push.**

Extends the materialized `part_summaries` projection (Aramco GAP 2) with the
machine-inventory MAKEABILITY lens so the whole-inventory in-house breakdown and
the "which one machine unlocks the most parts" ranking are SQL aggregates over the
projection — never a per-part engine re-run. Purely additive: absent inventory the
legacy columns/reads are byte-identical and the whole lens reads `unknown`.

## What shipped

**D1 — migration `0023_ps_makeability`** (down_revision `0022_part_context_env`,
`statement_timeout`, org-leading indexes, clean downgrade). Adds to
`part_summaries` (all nullable/defaulted → existing rows need no backfill, legacy
columns byte-identical):
- `makeability_verdict` (the §0 lattice verdict, NULL when costed with no declared
  inventory/env → "not evaluated", never fabricated), `in_house_makeable`
  (bool/NULL), `makeability_bucket` (NOT NULL default `unknown` — the D3 GROUP-BY
  key), `makeability_stale` (NOT NULL default false).
- D4 denormalized keys from the REAL stored FitFailure: `unlock_process`,
  `unlock_gate`, `unlock_single`, `unlock_need_num`, `unlock_need_label`, and
  `makeability_gap` JSONB (the full `{gate,axis,need,have,human}` list for
  drill-down).
- Indexes `ix_part_summaries_org_mkbucket` (org_id, makeability_bucket,
  updated_at DESC, mesh_hash DESC) and `ix_part_summaries_org_unlock` (org_id,
  unlock_process, unlock_gate). Up→down→up round-trip proven on live PG.

**D1 projection derivation** — `part_summary_service.derive_makeability_fields`
(PURE): reads the cost decision's `status` + Phase-C `verification` block
VERBATIM. `makeability_bucket` = `catalog_service.makeability_bucket(verdict,
status)`; a `GEOMETRY_INVALID` status wins (bucket `geometry_invalid`, not
in-house). `_derive_unlock` picks the single primary acquisition from `per_route`:
outsource_only → ACQUIRE the recommended (or first) unowned eligible process;
not_on_owned → UPGRADE the CLOSEST route (fewest distinct binding gates), binding
gate = highest `GATE_PRIORITY`, `single` True only when ONE gate blocks (multi-gate
parts are honestly NOT single-acquisition unlockable).

**D2 — projection-hook maintenance.**
- *Cost/analysis persist* (existing hooks): `refresh_part_summary` now also
  recomputes the makeability columns. The COST hook passes
  `mark_makeability_fresh=True` (its verification was just computed against current
  inventory → clears that part's stale flag); analysis/backfill leave the stale
  flag untouched.
- *Machine-inventory changes* → **honest STALE-marking, not full re-verify.** A
  machine add/update/delete or a shop-capability change would change the verdict
  for MANY parts; a full org re-verify per edit is unaffordable (millions of parts
  × re-running the engine). So each mutating machine-inventory route calls
  `mark_org_makeability_stale_safe` in the SAME txn — ONE indexed
  `UPDATE part_summaries SET makeability_stale=true WHERE org_id=:o AND
  makeability_verdict IS NOT NULL AND NOT makeability_stale`. Only verdict-carrying
  rows are marked (a part with no verdict is genuinely `unknown`, not "stale").
  Cleared per-part when the part is re-costed. GETs stay read-only.

**D3 — scaled makeability rollup** (`GET /catalog/makeability`, Role.viewer, rate
limited, resolve_org). SQL GROUP BY `makeability_bucket` over the projection →
the six buckets (`makeable_in_house | makeable_outside | needs_capability |
not_makeable | unknown | geometry_invalid`) + `total`. Carries the honesty flags:
`stale`+`stale_count` (stale rows are COUNTED in the buckets and flagged, never
hidden), `truncated:false` (whole-inventory SQL count), `cold_projection` +
note (read-only fallback flag, mirrors `/triage`), and an `evaluation_note` when
nothing has been evaluated against a declared inventory. `?bucket=` opts into a
keyset drill-down (typed `InvalidCursorError` → 400).

**D4 — capability-investment ranking** (`GET /catalog/capability-investment`,
Role.viewer, rate limited, resolve_org). ONE SQL GROUP BY over
`(unlock_process, unlock_gate)` where `unlock_single` → per-acquisition `count` +
spec inputs (`MAX(need_num)` for envelope/mass/axes, `MIN` for tolerance IT,
`array_agg(DISTINCT label)` for material) + stale aggregation. `rank_acquisitions`
(PURE) sorts by parts_unlocked desc (ties → process, gate). Each entry: the
acquisition (kind/process/label/gate/spec), `parts_unlocked` (+ keyset drill-down
via `?process=&gate=`), `stale`+`stale_parts`, and a `basis` line. Parts blocked
by MULTIPLE constraints are reported in
`summary.blocked_by_multiple_constraints` — never folded into an entry. **No
acquisition dollar figure is shown** (none is available from engine data — the IM
tooling consideration is a per-quote figure, not a machine acquisition price;
omitted rather than fabricated).

## Honesty invariants held
- No fabricated verdict/count/dollar. `unknown`/`not_makeable`/`geometry_invalid`
  are first-class; a NULL verdict stays `unknown`.
- Stale is VISIBLE (count + flag in rollup and ranking) and never silently served
  as fresh; cleared only by a genuine re-cost.
- `validated` untouched; legacy columns + `build_triage_scaled`/`build_catalog_page`
  byte-identical (86 PG-guarded related tests pass unchanged).
- Read-only GETs; keyset cursors use the typed `InvalidCursorError`→400 pattern;
  python 3.9-compatible (`from __future__ import annotations`); no frontend changes.

## Staleness design (the deliberate choice)
Stale-MARKING over refresh. Rationale + mechanics: a machine edit is O(1) SQL
(one indexed org-scoped UPDATE) instead of O(parts × engine). Staleness is surfaced
in `/catalog/makeability` (`stale`, `stale_count`, `stale_note` — the counts
INCLUDE the stale rows) and per-entry in `/catalog/capability-investment`
(`stale`, `stale_parts`, `stale_note`). Lazy refresh: re-costing a part recomputes
its verdict against current inventory and clears its stale flag. A part never
re-costed stays honestly stale (never silently wrong) until the deploy backfill or
a re-cost refreshes it — the spec's explicitly-permitted trade-off.

## Ranking basis (exactly what D4 is computed from)
Only the stored per-part `(unlock_process, unlock_gate, unlock_single,
unlock_need_num, unlock_need_label)` columns + `makeability_gap`, all derived at
projection time from the Phase-C `verification` block's `verdict` + `per_route`
binding `FitFailure`. `parts_unlocked` counts parts whose SINGLE binding
constraint the acquisition closes; the spec aggregates the group's real needs. No
external data, no invented dollars.

## Tests
- PURE: bucket mapping from every §0 verdict value; `derive_makeability_fields`
  incl. geometry-invalid + no-verification `unknown`; unlock derivation
  (single/multi-gate, material categorical, closest-route, outsource recommended
  route); `rank_acquisitions` ties/empty/spec-aggregation/staleness. + migration
  0023 mocked-op smoke (columns/indexes/downgrade/chain).
- LIVE-PG (throwaway DB, alembic upgrade head through 0023): migration-in-chain
  (columns+indexes present); two-org isolation on rollup/drill-down/ranking;
  projection maintenance on machine add/delete via the REAL router (+ re-cost
  clears stale); the D3/D4 GET routes end-to-end (resolve_org isolation + bad
  cursor/bucket → 400).

**Suite:** full no-DB run = 1226 passed / 45 skipped / **24 failed** (exactly the
known `CADVERIFY_PARTS_DIR`-unset corpus set — "string is not a file"; not a
regression). Live-PG Phase-D + related (part_summary, machine_inventory, catalog,
phase C) = 111 passed. Migration up→down→up round-trip proven.

## Files
- `backend/alembic/versions/0023_part_summary_makeability.py` (new)
- `backend/src/db/models.py` (PartSummary columns + indexes)
- `backend/src/services/part_summary_service.py` (derive_makeability_fields,
  _derive_unlock, refresh hooks + mark_makeability_fresh, mark_org_makeability_stale[_safe])
- `backend/src/services/catalog_service.py` (makeability_bucket, rank_acquisitions,
  build_makeability_rollup / _bucket_page / build_capability_investment / _page)
- `backend/src/services/cost_decision_service.py` (cost hook → mark_makeability_fresh=True)
- `backend/src/api/machine_inventory.py` (5 write paths → mark_org_makeability_stale_safe)
- `backend/src/api/catalog.py` (GET /makeability, GET /capability-investment)
- `backend/tests/test_makeability_projection.py`, `backend/tests/test_migration_0023.py` (new)
