/**
 * findings — the DERIVED trust findings the Inspection column surfaces alongside
 * the geometry-pinned DFM issues. PURE (no React, no DOM, no runtime imports) so
 * it is unit-testable with `node --test` and shares one implementation with the
 * render layer.
 *
 * D1 truth #2 ("everything has a source"): the engine already pins every DFM
 * issue to a face and every dollar to a driver. These three classes read the
 * SAME real `report_to_dict` and name, in plain language, the caveats a careful
 * engineer would otherwise have to hunt for — each still bound to a real field:
 *
 *   • provenance-caveat — a cost driver on the recommended route whose value is a
 *     generic DEFAULT (provenance === "DEFAULT"): "we're guessing this number."
 *   • confidence-caveat — the recommended estimate's confidence band is not yet
 *     validated (`confidence.validated === false`): a should-cost, not a quote.
 *   • fragility        — the make-vs-buy crossover (from lib/breakeven) sits
 *     within FRAGILITY_FACTOR× of a costed order quantity, so a modest volume
 *     change flips make↔tool: the decision is on a knife-edge.
 *
 * Nothing here invents a number: provenance/confidence are read verbatim off the
 * engine fields; fragility only compares the engine's own crossover to the costed
 * quantities. If a field is absent (e.g. the confidence band is still a backend
 * build-gap), the corresponding finding is simply not emitted — never faked.
 *
 * IMPORTS ARE TYPE-ONLY (erased at runtime) so this module resolves under the
 * repo's `node --test` type-stripping runner exactly like the other pure libs.
 * The crossover comes IN as a `Breakeven` (the lib/breakeven output type); the
 * caller derives it with `deriveBreakeven(report)` and passes it here.
 */
import type { CostReport, CostDriver, CostEstimate } from "@/lib/api";
import type { Breakeven } from "@/lib/breakeven";

export type FindingClass =
  | "provenance-caveat"
  | "confidence-caveat"
  | "fragility";

/**
 * Derived findings carry an Issue-shaped `severity` string so they flow through
 * the SAME `lib/status` severity→tone/label helpers and `StatusBadge` the DFM
 * issues use — one severity vocabulary across the Inspection column.
 */
export type FindingSeverity = "warning" | "info";

export interface DerivedFinding {
  /** stable React key + selection id (never collides with a DFM issue key) */
  key: string;
  cls: FindingClass;
  severity: FindingSeverity;
  /** short headline for the card */
  title: string;
  /** one line of plain-language detail */
  detail: string;
  /** the exact engine field(s) this binds to — the honesty audit trail */
  source: string;
}

/**
 * A crossover this close (in either direction) to a costed order quantity means
 * a modest volume change flips the make-vs-buy answer. 4× ≈ within two doublings.
 */
export const FRAGILITY_FACTOR = 4;

/* ------------------------------------------------------------------ */
/*  Small helpers (self-contained — no lib imports)                    */
/* ------------------------------------------------------------------ */

