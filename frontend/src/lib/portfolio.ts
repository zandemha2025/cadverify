/**
 * portfolio — the PURE aggregation behind the MRO / portfolio-owner door
 * (D5 FE-5, Door C). No React, no DOM, no runtime imports (only erased type
 * imports), so it is unit-testable with `node --test` and shares one
 * implementation with the render layer — the same discipline as `lib/catalog`,
 * `lib/findings`, `lib/dfm-scope`, `lib/cost-views`.
 *
 * The portfolio door is EXCEPTION-FIRST triage (D1 persona 3, "triage precedes
 * conversation at every scale"), not a full grid. It aggregates the parts the
 * user actually has — their REAL saved should-cost decisions — into three
 * exception queues, each computed from a real engine field:
 *
 *   • dfm-required     — the recommended make-now route is DFM-blocked
 *                        (`estimate.dfm_ready === false`): can't be made as
 *                        designed, price withheld. THE most severe exception.
 *   • default-heavy    — a majority of the make-now route's drivers are generic
 *                        DEFAULT guesses (posture.guess / posture.total ≥ 0.5):
 *                        the decision is running on numbers we admit we're
 *                        guessing. "running on guesses."
 *   • crossover-fragile — the engine's make-vs-buy crossover (decision.crossover_qty)
 *                        sits within FRAGILITY_FACTOR× of a costed order quantity,
 *                        so a modest volume change flips make↔tool.
 *
 * A part can fall into MORE THAN ONE queue — that is the honest truth of triage,
 * not a bug. The queues rank worst-first (dfm-required → default-heavy →
 * crossover-fragile): for a portfolio owner, an unmakeable route outranks
 * unreliable numbers, which outrank a volume-sensitive answer.
 *
 * SAVINGS (task item 2) is HONEST-THIN: portfolio-scale rolled-up $ needs annual
 * volumes × per-part deltas — that is W3 portfolio cost, NOT built, and this
 * module invents no portfolio total. What IS real today is PER-PART: when the
 * engine's `if_redesigned` alternative is cheaper than the recommended make,
 * `bestRedesignSaving` reads that verbatim delta (with the engine's own caveat).
 * The savings queue ranks those real per-part deltas and states the portfolio
 * roll-up as coming — never a fabricated aggregate.
 *
 * IMPORTS ARE TYPE-ONLY (erased at runtime) so this module resolves under the
 * repo's `node --test` type-stripping runner exactly like the other pure libs.
 */
import type { CostDecision } from "@/lib/api";
import type { CatalogMetrics } from "@/lib/catalog";

/* ------------------------------------------------------------------ */
/*  Tuning constants (named so a test and the UI legend agree)         */
/* ------------------------------------------------------------------ */

/**
 * A make-now route is "running on guesses" when at least this fraction of its
 * drivers are generic DEFAULT values (no shop rate, no override, not measured).
 * 0.5 = a majority. Deliberately broader than catalog's `assumption` lifecycle
 * (which requires ZERO grounded drivers): a route that is mostly-but-not-purely
 * default is still a decision built on guessed numbers.
 */
export const DEFAULT_HEAVY_THRESHOLD = 0.5;

/**
 * The make-vs-buy crossover is fragile when it sits within this multiple (either
 * direction) of a costed order quantity — a modest volume change flips make↔tool.
 * Same factor the single-part fragility finding uses (lib/findings), so the door
 * and the part hero agree on what "fragile" means. 4× ≈ within two doublings.
 */
export const FRAGILITY_FACTOR = 4;

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

export type ExceptionQueueId =
  | "dfm-required"
  | "default-heavy"
  | "crossover-fragile";

/**
 * The per-part signal the queues are computed from. `metrics` is the SAME
 * `CatalogMetrics` the catalog grid derives (reused verbatim — one derivation,
 * two doors), plus the two crossover inputs the fragility predicate needs, which
 * `CatalogMetrics` doesn't carry.
 */
export interface PartSignal {
  id: string;
  label: string;
  metrics: CatalogMetrics;
  /** the engine's authoritative crossover (decision.crossover_qty), or null */
  crossoverQty: number | null;
  /** the costed order quantities (report.estimates[].quantity), positive only */
  costedQuantities: number[];
}

/** The fragility of a make-vs-buy decision — null when it is NOT fragile. */
export interface CrossoverFragility {
  crossoverQty: number;
  /** the costed quantity nearest (by ratio) to the crossover */
  nearestQty: number;
  /** max(crossover/qty, qty/crossover) — 1 = crossover sits exactly on an order */
  ratio: number;
}

