/**
 * The ask-the-engine dock's logic — the ONLY code that turns a typed/clicked ask
 * into an answer. Honesty is the whole point of this module:
 *
 *   • A STRUCTURED ask that maps to a real engine call may return numbers. Two
 *     shapes are recognised: "compare routes [at qty N]" and "should-cost at qty
 *     N" read the REAL, in-hand CostReport (POST /validate/cost output the shell
 *     already fetched); "compare saved decisions" makes a LIVE call to
 *     GET /api/v1/cost-decisions/compare over two persisted decisions.
 *   • EVERYTHING ELSE is uncomputable. Free-form natural language has NO engine
 *     backend, so it is refused — never answered with an invented number. That
 *     input mode is IN DEVELOPMENT (see the dock's disclosure).
 *
 * No value here is fabricated: every figure is SELECTED from a real engine
 * response, or the ask is refused. There are no design fixtures (no hardcoded
 * shops, rates, or part costs).
 */
import type { CostReport, CostComparison } from "@/lib/api";
import { compareCostDecisions, fetchCostDecisions } from "@/lib/api";
import { nearestQty, makeNowEstimate, toolingEstimate } from "./derive";
import { normProv, type Prov } from "./tokens";

export type AskKind =
  | "compare_routes"
  | "compare_saved"
  | "cost_at_qty"
  | "uncomputable";

export interface ParsedAsk {
  kind: AskKind;
  /** the quantity the ask names, if any (null → the caller picks a default). */
  qty: number | null;
  raw: string;
}

/** Pull a quantity out of free text: "1,000", "1000", "1k", "10 k", "qty 500".
 *  Prefers a qty-context number ("at 1000", "qty 500", "@1k", "500 units"); else
 *  falls back to the largest bare number (quantities dominate these asks). */
export function parseQty(text: string): number | null {
  const coerce = (raw: string): number | null => {
    const m = raw.trim().toLowerCase().match(/^([\d,.]+)\s*(k)?$/);
    if (!m) return null;
    const base = Number(m[1].replace(/,/g, ""));
    if (!Number.isFinite(base)) return null;
    return Math.round(m[2] ? base * 1000 : base);
  };

  const ctx =
    text.match(/(?:qty|quantity|volume|of|@|at|per)\s*([\d,.]+\s*k?)/i) ||
    text.match(/([\d,.]+\s*k?)\s*(?:units|unit|pcs|pieces|parts|off)/i);
  if (ctx) {
    const q = coerce(ctx[1]);
    if (q != null && q > 0) return q;
  }

  // fallback: the largest standalone number-with-optional-k token
  const all = [...text.matchAll(/([\d,.]+\s*k?)/gi)]
    .map((m) => coerce(m[1]))
    .filter((n): n is number => n != null && n > 0);
  if (all.length === 0) return null;
  return Math.max(...all);
}

/** Classify an ask. Only the two structured shapes are answerable; the default
 *  is refusal, which is the honest stance for anything the engine can't compute. */
export function parseAsk(text: string): ParsedAsk {
  const raw = text.trim();
  const t = raw.toLowerCase();
  const qty = parseQty(raw);

  const isCompare = /\bcompare\b/.test(t) || /\bvs\.?\b|\bversus\b/.test(t);
  const wantsSaved = /\b(saved|record|records|decision|decisions|last|previous|prior|earlier|other|history|calibration|shop|shops)\b/.test(
    t
  );
  const isCost = /\b(cost|price|priced|should-?cost|how much|unit cost|per[- ]unit)\b/.test(t) || /\$/.test(t);

  if (isCompare) {
    if (wantsSaved) return { kind: "compare_saved", qty, raw };
    if (/\broute|routes|process|processes\b/.test(t) || qty != null)
      return { kind: "compare_routes", qty, raw };
    return { kind: "compare_routes", qty, raw };
  }
  if (isCost && (qty != null || /\bat\b|\bqty\b/.test(t))) {
    return { kind: "cost_at_qty", qty, raw };
  }
  return { kind: "uncomputable", qty, raw };
}

/* ── structured answers over the in-hand cost report (real engine output) ─── */

export interface RouteReadout {
  process: string;
  unit: number | null;
}

export interface CostAtQtyResult {
  requestedQty: number | null;
  snappedQty: number;
  makeNow: RouteReadout | null;
  tooling: RouteReadout | null;
  crossover: number | null;
  filename: string;
}

/** Read the should-cost at a quantity straight off the engine's estimates. */
export function computeCostAtQty(cost: CostReport, qty: number | null): CostAtQtyResult {
  const snapped = nearestQty(cost.quantities, qty ?? 1000);
  const make = makeNowEstimate(cost, snapped);
  const tool = toolingEstimate(cost, snapped);
  return {
    requestedQty: qty,
    snappedQty: snapped,
    makeNow: make ? { process: make.process, unit: make.unit_cost_usd } : null,
    tooling: tool ? { process: tool.process, unit: tool.unit_cost_usd } : null,
    crossover: cost.decision?.crossover_qty ?? null,
    filename: cost.filename,
  };
}

