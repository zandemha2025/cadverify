/**
 * cost-views — PURE derivations the role-aware workspace lenses share (no React).
 *
 * The cost-truth engine returns one `report_to_dict` per upload; the Decision /
 * Glass Box / Compare / Routing lenses are each a view onto it. These helpers pick
 * the right estimate for a (process, qty), build the compare board off the real
 * estimates, and split the calibration provenance — so every lens binds to the
 * SAME real numbers, never an invented figure.
 */
import type {
  CostReport,
  CostEstimate,
  CostAssumption,
  CostDriver,
  ValidationResult,
} from "@/lib/api";
import type { CalibrationRate, CompareRow } from "@/components/glass-box";
import { procLabel, verdictLabel, verdictTone } from "./status.ts";
import { crossoverSummary } from "./cost-decision.ts";
import { routeScopedDfmVerdict } from "./dfm-scope.ts";
import { routeDfmOutcome } from "./verify/derive.ts";
import { deriveBreakeven, posToQty, qtyToPos, recommendAt } from "./breakeven.ts";

/** Header and copied-summary verdict for the workspace's make-now route.
 * A declared cost report with no route cannot borrow an unrelated geometry pass. */
export function workspaceDfmSummary(
  report: CostReport | null,
  validation: ValidationResult | null,
  selection?: Pick<CostEstimate, "process" | "material" | "quantity"> | null,
) {
  const process = selection !== undefined ? selection?.process ?? null : report
    ? report.decision?.make_now_process ?? report.routing?.recommended_process ?? null
    : validation?.best_process ?? null;
  const material = selection?.material ?? report?.decision?.make_now_material;
  let estimates = report?.estimates.filter((e) => e.process === process && !e.environment_excluded
    && (!material || e.material === material)) ?? [];
  const exact = estimates.filter((e) => e.quantity === selection?.quantity);
  if (exact.length) estimates = exact;
  let verdict = routeScopedDfmVerdict(validation, process);
  for (const estimate of estimates) verdict = routeDfmOutcome(verdict, estimate).verdict;
  if (report && estimates.length === 0 && verdict === "pass") verdict = "unknown";
  if (report?.status === "GEOMETRY_INVALID") verdict = "fail";
  return { process, verdict } as const;
}

/** One selection for the quantity slider, headers, routing and evidence views. */
export function workspaceSelection(report: CostReport | null, validation: ValidationResult | null, position?: number) {
  const breakeven = report ? deriveBreakeven(report) : null;
  const pos = position ?? (breakeven
    ? qtyToPos(breakeven, breakeven.crossoverQty ?? Math.max(...(report?.quantities.length ? report.quantities : [1])))
    : 1);
  const quantity = breakeven ? posToQty(breakeven, pos) : null;
  const recommendation = breakeven && quantity != null ? recommendAt(breakeven, quantity) : null;
  const estimate = report && recommendation && quantity != null
    ? pickEstimate(report, recommendation.curve.process, quantity, recommendation.curve.material) : null;
  const dfm = workspaceDfmSummary(report, validation, breakeven
    ? recommendation && quantity != null ? { ...recommendation.curve, quantity } : null
    : undefined);
  return { breakeven, position: pos, quantity, recommendation, estimate, dfm } as const;
}

/* ------------------------------------------------------------------ */
/*  Override mapping (F3) — translate a glass-box edit into the engine's */
/*  dotted override key so the cost API actually re-costs. These mirror  */
/*  the CLI's --set surface (src/costing/rates.py::_apply_override).      */
/* ------------------------------------------------------------------ */

/** Flat global rate keys an assumption edit maps to 1:1 (name === key). */
const RATE_ASSUMPTION_KEYS = new Set([
  "labor_rate",
  "margin",
  "overhead",
  "utilization",
  "stock_allowance",
  "daily_machine_hours",
]);

/**
 * The engine override key for an editable assumption, or null if it isn't a
 * numeric rate (n_cavities routes to the cavities option; complexity /
 * material_class / region_* are set elsewhere, not via the rate card).
 */
export function assumptionOverrideKey(name: string): string | null {
  return RATE_ASSUMPTION_KEYS.has(name) ? name : null;
}

/** Can this assumption be edited into a real re-cost? (rate key, or cavities) */
export function canOverrideAssumption(name: string): boolean {
  return assumptionOverrideKey(name) !== null || name === "n_cavities";
}