/** One part's exception assessment — which queues it falls into, and why. */
export interface PartExceptions {
  id: string;
  label: string;
  /** the recommended route is DFM-blocked (price withheld) */
  dfmRequired: boolean;
  /** the first DFM blocker on the route (the honest reason), when blocked */
  blockerReason: string | null;
  /** DFM blockers on the make-now route (route-scoped, real) */
  routeBlockerCount: number;
  /** a majority of the make-now route's drivers are generic DEFAULT guesses */
  defaultHeavy: boolean;
  /** guess / total in [0,1] over the make-now route's drivers */
  guessPct: number;
  /** the make-vs-buy crossover is fragile at this volume */
  crossoverFragile: boolean;
  /** fragility detail (crossover + nearest order), when fragile */
  fragility: CrossoverFragility | null;
  /** grounded drivers on the make-now route (MEASURED + SHOP + USER) */
  groundedDrivers: number;
  /** total drivers on the make-now route */
  totalDrivers: number;
  /** in at least one exception queue */
  flagged: boolean;
}

export interface ExceptionQueueDef {
  id: ExceptionQueueId;
  label: string;
  /** the imperative for this queue (the portfolio owner's verb) */
  verb: string;
  /** one-line meaning (subtitle / legend) — the real field it binds to */
  description: string;
  /** severity tone token — matches lib/status Tone strings */
  tone: "fail" | "warn" | "info";
}

/** A computed queue: its definition plus the parts that fall into it. */
export interface ExceptionQueue extends ExceptionQueueDef {
  count: number;
  /** the cohort — ids of the parts in this queue (drill-down target) */
  memberIds: string[];
}

/**
 * The queue definitions, ranked worst-first. This order is load-bearing: the
 * door surfaces the queues top-down, so the most severe exception (unmakeable)
 * leads and the volume-sensitivity note trails.
 */
export const EXCEPTION_QUEUES: ExceptionQueueDef[] = [
  {
    id: "dfm-required",
    label: "DFM-required",
    verb: "Fix the geometry",
    description:
      "The recommended make-now route is DFM-blocked — can't be made as designed, so the price is withheld.",
    tone: "fail",
  },
  {
    id: "default-heavy",
    label: "Running on guesses",
    verb: "Ground the numbers",
    description:
      "Most of the make-now route's drivers are generic default rates — the make-vs-buy call is built on numbers we're guessing.",
    tone: "warn",
  },
  {
    id: "crossover-fragile",
    label: "Crossover-fragile",
    verb: "Confirm the volume",
    description:
      "The make-vs-buy crossover sits close to your order quantity — a modest volume change flips the recommendation.",
    tone: "info",
  },
];

export function queueDefById(id: ExceptionQueueId): ExceptionQueueDef {
  return EXCEPTION_QUEUES.find((q) => q.id === id) ?? EXCEPTION_QUEUES[0];
}

/* ------------------------------------------------------------------ */
/*  Per-part assessment                                                */
/* ------------------------------------------------------------------ */

/**
 * Whether the make-vs-buy crossover is fragile, and the detail if so. PURE over
 * the engine's crossover and the costed quantities — never invents a crossover.
 * Returns null when there is no crossover (no fragility) or no costed quantity.
 */
export function crossoverFragility(
  crossoverQty: number | null | undefined,
  costedQuantities: readonly number[]
): CrossoverFragility | null {
  if (crossoverQty == null || crossoverQty <= 0) return null;
  const qtys = costedQuantities.filter((q) => q > 0);
  if (qtys.length === 0) return null;

  let nearestQty = qtys[0];
  let minRatio = Infinity;
  for (const q of qtys) {
    const ratio = Math.max(crossoverQty / q, q / crossoverQty);
    if (ratio < minRatio) {
      minRatio = ratio;
      nearestQty = q;
    }
  }
  if (minRatio > FRAGILITY_FACTOR) return null;
  return { crossoverQty, nearestQty, ratio: minRatio };
}

/**
 * Assess one part into its exception queues. Every flag binds to a real engine
 * field via the reused `CatalogMetrics`; nothing here fabricates a signal.
 */
