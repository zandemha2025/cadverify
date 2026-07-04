# Phase C builder note — makeability verification wired into the live cost path

**Branch:** `feat/phase-c-makeability-wire` · **Head:** `ea87f27` · **Base:** `e0bc64d`
**Worktree:** `/private/tmp/claude-501/-Users-nazeem/6899cc99-6b1c-4537-8bff-73144abaa6dd/scratchpad/wt/phasec`
**Status:** DONE — Phase C only. Phase D (triage-at-scale) NOT started.

Rebuilt from `outputs/impl/machine-inventory-verification-spec.md` §2/§7/§10. The
pure engine (`makeability.py` verify_part/fit_machine/environment_gate) and the
data layer (`machine_inventory_service`, `part_context_service`, migrations
0021/0022) were already merged; Phase C is the wiring only.

## What changed (5 files, +292 / −10)

| File | Change |
|---|---|
| `src/costing/estimate.py` | `EstimateOptions` gains `inventory`/`shop_caps`/`service_environment` (all no-op defaults); `DecisionReport` gains `verification` (None default). `estimate_decision` builds the verdict + per-process marginal-rate overrides and threads `machine_override` into both `cost_breakdown` calls. New helpers `_build_verification` / `_serialize_verification` / `_ff_to_dict` / `_jsonable`. |
| `src/costing/cost_model.py` | `cost_breakdown(..., machine_override=None)`. When a fitted owned machine is handed in, its OWN `$/hr` replaces the rate-card default and its OWN `capital_frac` (or card default) drives the marginal seam; the `machine_cost` driver is provenance-tagged and NAMES the machine; `owned_in_house` driver names the machine. `machine_override=None` ⇒ original code path verbatim. |
| `src/costing/report.py` | `report_to_dict` appends `verification` **only** when `report.verification is not None`. Tail-append + truthiness guard = byte-identity when unused. |
| `src/costing/makeability.py` | +5 lines: `verify_part`'s per-route PASSING branch now also carries `resource` (the fitted machine's rate hint) so the cost seam and the verdict read the SAME source of truth. Additive; no existing test asserts per_route dict-equality. |
| `src/api/routes.py` | `_run_cost_decision` resolves the caller org's machines (`load_org_inventory`) + shop caps (`load_shop_caps`) + this part's declared `service_environment` (`get_context` by mesh_hash) and sets them on `options`. Best-effort (a load failure logs a warning and the decision proceeds without the machine lens). |

## Deliverables

- **C1** Inventory in the live path: authed `/validate/cost` computes per-process fit via `verify_part`/`fit_machine`; the report carries a machine-grounded §0 verdict.
- **C2** Machine-specific MARGINAL rate: a passing owned machine that declares a rate re-costs THAT process at its own rate × (1 − capital_frac). Generic path byte-identical when no machine matches (test: `test_estimates_byte_identical_when_no_machine_matches_a_route`).
- **C3** Verdict on the report: `verification` block = `{verdict, best_machine, resource, gap, env_exclusions, per_route{verdict,machines_evaluated,best_machine,failures,machine_rate_usd,...}, inventory_declared, environment_declared, provenance, note}`. Negatives/unknown first-class: `unknown` (no inventory / undeclared capability), `makeable_not_on_owned` (+ concrete quantified gap), `makeable_outsource_only`, `environment_excluded`, `not_makeable`. Env comes from part-context.
- **C4** `/validate/cost` wiring + byte-identity (see proof below).
- **C5** Tests: `tests/test_phase_c_makeability_wire.py` — 14 no-DB (verdict shapes incl. negative/unknown; marginal-rate substitution + provenance; byte-identity regression guard; real-profile sour + over-temp env integration) + 1 live-PG two-org isolation.

## Byte-identity proof (the hard invariant, C4 / §2.1)

`report_to_dict(estimate_decision(...))` for a 40×30×25 steel block with NO
inventory + NO env, serialized `json.dumps(sort_keys=True)`, run in the
pre-Phase-C base worktree (`e0bc64d`) vs the Phase-C tree:

```
base=48088 bytes  phasec=48088 bytes  → BYTE-IDENTICAL (fixed PYTHONHASHSEED=0)
```

