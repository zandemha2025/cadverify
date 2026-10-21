/**
 * Shared link derivations (boards P7 shared cost decision, P9 shared check).
 * Pure: they read the public, sanitized payloads (GET /s/cost/{id}, GET /s/{id})
 * and format them. Anything the sharer's shop declared arrives hidden (value
 * null, source "Set by the sharer's shop…"): it renders as "Hidden", never as a
 * number, and nothing here re-derives it.
 */
import { money, wayName, findingName, SEVERITY } from "./words.ts";

export interface SharedAssumption {
  name: string;
  value: number | null;
  unit: string;
  provenance: string;
  source: string;
}

export interface SharedEstimate {
  process: string;
  material: string;
  quantity: number;
  unit_cost_usd: number;
  dfm_ready: boolean;
  dfm_blockers?: string[];
  environment_excluded?: boolean;
  lead_time?: { low_days?: number; high_days?: number } | null;
  confidence?: { low_usd: number; high_usd: number; half_width_pct: number; validated: boolean } | null;
}

export interface SharedCostLite {
  filename: string;
  label: string | null;
  created_at: string;
  quantities: number[];
  geometry: { bbox_mm?: number[]; volume_cm3?: number; face_count?: number; watertight?: boolean } | null;
  material_class: string | null;
  estimates: SharedEstimate[];
  decision: {
    recommendation?: Record<string, { process: string; material: string; unit_cost_usd: number; dfm_ready?: boolean } | null>;
    crossover_qty?: number | null;
    tooling_process?: string | null;
    tooling_dfm_ready?: boolean;
  } | null;
  assumptions: SharedAssumption[];
}

const NAMES: Record<string, string> = {
  labor_rate: "Labor",
  region_labor: "Region, labor",
  region_material: "Region, material",
  region_tooling: "Region, tooling",
  margin: "Margin",
  overhead: "Overhead",
  utilization: "Machine utilization",
  stock_allowance: "Material size",
  machine_labor_frac: "Operator share of machine rate",
  perishable_frac: "Cutting tools and consumables",
  daily_machine_hours: "Machine hours per day",
  n_cavities: "Mold cavities",
  complexity: "Tooling complexity",
  material_class: "Material class",
  tolerance_class: "Tolerance class",
  source_units: "File units",
  machine_rate: "Machine rate",
  setup_hours: "Setup",
};

export function assumptionName(name: string): string {
  if (NAMES[name]) return NAMES[name];
  const w = name.replace(/_/g, " ").trim();
  return w ? w[0].toUpperCase() + w.slice(1) : name;
}

const UNITS = new Set(["$/hr", "$/h", "×", "x", "frac", "hr/day", "cav", "$", "hr", "%", "mm", "kg", "days", "$/kg"]);

/** The value as a reader sees it. A hidden (null) value is "Hidden"; a categorical one shows its word. */
export function assumptionValue(a: SharedAssumption): string {
  if (a.value == null) return "Hidden";
  const v = a.value;
  if (!UNITS.has(a.unit) && /^[a-z][a-z0-9 _-]*$/i.test(a.unit)) return a.unit.replace(/_/g, " ");
  switch (a.unit) {
    case "$/hr":
    case "$/h":
      return `$${trim(v)}/h`;
    case "$/kg":
      return `$${trim(v)}/kg`;
    case "$":
      return money(v);
    case "×":
    case "x":
      return `×${trim(v)}`;
    case "frac":
      return v === 0 ? "none added" : `${trim(v * 100)}%`;
    case "hr/day":
      return `${trim(v)} h/day`;
    case "hr":
      return `${trim(v)} h`;
    case "cav":
      return trim(v);
    default:
      return `${trim(v)}${a.unit ? ` ${a.unit}` : ""}`;
  }
}

function trim(v: number): string {
  return String(Math.round(v * 100) / 100);
}

export type SourceKind = "file" | "yours" | "typ";

/** Where an input came from, for a reader of someone else's link. */
export function assumptionSource(a: SharedAssumption): { kind: SourceKind; label: string } {
  const p = (a.provenance || "").toUpperCase();
  if (p === "MEASURED" || p === "CAD") return { kind: "file", label: "From the file" };
  if (p === "USER" || p === "SHOP") return { kind: "yours", label: "Sharer's" };
  return { kind: "typ", label: "Typical" };
}

/** Headline prices: the engine's pick at each quoted quantity (four at most). */
export function priceFigs(d: SharedCostLite): { k: string; v: string; s: string }[] {
  const rec = d.decision?.recommendation ?? {};
  return d.quantities
    .map((q) => ({ q, r: rec[String(q)] }))
    .filter((x) => x.r && Number.isFinite(x.r.unit_cost_usd))
    .slice(0, 4)
    .map(({ q, r }) => ({ k: `At ${q.toLocaleString("en-US")}`, v: money(r!.unit_cost_usd), s: wayName(r!.process) }));
}