/** Bounds for both visible rate editors; the server validates the final card too. */
export function costOverrideError(name: string, raw: string): string | null {
  const value = Number(raw);
  if (!raw.trim() || !Number.isFinite(value)) return "Enter a finite number.";
  if (value < 0) return "Enter zero or a positive number.";
  if (name === "utilization" && (value <= 0 || value > 1)) return "Utilization must be greater than 0 and at most 1.";
  if (name === "stock_allowance" && value < 1) return "Stock allowance must be at least 1.";
  if (name === "daily_machine_hours" && (value <= 0 || value > 24)) return "Machine hours must be greater than 0 and at most 24 per day.";
  if (name === "n_cavities" && (!Number.isSafeInteger(value) || value < 1)) return "Cavities must be a positive whole number.";
  return null;
}

/**
 * The engine override key a cost-driver row edits — the underlying RATE that
 * drives it (so the edit is honest: you set the rate, the driver re-costs):
 *   machine_cost  → machine_rate.<PROCESS>   ($/hr, per-process)
 *   labor_cost / setup_cost → labor_rate     ($/hr, global)
 *   material_cost → material_price.@<class>   ($/kg, per material class)
 */
export function driverOverrideKey(
  driverName: string,
  process: string,
  materialClass: string
): string | null {
  switch (driverName) {
    case "machine_cost":
      return `machine_rate.${process.toUpperCase()}`;
    case "labor_cost":
    case "setup_cost":
      return "labor_rate";
    case "material_cost":
      return `material_price.@${materialClass}`;
    default:
      return null;
  }
}

export function canOverrideDriver(driverName: string): boolean {
  return ["machine_cost", "labor_cost", "setup_cost", "material_cost"].includes(
    driverName
  );
}

/** Human label for the rate a driver edit actually sets. */
export function driverRateLabel(driverName: string): string {
  switch (driverName) {
    case "machine_cost":
      return "machine rate";
    case "labor_cost":
    case "setup_cost":
      return "labor rate";
    case "material_cost":
      return "material price";
    default:
      return "rate";
  }
}

/** Unit suffix for the rate a driver edit sets ($/hr vs $/kg). */
export function driverRateUnit(driverName: string): string {
  return driverName === "material_cost" ? "$/kg" : "$/hr";
}

/**
 * Pre-fill value for a driver's rate editor — the rate is printed verbatim in
 * the engine's own source string ("× $30/hr", "× $7/kg"), so we read it back
 * rather than invent one. Returns null if it can't be parsed (editor opens blank).
 */
export function parseDriverRate(driver: CostDriver): number | null {
  const unit = driver.name === "material_cost" ? "kg" : "hr";
  const re = new RegExp(`\\$([0-9]+(?:\\.[0-9]+)?)\\s*/\\s*${unit}`);
  const m = driver.source?.match(re);
  return m ? parseFloat(m[1]) : null;
}

/** Distinct eligible costed processes, in first-seen order. */
export function costedProcesses(report: CostReport): string[] {
  const seen: string[] = [];
  for (const e of report.estimates) {
    if (e.environment_excluded) continue;
    if (!seen.includes(e.process)) seen.push(e.process);
  }
  return seen;
}

/** The costed quantities (sorted ascending). */
export function costedQuantities(report: CostReport): number[] {
  return [...new Set(report.estimates.filter((e) => !e.environment_excluded).map((e) => e.quantity))].sort(
    (a, b) => a - b
  );
}

/**
 * The estimate for `process` at the costed quantity nearest `qty` (the glass box
 * is per-(process, qty); the slider qty is continuous, so we snap to the nearest
 * costed point rather than invent a figure between them).
 */
export function pickEstimate(
  report: CostReport,
  process: string,
  qty?: number,
  material?: string,
): CostEstimate | null {
  const forProc = report.estimates.filter((e) => e.process === process && !e.environment_excluded
    && (material == null || e.material === material));
  if (forProc.length === 0) return null;
  if (qty == null) return forProc[0];
  return forProc.reduce((best, e) =>
    Math.abs(e.quantity - qty) < Math.abs(best.quantity - qty) ? e : best
  );
}

/** Half-width % for an estimate (prefer the confidence band, else the error band). */
export function estimateHalfWidth(e: CostEstimate): number {
  return Math.round(e.confidence?.half_width_pct ?? e.est_error_band_pct ?? 0);
}

/** Format an assumption value the way the engine speaks it ($52/hr, 0.8, 1.1×). */
export function fmtAssumptionValue(
  a: Pick<CostAssumption, "value" | "unit">
): string {
  if (a.unit === "$/hr") return `$${a.value}/hr`;
  if (a.unit === "$") return `$${a.value}`;
  if (a.unit === "×") return `${a.value}×`;
  if (!a.unit || a.unit === "frac") return String(a.value);
  return `${a.value} ${a.unit}`;
}

export interface CalibrationView {
  /** null → not calibrated (every rate is a generic DEFAULT) */
  shopName: string | null;
  source?: string;
  note?: string;
  shopRates: CalibrationRate[];
  defaultRates: CalibrationRate[];
}

