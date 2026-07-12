/**
 * Unit tests for the portfolio PATCH path (program-api.ts) — Wave-B W6-1.
 *
 * The Programs view used to refetch the WHOLE portfolio (a rate-limited read)
 * after every assign / setVolume / unassign, driving itself into a 1-hour 429
 * lockout during heavy triage. The fix patches in-memory state from the write's
 * `portfolio_delta` instead. These tests pin the load-bearing invariant:
 *
 *   applyPortfolioDelta(stalePortfolio, mesh, delta) yields the SAME displayed
 *   figures a full `GET /portfolio` refetch would — the rollup NEVER drifts from
 *   the engine. (The delta is the backend's own build_portfolio output, so the
 *   test derives the delta from a "refetched" portfolio and asserts equality.)
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyPortfolioDelta,
  declaredPrograms,
  rowsInProgram,
  type Portfolio,
  type PortfolioRow,
  type PortfolioDelta,
} from "./program-rollup.ts";

function row(over: Partial<PortfolioRow> = {}): PortfolioRow {
  return {
    part_key: "mA",
    filename: "a.stl",
    lifecycle_state: "Costed",
    make_now_process: "cnc_3axis",
    unit_cost: { usd: 230, qty: 1000, currency: "USD", withheld: false, withheld_reason: null, validated: false },
    quantities: [1000],
    validated: false,
    crossover_qty: null,
    savings: null,
    ...over,
  };
}

/** The delta the backend PUT returns = the slice of a full (re)build_portfolio. */
function deltaFromRefetch(refetched: Portfolio, mesh: string): PortfolioDelta {
  return {
    row: refetched.rows.find((r) => r.part_key === mesh) ?? null,
    programs: refetched.summary.programs ?? [],
  };
}

function exposureOf(p: Portfolio, program: string): number | null {
  const rows = rowsInProgram(p, program).filter((r) => r.annualized_cost_usd != null);
  if (!rows.length) return null;
  return rows.reduce((s, r) => s + (r.annualized_cost_usd ?? 0), 0);
}

const summary = (programs: Portfolio["summary"]["programs"]): Portfolio["summary"] => ({
  parts: 2, costed: 2, drafted: 0, excluded_no_cost_count: 0, truncated: false, posture: {}, programs,
});

test("patched exposure equals a full refetch after a volume edit (230000)", () => {
  const mesh = "mA";
  // Stale client state: pA @ 1000 units → $230,000/yr; pB assigned, no volume yet.
  const stale: Portfolio = {
    summary: summary([{ program: "Actuator", parts: 2, annualized_cost_usd: 230000, annualized_savings_usd: null }]),
    rows: [
      row({ part_key: mesh, context: { program: "Actuator", parent_assembly: null, units_per_parent: null, annual_volume: 1000, provenance: "user" }, annualized_cost_usd: 230000 }),
      row({ part_key: "mB", filename: "b.stl", unit_cost: { usd: 100, qty: 500, currency: "USD", withheld: false, withheld_reason: null, validated: false }, context: { program: "Actuator", parent_assembly: null, units_per_parent: null, annual_volume: null, provenance: "user" }, annualized_cost_usd: null }),
    ],
  };

  // What a FULL refetch would show after declaring pB @ 654.68... units — use an
  // integer volume so the number is exact: pB 100 × 654 = 65,400 → program 295,400.
  const refetched: Portfolio = {
    summary: summary([{ program: "Actuator", parts: 2, annualized_cost_usd: 295400, annualized_savings_usd: null }]),
    rows: [
      stale.rows[0],
      row({ part_key: "mB", filename: "b.stl", unit_cost: { usd: 100, qty: 500, currency: "USD", withheld: false, withheld_reason: null, validated: false }, context: { program: "Actuator", parent_assembly: null, units_per_parent: null, annual_volume: 654, provenance: "user" }, annualized_cost_usd: 65400 }),
    ],
  };

  const patched = applyPortfolioDelta(stale, "mB", deltaFromRefetch(refetched, "mB"));

  // Same program rollup (the index card figure) …
  assert.deepEqual(declaredPrograms(patched), declaredPrograms(refetched));
  // … and the same client-summed exposure (the detail-screen figure).
  assert.equal(exposureOf(patched, "Actuator"), exposureOf(refetched, "Actuator"));
  assert.equal(exposureOf(patched, "Actuator"), 295400);
});

test("patched view equals refetch when unassign empties a program", () => {
  const stale: Portfolio = {
    summary: summary([{ program: "Solo", parts: 1, annualized_cost_usd: 230000, annualized_savings_usd: null }]),
    rows: [
      row({ part_key: "mA", context: { program: "Solo", parent_assembly: null, units_per_parent: null, annual_volume: 1000, provenance: "user" }, annualized_cost_usd: 230000 }),
    ],
  };
  // A refetch after unassigning: the part is still a costed row but carries no
  // program; the "Solo" program vanishes entirely (programs → []).
  const refetched: Portfolio = {
    summary: summary(undefined),
    rows: [row({ part_key: "mA", context: { program: null, parent_assembly: null, units_per_parent: null, annual_volume: 1000, provenance: "user" }, annualized_cost_usd: 230000 })],
  };

  const patched = applyPortfolioDelta(stale, "mA", deltaFromRefetch(refetched, "mA"));

  assert.deepEqual(declaredPrograms(patched), declaredPrograms(refetched)); // both []
  assert.equal(rowsInProgram(patched, "Solo").length, 0);
  assert.equal(patched.rows.length, 1); // the row survives, just unassigned
});