export function assessPart(signal: PartSignal): PartExceptions {
  const m = signal.metrics;
  const total = m.posture.total;
  const grounded = m.posture.grounded;
  const guessPct = total > 0 ? m.posture.guess / total : 0;
  const defaultHeavy = total > 0 && guessPct >= DEFAULT_HEAVY_THRESHOLD;
  const fragility = crossoverFragility(signal.crossoverQty, signal.costedQuantities);

  return {
    id: signal.id,
    label: signal.label,
    dfmRequired: m.blocked,
    blockerReason: m.withheldReason,
    routeBlockerCount: m.routeBlockerCount,
    defaultHeavy,
    guessPct,
    crossoverFragile: fragility != null,
    fragility,
    groundedDrivers: grounded,
    totalDrivers: total,
    flagged: m.blocked || defaultHeavy || fragility != null,
  };
}

/** Whether a part belongs to a given exception queue (the cohort predicate). */
export function partInQueue(part: PartExceptions, queue: ExceptionQueueId): boolean {
  switch (queue) {
    case "dfm-required":
      return part.dfmRequired;
    case "default-heavy":
      return part.defaultHeavy;
    case "crossover-fragile":
      return part.crossoverFragile;
    default:
      return false;
  }
}

/* ------------------------------------------------------------------ */
/*  Queue aggregation                                                  */
/* ------------------------------------------------------------------ */

/**
 * Build the three exception queues from the assessed parts — each carries its
 * count and its cohort (member ids), in the ranked worst-first order. Member
 * order follows input order (the hook feeds newest-first), so a queue's cohort
 * reads in the same order the parts were costed.
 */
export function buildExceptionQueues(parts: readonly PartExceptions[]): ExceptionQueue[] {
  return EXCEPTION_QUEUES.map((def) => {
    const memberIds: string[] = [];
    for (const p of parts) {
      if (partInQueue(p, def.id)) memberIds.push(p.id);
    }
    return { ...def, count: memberIds.length, memberIds };
  });
}

/* ------------------------------------------------------------------ */
/*  Portfolio pulse (the KPIs — REAL / derivable numbers only)          */
/* ------------------------------------------------------------------ */

/**
 * The portfolio pulse KPIs. Every number is a real count or a derivable ratio
 * over the parts the user ACTUALLY HAS assessed — never a fabricated
 * portfolio-scale figure (no "2.4M parts"). `scope` is the honest denominator:
 * these are computed across `assessed` costed parts, and the UI says so.
 */
export interface PortfolioPulse {
  /** parts assessed (the honest denominator — what the user has costed) */
  assessed: number;
  /** parts in at least one exception queue */
  flagged: number;
  /** parts in no exception queue */
  clean: number;
  /** per-queue counts (parts may be counted in more than one) */
  dfmRequired: number;
  defaultHeavy: number;
  crossoverFragile: number;
  /** grounded drivers summed across every assessed make-now route */
  groundedDrivers: number;
  /** total drivers summed across every assessed make-now route */
  totalDrivers: number;
  /** grounded / total in [0,1]; 0 when no drivers — the portfolio posture % */
  groundedPct: number;
}

export function portfolioPulse(parts: readonly PartExceptions[]): PortfolioPulse {
  let flagged = 0;
  let dfmRequired = 0;
  let defaultHeavy = 0;
  let crossoverFragile = 0;
  let groundedDrivers = 0;
  let totalDrivers = 0;

  for (const p of parts) {
    if (p.flagged) flagged++;
    if (p.dfmRequired) dfmRequired++;
    if (p.defaultHeavy) defaultHeavy++;
    if (p.crossoverFragile) crossoverFragile++;
    groundedDrivers += p.groundedDrivers;
    totalDrivers += p.totalDrivers;
  }

  const assessed = parts.length;
  return {
    assessed,
    flagged,
    clean: assessed - flagged,
    dfmRequired,
    defaultHeavy,
    crossoverFragile,
    groundedDrivers,
    totalDrivers,
    groundedPct: totalDrivers > 0 ? groundedDrivers / totalDrivers : 0,
  };
}

/* ------------------------------------------------------------------ */
/*  Per-part savings — REAL where the engine offers a cheaper redesign  */
/* ------------------------------------------------------------------ */

/**
 * A real per-part savings signal: the engine's `if_redesigned` alternative is
 * cheaper than the recommended make at a costed quantity. This is NOT a
 * portfolio total — it is one part's "if you redesigned it" delta, read verbatim
 * from `decision.recommendation` and `decision.if_redesigned` (with the engine's
 * own caveat). The portfolio roll-up of these deltas is W3 and deliberately not
 * computed.
 */
