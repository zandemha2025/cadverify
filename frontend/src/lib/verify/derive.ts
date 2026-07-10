/**
 * Pure derivations the verdict walk reads off the real CostReport. No fabrication:
 * every function only SELECTS or FORMATS values the engine already returned, or
 * returns null when the engine did not carry the value. Unit-tested in derive.test.ts.
 */
import type { CostReport, CostEstimate, CostDriver } from "@/lib/api";
import type { Prov } from "./tokens";

/** Normalise the engine's provenance string to a Prov key. Inlined (not imported
 *  at runtime) so this pure module stays free of runtime relative imports and can
 *  run under the repo's `node --test` type-stripping runner. */
function normProv(p: string | null | undefined): Prov {
  const u = String(p ?? "").toUpperCase();
  if (u === "MEASURED" || u === "SHOP" || u === "USER" || u === "CAD" || u === "MODEL")
    return u as Prov;
  return "DEFAULT";
}

/** The make-now route's estimate at a given quantity (drivers/confidence/lead). */
export function makeNowEstimate(
  cost: CostReport,
  qty?: number
): CostEstimate | null {
  const proc = cost.decision?.make_now_process;
  const estimates = cost.estimates.filter((e) => !e.environment_excluded);
  const pool = proc
    ? estimates.filter((e) => e.process === proc)
    : estimates;
  if (pool.length === 0) return null;
  if (qty != null) {
    const exact = pool.find((e) => e.quantity === qty);
    if (exact) return exact;
  }
  // otherwise the largest-quantity estimate (setup fully amortized = the stable read)
  return pool.reduce((a, b) => (b.quantity > a.quantity ? b : a));
}

/** The tooling / acquire route's estimate at a given quantity (may be absent). */
export function toolingEstimate(
  cost: CostReport,
  qty?: number
): CostEstimate | null {
  const proc = cost.decision?.tooling_process;
  if (!proc) return null;
  const pool = cost.estimates.filter(
    (e) => e.process === proc && !e.environment_excluded
  );
  if (pool.length === 0) return null;
  if (qty != null) {
    const exact = pool.find((e) => e.quantity === qty);
    if (exact) return exact;
  }
  return pool.reduce((a, b) => (b.quantity > a.quantity ? b : a));
}

/** qty → unit cost (USD) for a process, from the engine's estimates only. */
export function unitCostByQty(
  cost: CostReport,
  process: string | null | undefined
): Map<number, number> {
  const out = new Map<number, number>();
  if (!process) return out;
  for (const e of cost.estimates) {
    if (e.process === process && !e.environment_excluded) {
      out.set(e.quantity, e.unit_cost_usd);
    }
  }
  return out;
}

/** The computed quantity nearest a target — the scrub snaps to real points. */
export function nearestQty(quantities: number[], target: number): number {
  if (quantities.length === 0) return target;
  return quantities.reduce((best, q) =>
    Math.abs(q - target) < Math.abs(best - target) ? q : best
  );
}

/** Map a 0..1 slider fraction to a log-scaled quantity in [min,max]. */
export function fractionToQty(f: number, min = 1, max = 10000): number {
  const lf = Math.log10(min);
  const lt = Math.log10(max);
  const k = Math.min(1, Math.max(0, f));
  return Math.round(Math.pow(10, lf + (lt - lf) * k));
}

/** Inverse: a quantity's 0..1 position on the log axis (for markers). */
export function qtyToFraction(q: number, min = 1, max = 10000): number {
  const lf = Math.log10(min);
  const lt = Math.log10(max);
  if (lt <= lf) return 0;
  return Math.min(1, Math.max(0, (Math.log10(Math.max(min, q)) - lf) / (lt - lf)));
}

export interface DriverView {
  name: string;
  label: string;
  value: number;
  unit: string;
  provenance: Prov;
  source: string;
  errorBandPct: number | null;
}

const DRIVER_LABELS: Record<string, string> = {
  labor_cost: "Labor",
  setup_cost: "Setup",
  machine_cost: "Machine time",
  material_cost: "Material",
  tooling_cost: "Tooling",
  finishing_cost: "Finishing",
  parts_per_build: "Parts per build",
  labor_rate: "Labor rate",
  machine_rate: "Machine rate",
};

function humanizeDriver(name: string): string {
  return (
    DRIVER_LABELS[name] ??
    name
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

/** Time-unit tokens — a driver denominated in these is HOURS, and hours are MODEL
 *  (computed from a nesting/time assumption), never MEASURED. DESIGN-DECISIONS.md
 *  is binding: "hours are ○ MODEL, only geometry is ● MEASURED". */
const TIME_UNITS = new Set(["hr", "hrs", "hour", "hours", "min", "mins", "minute", "minutes", "s", "sec", "secs", "hr/part", "hr/build"]);

/** Provenance for a driver, refined so an UNGROUNDED time (hours) driver reads
 *  ○ MODEL rather than the generic ○ DEFAULT — matching the binding "hours are
 *  MODEL" rule. It ONLY ever refines the label of an already-hollow (DEFAULT)
 *  provenance for a time-denominated driver; a grounded MEASURED/SHOP/USER value
 *  is NEVER downgraded, and a non-time DEFAULT stays DEFAULT. Never upgrades a
 *  hollow value to a filled/grounded one. */
export function driverProvenance(d: CostDriver): Prov {
  const p = normProv(d.provenance);
  if (p === "DEFAULT" && TIME_UNITS.has(String(d.unit ?? "").toLowerCase().trim())) {
    return "MODEL";
  }
  return p;
}

/** The estimate's drivers, provenance normalized, labelled — verbatim values. */
export function driverViews(est: CostEstimate | null): DriverView[] {
  if (!est) return [];
  return est.drivers.map((d: CostDriver) => ({
    name: d.name,
    label: humanizeDriver(d.name),
    value: d.value,
    unit: d.unit,
    provenance: driverProvenance(d),
    source: d.source,
    errorBandPct: d.error_band_pct,
  }));
}

export interface ProvenanceMix {
  measured: number;
  shop: number;
  user: number;
  default: number;
  model: number;
  total: number;
  groundedPct: number;
}

/** How grounded is this estimate — the real provenance mix over its drivers. */
export function provenanceMix(est: CostEstimate | null): ProvenanceMix {
  const mix: ProvenanceMix = {
    measured: 0,
    shop: 0,
    user: 0,
    default: 0,
    model: 0,
    total: 0,
    groundedPct: 0,
  };
  if (!est) return mix;
  for (const d of est.drivers) {
    const p = normProv(d.provenance);
    if (p === "MEASURED") mix.measured++;
    else if (p === "SHOP") mix.shop++;
    else if (p === "USER") mix.user++;
    else if (p === "MODEL") mix.model++;
    else mix.default++;
    mix.total++;
  }
  const grounded = mix.measured + mix.shop + mix.user;
  mix.groundedPct = mix.total > 0 ? Math.round((grounded / mix.total) * 100) : 0;
  return mix;
}