/**
 * Read the per-shop calibration straight off the report's assumptions + notes.
 * When the API hasn't bound a shop yet (the current build-gap state) every rate
 * is DEFAULT and `shopName` is null — the bar honestly reads "not calibrated."
 */
export function parseCalibration(report: CostReport): CalibrationView {
  const note = (report.notes ?? []).find((n) =>
    /calibrated to shop/i.test(n)
  );
  let shopName: string | null = null;
  let source: string | undefined;
  if (note) {
    const nameMatch = note.match(/calibrated to shop ['"]([^'"]+)['"]/i);
    if (nameMatch) shopName = nameMatch[1];
    const srcMatch = note.match(/Source:\s*(.+?)\s*$/i);
    if (srcMatch) source = srcMatch[1].replace(/\.\s*$/, "");
  }

  const toRate = (a: CostAssumption): CalibrationRate => ({
    name: a.name,
    display: fmtAssumptionValue(a),
  });

  const shopRates = (report.assumptions ?? [])
    .filter((a) => a.provenance === "SHOP")
    .map(toRate);
  const defaultRates = (report.assumptions ?? [])
    .filter((a) => a.provenance === "DEFAULT")
    .map(toRate);

  // If no shop note but some rates are SHOP-tagged, still treat as calibrated.
  if (!shopName && shopRates.length > 0) shopName = "your shop profile";

  return { shopName, source, note: note?.trim(), shopRates, defaultRates };
}

/**
 * The compare board off the real estimates: one row per process, the two costed
 * quantities as columns (the volume price-break — the make-vs-buy crossover made
 * tabular). Every cell is a banded real number; nothing fake-exact.
 *
 * (Shop-A-vs-shop-B in one board needs multi-shop-in-one-call — a build gap; the
 * engine supports a shop per call, so this composes from real per-call reports.)
 */
export function buildCompareRows(
  report: CostReport,
  qtyA: number,
  qtyB: number
): CompareRow[] {
  const rows: CompareRow[] = [];
  for (const process of costedProcesses(report)) {
    const a = pickEstimate(report, process, qtyA);
    const b = pickEstimate(report, process, qtyB);
    if (!a || !b) continue;
    rows.push({
      process,
      a: {
        unitCost: a.unit_cost_usd,
        halfWidthPct: estimateHalfWidth(a),
        dfmReady: a.dfm_ready,
        redesign: !a.dfm_ready,
      },
      b: {
        unitCost: b.unit_cost_usd,
        halfWidthPct: estimateHalfWidth(b),
        dfmReady: b.dfm_ready,
        redesign: !b.dfm_ready,
      },
    });
  }
  // cheapest-at-high-volume first — the sourcing reading order
  return rows.sort((x, y) => x.b.unitCost - y.b.unitCost);
}

/** First blocker for every process, with estimate fallback for older reports. */
export function blockersByProcess(report: CostReport): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of report.estimates) {
    if (e.dfm_blockers && e.dfm_blockers.length > 0) {
      out[e.process] = e.dfm_blockers[0];
    }
  }
  for (const f of report.engine_feasibility) {
    if (f.blockers?.length) out[f.process] = f.blockers[0];
  }
  return out;
}

/** The copied decision uses the same selection in both workspace layouts. */
export function buildAnswerSummary(
  report: CostReport | null,
  validation: ValidationResult | null,
  selection: ReturnType<typeof workspaceSelection>,
): string {
  const lines: string[] = [];
  if (report?.decision) {
    const dec = report.decision;
    lines.push(`ProofShape — ${report.filename}`);
    const pick = selection.recommendation;
    lines.push(pick ? `Make by ${procLabel(pick.curve.process)} / ${pick.curve.material} at quantity ${selection.quantity}` : "Manufacturing recommendation unavailable");
    if (pick && selection.estimate?.quantity !== selection.quantity) {
      lines.push("Approximate recommendation at this quantity; re-cost it to include batch rounding and minimum charges.");
    }
    for (const q of report.quantities) {
      const r = dec.recommendation[String(q)];
      if (r) {
        lines.push(
          `  qty ${q.toLocaleString()}: ${procLabel(r.process)} — $${r.unit_cost_usd.toFixed(2)}/unit${
            r.lead_low_days != null && r.lead_high_days != null
              ? `, ${r.lead_low_days}-${r.lead_high_days} days`
              : ""
          }`
        );
      }
    }
    lines.push(crossoverSummary(dec));
  }
  if (validation || report) {
    const dfm = selection.dfm;
    lines.push(
      `DFM${dfm.process ? ` · ${procLabel(dfm.process)}` : ""}: ${verdictLabel(dfm.verdict)} (${verdictTone(dfm.verdict)})`
    );
  }
  return lines.join("\n");
}
