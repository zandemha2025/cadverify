/**
 * Crossover scrub interpolation — reads the REAL 6-point quantity ladder the cost
 * engine returned (QTY_LADDER: 1 · 100 · 1,000 · 2,000 · 5,000 · 10,000) and,
 * for any quantity the scrub lands on BETWEEN two computed points, interpolates
 * the unit cost along the amortization curve the two real points bracket.
 *
 * HONESTY: this NEVER fabricates a cost. At a computed point the value is the
 * engine's own number (exact:true). Between two computed points it is an explicit
 * interpolation of two real engine outputs (exact:false) — the caller labels it
 * "interpolated between N and M" so the read is never mistaken for a fresh compute.
 * Amortization (fixed/qty + variable) is ~linear in log-log, so we interpolate in
 * log(qty)×log(unit) space (falling back to linear-in-log(qty) if a bound is ≤ 0),
 * which tracks the real curve far better than a straight line between the points.
 *
 * Pure module (no React, no runtime relative imports beyond the sibling selector)
 * so it runs under the repo's `node --test` type-stripping runner. Tested in
 * scrub.test.ts.
 */
import type { CostReport } from "@/lib/api";

/** qty → unit cost (USD) for a process, from the engine's estimates only. Inlined
 *  (not imported at runtime) so this pure module stays free of runtime relative
 *  imports and runs under the repo's `node --test` type-stripping runner. */
function unitCostByQty(
  cost: CostReport,
  process: string | null | undefined
): Map<number, number> {
  const out = new Map<number, number>();
  if (!process) return out;
  for (const e of cost.estimates) {
    if (e.process === process) out.set(e.quantity, e.unit_cost_usd);
  }
  return out;
}

export interface InterpPoint {
  /** the unit cost at the target qty — engine-exact at a point, interpolated
   *  between two, or null when the process has no computed estimates. */
  unit: number | null;
  /** the lower / upper REAL computed quantities that bracket the target. */
  lo: number;
  hi: number;
  /** true when the target IS a computed point (unit is the engine's own value). */
  exact: boolean;
  /** true when the target sits outside the ladder and was clamped to an end point. */
  clamped: boolean;
}

/**
 * The unit cost for `process` at `qty`, read off the engine's computed ladder.
 * Interpolates (log-log) between the two bracketing real points; clamps to the
 * nearest end point outside the ladder; exact at a computed point.
 */
export function interpUnitCost(
  cost: CostReport,
  process: string | null | undefined,
  qty: number
): InterpPoint {
  const map = unitCostByQty(cost, process);
  const qs = [...map.keys()].sort((a, b) => a - b);
  if (qs.length === 0) return { unit: null, lo: qty, hi: qty, exact: false, clamped: false };

  const exact = map.get(qty);
  if (exact != null) return { unit: exact, lo: qty, hi: qty, exact: true, clamped: false };

  const first = qs[0];
  const last = qs[qs.length - 1];
  if (qty <= first) return { unit: map.get(first) ?? null, lo: first, hi: first, exact: false, clamped: true };
  if (qty >= last) return { unit: map.get(last) ?? null, lo: last, hi: last, exact: false, clamped: true };

  // bracket the target between two adjacent computed points
  let lo = first;
  let hi = last;
  for (let i = 0; i < qs.length - 1; i++) {
    if (qty >= qs[i] && qty <= qs[i + 1]) {
      lo = qs[i];
      hi = qs[i + 1];
      break;
    }
  }
  const cLo = map.get(lo);
  const cHi = map.get(hi);
  if (cLo == null || cHi == null) return { unit: cLo ?? cHi ?? null, lo, hi, exact: false, clamped: false };

  // position of qty along the log(qty) axis between the two points
  const t = (Math.log10(qty) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo));
  let unit: number;
  if (cLo > 0 && cHi > 0) {
    // log-log — tracks the fixed/qty amortization curve between the two real points
    const logc = Math.log10(cLo) + t * (Math.log10(cHi) - Math.log10(cLo));
    unit = Math.pow(10, logc);
  } else {
    // a non-positive bound (degenerate) — straight interpolation in log(qty)
    unit = cLo + t * (cHi - cLo);
  }
  return { unit, lo, hi, exact: false, clamped: false };
}