export interface RedesignSaving {
  id: string;
  label: string;
  /** the quantity this delta is quoted at */
  qty: number;
  /** the recommended make-now unit cost at `qty` */
  makeNowUsd: number;
  /** the redesigned alternative's unit cost at `qty` */
  redesignedUsd: number;
  /** makeNowUsd - redesignedUsd (> 0 → redesign is cheaper) */
  saveUsd: number;
  /** saveUsd / makeNowUsd in [0,1] */
  savePct: number;
  /** the redesigned alternative's process */
  redesignedProcess: string;
  /** the engine's own caveat on the redesign (rendered verbatim, never softened) */
  caveat: string;
}

/** Numeric quantity keys of a JSONB-round-tripped map, sorted ascending. */
function numericKeys(map: Record<string, unknown> | null | undefined): number[] {
  if (!map) return [];
  return Object.keys(map)
    .map((k) => Number(k))
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b);
}

/** String-key tolerant lookup (JSONB turns int keys into strings). */
function atQty<V>(map: Record<string, V> | null | undefined, qty: number): V | null {
  if (!map) return null;
  const key = String(qty);
  if (Object.prototype.hasOwnProperty.call(map, key)) return map[key] ?? null;
  for (const k of Object.keys(map)) {
    if (Number(k) === qty) return map[k] ?? null;
  }
  return null;
}

/**
 * The best real redesign saving for a decision — the costed quantity at which
 * the `if_redesigned` alternative is cheaper than the recommended make, by the
 * largest fraction. Returns null when there is no cheaper redesign (never a
 * fabricated saving). Prefers the deepest savePct; ties break to the larger qty
 * (the volume where a redesign matters most to a portfolio owner).
 */
export function bestRedesignSaving(
  id: string,
  label: string,
  decision: CostDecision | null | undefined
): RedesignSaving | null {
  if (!decision) return null;
  let best: RedesignSaving | null = null;

  for (const qty of numericKeys(decision.recommendation)) {
    const rec = atQty(decision.recommendation, qty);
    const alt = atQty(decision.if_redesigned, qty);
    if (!rec || !alt) continue;
    const makeNowUsd = rec.unit_cost_usd;
    const redesignedUsd = alt.unit_cost_usd;
    if (
      !Number.isFinite(makeNowUsd) ||
      !Number.isFinite(redesignedUsd) ||
      makeNowUsd <= 0
    ) {
      continue;
    }
    const saveUsd = makeNowUsd - redesignedUsd;
    if (saveUsd <= 0) continue; // redesign not cheaper — no saving to claim
    const savePct = saveUsd / makeNowUsd;

    const candidate: RedesignSaving = {
      id,
      label,
      qty,
      makeNowUsd,
      redesignedUsd,
      saveUsd,
      savePct,
      redesignedProcess: alt.process,
      caveat: alt.caveat,
    };
    if (
      !best ||
      savePct > best.savePct ||
      (savePct === best.savePct && qty > best.qty)
    ) {
      best = candidate;
    }
  }

  return best;
}

/**
 * The portfolio's per-part redesign savings, ranked deepest-first. One row per
 * part that has a real cheaper redesign; parts without one are omitted (not
 * shown as $0). This is a RANKED LIST of real per-part deltas — NOT a summed
 * portfolio total, which stays honestly uncomputed until W3.
 */
export function rankRedesignSavings(
  signals: readonly { id: string; label: string; decision: CostDecision | null }[]
): RedesignSaving[] {
  const out: RedesignSaving[] = [];
  for (const s of signals) {
    const saving = bestRedesignSaving(s.id, s.label, s.decision);
    if (saving) out.push(saving);
  }
  return out.sort((a, b) => b.savePct - a.savePct);
}

/* ------------------------------------------------------------------ */
/*  Small format helpers (pure) — shared by tests and the render layer  */
/* ------------------------------------------------------------------ */

/** A percentage from a [0,1] ratio, rounded, no decimals ("62%"). */
export function formatPct(ratio: number): string {
  if (!Number.isFinite(ratio)) return "—";
  return `${Math.round(ratio * 100)}%`;
}

/** A whole-dollar amount ($1,240) — savings figures speak in round dollars. */
export function formatUsd0(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return `$${Math.round(n).toLocaleString("en-US")}`;
}
