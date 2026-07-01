/**
 * Make-vs-buy breakeven derivation — PURE (no React, no DOM).
 *
 * The cost engine returns a discrete `unit_cost_usd` per (process, quantity).
 * For the live quantity slider + breakeven chart we need a continuous
 * cost/unit curve per process. Every manufacturing cost is a fixed (tooling /
 * setup) part amortised over the run plus a per-unit variable part:
 *
 *     unit(q) = fixedAmort / q + variablePerUnit
 *
 * We fit (fixedAmort, variablePerUnit) from the report's OWN reported unit
 * costs (so the curve passes exactly through the numbers shown in the glass-box
 * breakdown — no invented figures). With two costed quantities the fit is exact.
 */
import type { CostReport, CostEstimate } from "@/lib/api";

export interface ProcessCurve {
  process: string;
  material: string;
  /** amortised fixed cost: unit(q) = fixedAmort / q + variablePerUnit */
  fixedAmort: number;
  variablePerUnit: number;
  dfmReady: boolean;
  /** lead-time window (days) from the representative estimate */
  leadLow: number | null;
  leadHigh: number | null;
  /** the actually-costed (qty, unit) points, for reference dots */
  points: { qty: number; unit: number }[];
}

export interface Breakeven {
  curves: ProcessCurve[];
  qtyMin: number;
  qtyMax: number;
  /** authoritative crossover from the engine (make → tool/buy) */
  crossoverQty: number | null;
  makeNowProcess: string;
  toolingProcess: string | null;
}

export interface Recommendation {
  curve: ProcessCurve;
  unitCost: number;
  dfmReady: boolean;
}

/** unit cost of a curve at quantity q. */
export function unitCostAt(c: ProcessCurve, q: number): number {
  if (q <= 0) return Infinity;
  return c.fixedAmort / q + c.variablePerUnit;
}

function fitCurve(ests: CostEstimate[]): {
  fixedAmort: number;
  variablePerUnit: number;
} {
  const pts = ests
    .map((e) => ({ q: e.quantity, u: e.unit_cost_usd }))
    .sort((a, b) => a.q - b.q);

  if (pts.length >= 2) {
    const lo = pts[0];
    const hi = pts[pts.length - 1];
    const denom = 1 / lo.q - 1 / hi.q;
    if (Math.abs(denom) > 1e-12) {
      const a = (lo.u - hi.u) / denom; // fixedAmort
      const b = lo.u - a / lo.q; // variablePerUnit
      if (Number.isFinite(a) && Number.isFinite(b)) {
        return { fixedAmort: Math.max(0, a), variablePerUnit: Math.max(0, b) };
      }
    }
  }

  // Single costed quantity: prefer the engine's own fixed/variable split when
  // it reproduces the reported unit cost, else fall back to a flat line.
  const e = ests[0];
  if (e) {
    const a = e.fixed_cost_usd;
    const b = e.variable_cost_usd;
    if (a != null && b != null) {
      const pred = a / e.quantity + b;
      const tol = Math.max(0.05, e.unit_cost_usd * 0.05);
      if (Math.abs(pred - e.unit_cost_usd) < tol) {
        return { fixedAmort: Math.max(0, a), variablePerUnit: Math.max(0, b) };
      }
    }
    return { fixedAmort: 0, variablePerUnit: e.unit_cost_usd };
  }
  return { fixedAmort: 0, variablePerUnit: 0 };
}

export function deriveBreakeven(report: CostReport): Breakeven | null {
  const dec = report.decision;
  if (!dec) return null;

  const byProc = new Map<string, CostEstimate[]>();
  for (const e of report.estimates) {
    const arr = byProc.get(e.process) ?? [];
    arr.push(e);
    byProc.set(e.process, arr);
  }

  const curves: ProcessCurve[] = [];
  for (const [proc, ests] of byProc) {
    const rep = ests[0];
    const { fixedAmort, variablePerUnit } = fitCurve(ests);
    curves.push({
      process: proc,
      material: rep.material,
      fixedAmort,
      variablePerUnit,
      dfmReady: rep.dfm_ready,
      leadLow: rep.lead_time?.low_days ?? null,
      leadHigh: rep.lead_time?.high_days ?? null,
      points: ests
        .map((e) => ({ qty: e.quantity, unit: e.unit_cost_usd }))
        .sort((a, b) => a.qty - b.qty),
    });
  }

  const qs = report.quantities.length ? report.quantities : [1];
  const qtyMin = 1;
  const maxCosted = Math.max(...qs);
  const crossover = dec.crossover_qty ?? null;
  const qtyMax = Math.ceil(
    Math.max(maxCosted, crossover ? crossover * 2 : 0, 10000)
  );

  return {
    curves,
    qtyMin,
    qtyMax,
    crossoverQty: crossover,
    makeNowProcess: dec.make_now_process,
    toolingProcess: dec.tooling_process,
  };
}

/**
 * Cheapest DFM-ready process at quantity q (the recommendation that "live-flips"
 * as the slider moves). Falls back to the cheapest overall if nothing is
 * DFM-ready as-modeled.
 */
export function recommendAt(b: Breakeven, q: number): Recommendation | null {
  if (!b.curves.length) return null;
  const scored = b.curves
    .map((c) => ({ c, u: unitCostAt(c, q) }))
    .sort((x, y) => x.u - y.u);
  const ready = scored.find((s) => s.c.dfmReady);
  const pick = ready ?? scored[0];
  return { curve: pick.c, unitCost: pick.u, dfmReady: pick.c.dfmReady };
}

/** Log-map a slider position [0,1] to a quantity in [qtyMin, qtyMax]. */
export function posToQty(b: Breakeven, pos: number): number {
  const lo = Math.log(Math.max(1, b.qtyMin));
  const hi = Math.log(b.qtyMax);
  return Math.round(Math.exp(lo + (hi - lo) * pos));
}

/** Inverse of posToQty. */
export function qtyToPos(b: Breakeven, qty: number): number {
  const lo = Math.log(Math.max(1, b.qtyMin));
  const hi = Math.log(b.qtyMax);
  const q = Math.min(b.qtyMax, Math.max(b.qtyMin, qty));
  return (Math.log(q) - lo) / (hi - lo);
}

/** Log-spaced quantity samples for charting the curves. */
export function sampleQuantities(b: Breakeven, n = 48): number[] {
  const lo = Math.log(Math.max(1, b.qtyMin));
  const hi = Math.log(b.qtyMax);
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    out.push(Math.round(Math.exp(lo + ((hi - lo) * i) / (n - 1))));
  }
  return Array.from(new Set(out));
}