**Gotcha found & ruled out:** the served payload's `estimates[]` order is
NON-deterministic across processes (pre-existing — `COSTED_PROCESSES` is a set;
order tracks `PYTHONHASHSEED`). Two runs of the SAME tree reorder the list. This
affects both trees equally and is NOT a Phase-C effect. Pinning `PYTHONHASHSEED=0`
stabilizes ordering and the two trees are byte-for-byte identical. In-process the
regression test `report_to_dict(x) == report_to_dict(x)` holds (same seed) and
asserts `"verification" not in base` — it FAILS the instant the key is made
always-on. (Flagging the ordering non-determinism as a latent output-stability
issue worth a separate fix; out of Phase-C scope.)

## Tests

- No-DB full suite (from worktree `backend`, `env -u DATABASE_URL -u CADVERIFY_PARTS_DIR … pytest -q`): **24 failed / 1201 passed / 38 skipped**, zero collection errors. Baseline was 24/1187/37 → exactly +14 new passing (Phase-C no-DB) and +1 PG skip. The 24 are the known env-only set (`test_costing_gates` 16 + `test_costing_accuracy` 8, need `CADVERIFY_PARTS_DIR`).
- Live-PG (throwaway DB on :5432, `alembic upgrade head` through 0022): `test_phase_c_makeability_wire` + `test_machine_inventory` + `test_part_context*` = **72 passed**; cost-route suite (`test_cost_api`/`test_cost_persist_api`/`test_cost_ensemble_api`/`test_owned_equipment`/…) = **104 passed**. Two-org isolation confirmed: org A's fitting mill → `makeable_in_house` on A-VF2; org B's undersized mill → `makeable_not_on_owned`; neither machine leaks into the other's verdict (via the real org-scoped `load_org_inventory` + real `estimate_decision`).

## Honesty invariants (§2) held

`assert_sums` holds on the machine-rate path (test). `validated`/CI is untouched
(machine rate is a driver provenance, not a measurement — never flips the band).
Every new/changed driver keeps provenance + non-empty source. No fabricated pass:
undeclared capability ⇒ `unknown`, never green. Env exclusions cite the property/
standard (NACE MR0175 / max service temp), read off the loader's real nested
`MaterialProfile.compliance` shape.

## Deliberate decisions / deviations (orchestrator: please confirm)

1. **Machine-rate provenance = SHOP.** A declared per-machine `hourly_rate_usd`
   is the org/shop's real, durable per-machine reality (not a per-quote USER
   override) — the SHOP semantic ("this shop's real machine rate"). The spec C2
   says "SHOP or USER per how it was declared"; I chose SHOP and the source string
   names the machine. USER is a one-line change if preferred. The machine RECORD
   API serialization stays `provenance:"user"` (unchanged); this is the COST-LINE
   provenance only.
2. **Env does not filter the cost shortlist.** The environment gate feeds the
   VERDICT (env_exclusions + `environment_excluded`), but I do NOT drop
   env-excluded processes from the costed `estimates[]`. Rationale: dropping
   estimates would silently move the make-vs-buy crossover; Phase C's deliverable
   is the verdict + marginal rate, not re-shaping the cost shortlist. The
   exclusions are surfaced honestly with citations. Revisit if the spec intends
   hard filtering.
3. **Env-only case** (env declared, no machines): `verify_part` short-circuits to
   `unknown` before the env gate, so I run `environment_gate` directly in the
   wiring to still surface cited exclusions; the top verdict stays honest
   `unknown` (no inventory).

## Known limitations carried forward (surfaced in `verification.note`, not papered over)

- 5-axis/undercut need is inherited from the upstream process router (a part
  routed to `cnc_5axis` needs 5-axis) — NOT re-derived from geometry.
- Force gates (tonnage/taper) require a declared force; absent one, that gate is
  not asserted (no fabricated forming force from geometry).
- `makeable_with_secondary_op` uses the fitted machine's rate but does NOT add a
  secondary-op cost line (grind/HIP $) — out of Phase-C marginal-rate scope.

## Not done (Phase D — next beat)

`part_summaries.in_house_makeable` + projection-hook maintenance + scaled rollup
breakdown + capability-investment ranking. Untouched.