/** Human label for a cost-driver name (machine_cost → "Machine cost"). */
function humanizeDriver(name: string): string {
  const known: Record<string, string> = {
    machine_cost: "Machine rate",
    labor_cost: "Labor rate",
    setup_cost: "Setup cost",
    material_cost: "Material price",
    cycle_time: "Cycle time",
    finishing_cost: "Finishing",
    tooling_cost: "Tooling",
  };
  if (known[name]) return known[name];
  return name
    .split("_")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/** The estimates for a process, or every estimate when process is empty/absent. */
function estimatesFor(
  report: CostReport,
  process: string | null | undefined
): CostEstimate[] {
  const p = (process ?? "").trim();
  if (!p) return report.estimates;
  const scoped = report.estimates.filter((e) => e.process === p);
  return scoped.length ? scoped : report.estimates;
}

/** The costed order quantities, positive only, ascending. */
function costedQuantities(report: CostReport): number[] {
  return Array.from(new Set(report.estimates.map((e) => e.quantity)))
    .filter((q) => q > 0)
    .sort((a, b) => a - b);
}

/* ------------------------------------------------------------------ */
/*  1 — provenance caveats (DEFAULT drivers on the recommended route)  */
/* ------------------------------------------------------------------ */

/**
 * The DEFAULT-provenance drivers on the recommended route, deduped by driver
 * name (first source string wins). Each is a "we don't know YOUR number here"
 * caveat — the hollow-marker guess made explicit as a finding.
 */
export function provenanceCaveats(report: CostReport): DerivedFinding[] {
  const rec = report.decision?.make_now_process;
  const ests = estimatesFor(report, rec);
  const seen = new Map<string, CostDriver>();
  for (const e of ests) {
    for (const d of e.drivers ?? []) {
      if (d.provenance === "DEFAULT" && !seen.has(d.name)) {
        seen.set(d.name, d);
      }
    }
  }
  return Array.from(seen.values()).map((d) => ({
    key: `prov:${d.name}`,
    cls: "provenance-caveat" as const,
    severity: "info" as const,
    title: `${humanizeDriver(d.name)} is a generic default`,
    // the verbose engine derivation lives in the glass box; here we state the
    // consequence plainly. `source` keeps the exact field for the honesty audit.
    detail:
      "No calibrated value for your shop yet — a generic fallback rate. Bind your shop or override it in the glass box to ground it.",
    source: `estimate.drivers[${d.name}].provenance = DEFAULT`,
  }));
}

/* ------------------------------------------------------------------ */
/*  2 — confidence caveat (recommended estimate not yet validated)     */
/* ------------------------------------------------------------------ */

/** The recommended estimate that carries a confidence band (prefer larger qty). */
function recommendedConfidenceEstimate(report: CostReport): CostEstimate | null {
  const rec = report.decision?.make_now_process;
  const ests = estimatesFor(report, rec).filter((e) => e.confidence);
  if (!ests.length) return null;
  return ests.reduce((best, e) => (e.quantity > best.quantity ? e : best));
}

/**
 * The recommended cost is an assumption band, not a validated quote — emitted
 * only when the engine actually surfaces a confidence band AND it is not yet
 * validated. When the band is absent (backend build-gap) NOTHING is emitted;
 * when it is validated the caveat disappears. The wording is the engine's own
 * `label`, never a fabricated ±X%.
 */
export function confidenceCaveat(report: CostReport): DerivedFinding | null {
  const est = recommendedConfidenceEstimate(report);
  const c = est?.confidence;
  if (!c || c.validated) return null;
  const pct = Math.round(c.half_width_pct);
  return {
    key: "confidence",
    cls: "confidence-caveat",
    severity: "info",
    title: c.label || "Assumption-based cost, not yet validated",
    detail: `A should-cost within ±${pct}% — an assumption band, not a validated quote.`,
    source: "estimate.confidence.validated = false",
  };
}

/* ------------------------------------------------------------------ */
/*  3 — fragility (crossover within FRAGILITY_FACTOR× of a costed qty)  */
/* ------------------------------------------------------------------ */

/**
 * The make-vs-buy decision is fragile when the engine's crossover quantity sits
 * within FRAGILITY_FACTOR× (either direction) of a costed order quantity — a
 * modest volume change would flip make↔tool. The crossover comes from
 * lib/breakeven (`deriveBreakeven(report).crossoverQty`), passed in by the
 * caller so this module stays pure/testable.
 */
export function fragilityFinding(
  report: CostReport,
  breakeven: Breakeven | null
): DerivedFinding | null {
  const crossover = breakeven?.crossoverQty ?? null;
  if (crossover == null || crossover <= 0) return null;
  const qtys = costedQuantities(report);
  if (!qtys.length) return null;

  // the costed quantity whose ratio to the crossover is tightest
  let nearestQty = qtys[0];
  let minRatio = Infinity;
  for (const q of qtys) {
    const ratio = Math.max(crossover / q, q / crossover);
    if (ratio < minRatio) {
      minRatio = ratio;
      nearestQty = q;
    }
  }
  if (minRatio > FRAGILITY_FACTOR) return null;

  const xN = Math.round(crossover).toLocaleString();
  const qN = nearestQty.toLocaleString();
  const tool = breakeven?.toolingProcess;
  return {
    key: "fragility",
    cls: "fragility",
    severity: "warning",
    title: "Make-vs-buy decision is fragile at this volume",
    detail: `Crossover ≈ ${xN} units sits within ${FRAGILITY_FACTOR}× of your ${qN}-unit order — a modest volume change flips the recommendation${
      tool ? " toward tooling" : ""
    }.`,
    source: "decision.crossover_qty (lib/breakeven) vs costed quantities",
  };
}

/* ------------------------------------------------------------------ */
/*  Aggregate                                                          */
/* ------------------------------------------------------------------ */

/**
 * All three derived-finding classes for a report, in importance order
 * (fragility → confidence → provenance). Callers that also render DFM issues
 * re-sort the merged set by severity tone; within a tone this order is stable.
 */
export function deriveFindings(
  report: CostReport,
  breakeven: Breakeven | null
): DerivedFinding[] {
  const out: DerivedFinding[] = [];
  const frag = fragilityFinding(report, breakeven);
  if (frag) out.push(frag);
  const conf = confidenceCaveat(report);
  if (conf) out.push(conf);
  out.push(...provenanceCaveats(report));
  return out;
}