/** The quantity the "every process" list is priced at: 10 when quoted, else the first quantity. */
export function listQty(d: SharedCostLite): number | null {
  if (d.quantities.includes(10)) return 10;
  return d.quantities[0] ?? null;
}

export interface WayRow {
  key: string;
  name: string;
  note: string;
  price: string;
}

function firstClause(s: string): string {
  return s.split(/(?<=\.)\s/)[0].replace(/\s*\(\d+(\.\d+)?% of [^)]*\)/g, "").replace(/\s+for [a-z0-9_]+\.?$/i, "").replace(/\.$/, "");
}

/** Every priced way at the list quantity, cheapest first; a way that needs a design change says so. */
export function wayRows(d: SharedCostLite, qty: number | null): WayRow[] {
  if (qty == null) return [];
  return d.estimates
    .filter((e) => e.quantity === qty && Number.isFinite(e.unit_cost_usd))
    .sort((a, b) => a.unit_cost_usd - b.unit_cost_usd)
    .map((e) => {
      const lead = e.lead_time && e.lead_time.low_days != null && e.lead_time.high_days != null ? `${Math.round(e.lead_time.low_days)}–${Math.round(e.lead_time.high_days)} days` : "";
      const why = e.environment_excluded ? "Ruled out by the service conditions" : !e.dfm_ready ? `Only after a design change${e.dfm_blockers?.[0] ? `: ${firstClause(e.dfm_blockers[0]).toLowerCase()}` : ""}` : "";
      return { key: `${e.process}-${e.material}`, name: `${wayName(e.process)} · ${e.material}`, note: [why, lead].filter(Boolean).join(" · "), price: money(e.unit_cost_usd) };
    });
}

/** The engine's range for its pick at the list quantity, when it reported one. */
export function pickRange(d: SharedCostLite, qty: number | null): string | null {
  if (qty == null) return null;
  const r = d.decision?.recommendation?.[String(qty)];
  if (!r) return null;
  const e = d.estimates.find((x) => x.process === r.process && x.quantity === qty && x.material === r.material) ?? d.estimates.find((x) => x.process === r.process && x.quantity === qty);
  const c = e?.confidence;
  if (!c || !Number.isFinite(c.low_usd) || !Number.isFinite(c.high_usd)) return null;
  return `${wayName(r.process)} at ${qty.toLocaleString("en-US")}: ${money(c.low_usd)}–${money(c.high_usd)} (±${Math.round(c.half_width_pct)}%${c.validated ? ", from real costs" : ", no real costs yet"})`;
}

export function crossoverLine(d: SharedCostLite): string | null {
  const x = d.decision;
  if (!x?.crossover_qty || !x.tooling_process) return null;
  return `${wayName(x.tooling_process)} costs less from about ${x.crossover_qty.toLocaleString("en-US")} parts${x.tooling_dfm_ready === false ? ", after a design change" : ""}`;
}

/* ---------- shared check (P9) ---------- */

export interface SharedIssue {
  code: string;
  severity: string;
  message: string;
}

export interface SharedCheckLite {
  filename: string;
  created_at: string;
  face_count: number;
  best_process: string | null;
  geometry: { bounding_box_mm?: number[]; volume_mm3?: number; is_watertight?: boolean; faces?: number } | null;
  process_scores: { process: string; score: number; verdict: string; issues: SharedIssue[] }[];
  universal_issues: SharedIssue[];
}

export interface CheckWay {
  key: string;
  name: string;
  count: string;
  verdict: string;
  tone: "ok" | "warn" | "bad";
  findings: string[];
}

function findingLine(i: SharedIssue): string {
  return `${findingName(i.code, i.message)} (${SEVERITY[i.severity] ?? i.severity})`;
}

/** Every way, best first: the ones that can make it (by score), then the ones that can't. */
export function checkWays(d: SharedCheckLite): CheckWay[] {
  const ways = [...(d.process_scores ?? [])].sort((a, b) => Number(a.verdict === "fail") - Number(b.verdict === "fail") || b.score - a.score);
  return ways.map((p) => {
    const n = p.issues?.length ?? 0;
    const cant = p.verdict === "fail";
    const order: Record<string, number> = { error: 0, warning: 1, info: 2 };
    const issues = [...(p.issues ?? [])].sort((a, b) => (order[a.severity] ?? 3) - (order[b.severity] ?? 3));
    return {
      key: p.process,
      name: wayName(p.process),
      count: n === 1 ? "1 finding" : `${n} findings`,
      verdict: cant ? "Can't" : n ? "Check" : "Can make",
      tone: cant ? "bad" : n ? "warn" : "ok",
      findings: issues.map(findingLine),
    };
  });
}

export function checkFacts(d: SharedCheckLite): { can: number; cant: number; total: number } {
  const total = d.process_scores?.length ?? 0;
  const cant = (d.process_scores ?? []).filter((p) => p.verdict === "fail").length;
  return { can: total - cant, cant, total };
}

export function partFindings(d: SharedCheckLite): string[] {
  return (d.universal_issues ?? []).map(findingLine);
}
