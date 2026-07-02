/**
 * cost-decision — PURE helpers for the persisted should-cost artifact (no React).
 *
 * Two honesty-critical concerns live here:
 *
 *  1. STRING-KEYED QUANTITIES. The live `POST /validate/cost` decision and the
 *     PERSISTED `result_json.decision` both key `recommendation` / `if_redesigned`
 *     by quantity, but a JSONB round-trip turns the int keys into STRINGS
 *     ("50","5000"). The scrubber and charts speak in numbers. These readers
 *     normalize both directions so a saved decision re-renders identically to a
 *     live one — never a missing figure because "50" !== 50.
 *
 *  2. COMPARE-DIFF FORMATTING. The compare endpoint returns raw `delta_usd` /
 *     `delta_pct`; this formats them into signed, human strings and decides which
 *     side is cheaper, without inventing a number when one side has no estimate.
 *
 * Tested by cost-decision.test.ts on the repo's `node --test` runner.
 */
import type {
  CostDecision,
  CostRecommendation,
  CostRedesigned,
  CostCompareUnitRow,
} from "@/lib/api";

/* ------------------------------------------------------------------ */
/*  Feature flag                                                       */
/* ------------------------------------------------------------------ */

/**
 * `NEXT_PUBLIC_COST_PERSIST_UI` — the save/export/share/compare surface. Default
 * ON (this completes the demo artifact); only an explicit "0"/"false" opts out.
 */
export function costPersistUiEnabled(): boolean {
  const f = process.env.NEXT_PUBLIC_COST_PERSIST_UI;
  return f !== "0" && f !== "false";
}

/* ------------------------------------------------------------------ */
/*  String-keyed quantity readers                                      */
/* ------------------------------------------------------------------ */

/** Look up a quantity-keyed value tolerant of int-vs-string keys (JSONB). */
function lookupByQty<V>(
  map: Record<string, V> | null | undefined,
  qty: number | string
): V | null {
  if (!map) return null;
  const key = String(qty);
  if (Object.prototype.hasOwnProperty.call(map, key)) return map[key] ?? null;
  // Fall back to a numeric-equality scan (handles "50.0" vs "50", padded, etc.)
  const want = Number(qty);
  if (Number.isFinite(want)) {
    for (const k of Object.keys(map)) {
      if (Number(k) === want) return map[k] ?? null;
    }
  }
  return null;
}

/** The recommended process/cost at `qty` (string-key safe). */
export function recommendationForQty(
  decision: Pick<CostDecision, "recommendation"> | null | undefined,
  qty: number | string
): CostRecommendation | null {
  return lookupByQty(decision?.recommendation, qty);
}

/** The "cheaper if redesigned" alternative at `qty`, or null (string-key safe). */
export function redesignedForQty(
  decision: Pick<CostDecision, "if_redesigned"> | null | undefined,
  qty: number | string
): CostRedesigned | null {
  return lookupByQty(decision?.if_redesigned, qty);
}

/** The quantities a decision was costed at, as sorted numbers (keys may be strings). */
export function recommendedQuantities(
  decision: Pick<CostDecision, "recommendation"> | null | undefined
): number[] {
  if (!decision?.recommendation) return [];
  return Object.keys(decision.recommendation)
    .map((k) => Number(k))
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b);
}

/* ------------------------------------------------------------------ */
/*  Compare-diff formatting                                            */
/* ------------------------------------------------------------------ */

export type DeltaDirection = "cheaper" | "pricier" | "flat" | "na";

export interface FormattedDelta {
  /** e.g. "-$3.20 (-12.5%)", "+$1.00 (+4%)", "no change", "—" */
  text: string;
  direction: DeltaDirection;
}

const USD = (n: number) =>
  `$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/**
 * Format a compare delta (B relative to A). Positive delta = B is pricier.
 * Returns "—" when either side lacks an estimate — never a fabricated number.
 */
export function formatUnitCostDelta(
  deltaUsd: number | null | undefined,
  deltaPct: number | null | undefined
): FormattedDelta {
  if (deltaUsd == null) return { text: "—", direction: "na" };
  if (deltaUsd === 0) return { text: "no change", direction: "flat" };
  const sign = deltaUsd > 0 ? "+" : "-";
  const pct = deltaPct != null ? ` (${deltaPct > 0 ? "+" : "-"}${Math.abs(deltaPct)}%)` : "";
  return {
    text: `${sign}${USD(deltaUsd)}${pct}`,
    // B pricier than A => A is the cheaper side; direction reflects B vs A.
    direction: deltaUsd > 0 ? "pricier" : "cheaper",
  };
}

/** Which decision is cheaper for a compare row: "a", "b", "equal", or "na". */
export function cheaperSide(row: CostCompareUnitRow): "a" | "b" | "equal" | "na" {
  const ua = row.a?.unit_cost_usd;
  const ub = row.b?.unit_cost_usd;
  if (ua == null || ub == null) return "na";
  if (Math.abs(ua - ub) < 0.005) return "equal";
  return ua < ub ? "a" : "b";
}