export interface DriverDelta {
  name: string;
  a: number;
  b: number;
  provenance: Prov;
}

export type RouteCompareResult =
  | { status: "single"; snappedQty: number; filename: string }
  | {
      status: "ok";
      requestedQty: number | null;
      snappedQty: number;
      a: { process: string; unit: number };
      b: { process: string; unit: number };
      deltaPct: number | null;
      divergent: DriverDelta | null;
      filename: string;
    };

/** Compare two REAL routes at a quantity: the make-now route vs the tooling
 *  route (or, absent a tooling route, the next-cheapest costed process). The
 *  "divergent driver" is the single cost driver whose value differs most between
 *  the two routes — read verbatim from the engine's drivers, with its provenance.
 *  Never fabricates a route: fewer than two costed processes → status "single". */
export function compareRoutesAtQty(cost: CostReport, qty: number | null): RouteCompareResult {
  const snapped = nearestQty(cost.quantities, qty ?? 1000);
  const make = makeNowEstimate(cost, snapped);
  if (!make) return { status: "single", snappedQty: snapped, filename: cost.filename };

  // B = the tooling route if the engine named one, else the cheapest OTHER process
  // costed at this quantity. Both are real estimates off the report.
  let bEst = toolingEstimate(cost, snapped);
  if (!bEst || bEst.process === make.process) {
    const others = cost.estimates
      .filter((e) => e.quantity === snapped && e.process !== make.process)
      .sort((x, y) => x.unit_cost_usd - y.unit_cost_usd);
    bEst = others[0] ?? null;
  }
  if (!bEst) return { status: "single", snappedQty: snapped, filename: cost.filename };

  const deltaPct =
    make.unit_cost_usd > 0
      ? Math.round(((bEst.unit_cost_usd - make.unit_cost_usd) / make.unit_cost_usd) * 1000) / 10
      : null;

  // the driver with the largest absolute delta between the two routes
  let divergent: DriverDelta | null = null;
  const bByName = new Map(bEst.drivers.map((d) => [d.name, d]));
  let best = -1;
  for (const da of make.drivers) {
    const db = bByName.get(da.name);
    if (!db) continue;
    const diff = Math.abs(db.value - da.value);
    if (diff > best) {
      best = diff;
      divergent = { name: da.name, a: da.value, b: db.value, provenance: normProv(da.provenance) };
    }
  }

  return {
    status: "ok",
    requestedQty: qty,
    snappedQty: snapped,
    a: { process: make.process, unit: make.unit_cost_usd },
    b: { process: bEst.process, unit: bEst.unit_cost_usd },
    deltaPct,
    divergent,
    filename: cost.filename,
  };
}

/* ── the LIVE compare over two persisted decisions ─────────────────────────── */

export type SavedCompareResult =
  | { status: "not_saved" }
  | { status: "need_second" }
  | { status: "error"; message: string }
  | { status: "ok"; comparison: CostComparison; otherId: string };

/** Ask GET /api/v1/cost-decisions/compare to diff THIS part's saved decision
 *  against the org's most-recent OTHER saved decision. Honest at every fork: no
 *  saved id → "not_saved"; no second decision on record → "need_second"; a failed
 *  call → its error. Only a real diff is ever rendered. */
export async function compareSaved(currentSavedId: string | null): Promise<SavedCompareResult> {
  if (!currentSavedId) return { status: "not_saved" };
  try {
    const page = await fetchCostDecisions({ limit: 12 });
    const other = page.cost_decisions.find((d) => d.id !== currentSavedId);
    if (!other) return { status: "need_second" };
    const comparison = await compareCostDecisions(currentSavedId, other.id);
    return { status: "ok", comparison, otherId: other.id };
  } catch (e) {
    return { status: "error", message: e instanceof Error ? e.message : "compare request failed" };
  }
}

/** The honest refusal copy for a free-form / uncomputable ask. States plainly
 *  that no engine backs free text yet and lists what the engine CAN compute. */
export const NL_REFUSAL =
  "Free-form questions have no engine backend yet — that input mode is IN DEVELOPMENT, and the engine never invents an answer. It can compute: envelope fit · surviving materials · process physics · hours · resource cost · route & saved-decision crossovers. Try “compare routes at qty 1,000” or “should-cost at qty 500”.";

/** The design's uncomputable-ask example (supplier pressure) — a non-deterministic
 *  question the engine correctly refuses rather than fabricate. */
export const NONDETERMINISTIC_REFUSAL =
  "Supplier pricing pressure isn’t a deterministic property of geometry, machines, or rates — so no number is offered, and none is invented. The engine computes what it can measure or derive: envelope fit, surviving materials, process physics, hours, resource cost, and crossovers.";
