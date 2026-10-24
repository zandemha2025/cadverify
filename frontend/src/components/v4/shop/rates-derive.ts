/**
 * Pure helpers for Rates (board S1): the rate card rows (from a governed card's
 * table, or the defaults the engine recorded on a saved check), regional
 * multipliers, a part's cost lines with a labor-rate preview, and where every
 * cost input on your parts comes from. Numbers only ever come from the caller's
 * API data; a value that isn't there isn't shown.
 */
import type { Assumption, CostLine, EstimateRow, RecordDetail } from "./shop-api";

export type Prov = "yours" | "file" | "typ";

export function provOf(p: string | null | undefined): Prov {
  if (p === "USER" || p === "SHOP") return "yours";
  if (p === "MEASURED" || p === "CAD") return "file";
  return "typ";
}

export const PROV_TAG: Record<Prov, string> = { yours: "Yours", file: "Your file", typ: "Typical" };

/* ------------------------------------------------------------------ */
/*  Rate card rows                                                      */
/* ------------------------------------------------------------------ */

type RowSpec = { key: string; name: string; note: string; fmt: (v: number) => string };

const money = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pct = (v: number) => `${Math.round(v * 1000) / 10}%`;

export const CARD_ROWS: RowSpec[] = [
  { key: "labor_rate", name: "Labor, loaded shop floor", note: "Finishing, setup, programming, inspection", fmt: (v) => `${money(v)}/h` },
  { key: "margin", name: "Margin", note: "Should-cost, not price", fmt: pct },
  {
    key: "overhead",
    name: "Overhead",
    note: "Indirect burden on conversion cost, the work done on the shop floor: machine (and the tools line, a share of it), labor, setup, programming, inspection, and finish machining, sintering, metal-printing post work or declared hand operations where the process has them; not material, tooling, EDM wire or outside finishing; price = cost × (1 + overhead) on those lines",
    fmt: pct,
  },
  { key: "utilization", name: "Machine utilization", note: "", fmt: pct },
  { key: "machine_capital_frac", name: "Machine payback share of rate", note: "Excluded for machines you own", fmt: pct },
  { key: "stock_allowance", name: "Machining stock allowance", note: "Billet over part size", fmt: (v) => `${v.toFixed(2)}×` },
  { key: "daily_machine_hours", name: "Machine hours per day", note: "Lead times", fmt: (v) => String(Math.round(v * 100) / 100) },
  { key: "ship_days", name: "Shipping", note: "", fmt: (v) => `${Math.round(v * 100) / 100} days` },
];

export type CardRow = { key: string; name: string; note: string; value: string; prov: Prov };

/** Rows from a governed card's table (`payload.global`). Missing keys are left out. */
export function rowsFromPayload(payload: unknown): CardRow[] {
  const g = (payload as { global?: Record<string, unknown> } | null)?.global;
  if (!g || typeof g !== "object") return [];
  const out: CardRow[] = [];
  for (const r of CARD_ROWS) {
    const v = g[r.key];
    if (typeof v === "number" && Number.isFinite(v)) out.push({ key: r.key, name: r.name, note: r.note, value: r.fmt(v), prov: "yours" });
  }
  return out;
}

/**
 * Rows from the defaults a saved check recorded (`assumptions` tagged DEFAULT):
 * what the built-in card v0 actually said when the engine ran. Only keys the
 * check recorded are returned.
 */
export function rowsFromAssumptions(assumptions: Assumption[] | null | undefined): CardRow[] {
  const by = new Map((assumptions ?? []).filter((a) => a.provenance === "DEFAULT").map((a) => [a.name, a]));
  const out: CardRow[] = [];
  for (const r of CARD_ROWS) {
    const a = by.get(r.key);
    if (a && typeof a.value === "number" && Number.isFinite(a.value)) out.push({ key: r.key, name: r.name, note: r.note, value: r.fmt(a.value), prov: "typ" });
  }
  return out;
}

/**
 * The default (v0) values across saved checks, newest first: for each input the
 * newest value the engine tagged DEFAULT. A check costed with a shop profile or
 * a user override records those instead, and they aren't the card.
 */
export function defaultsFrom(lists: (Assumption[] | null | undefined)[]): Assumption[] {
  const seen = new Map<string, Assumption>();
  for (const list of lists) for (const a of list ?? []) if (a.provenance === "DEFAULT" && !seen.has(a.name)) seen.set(a.name, a);
  return Array.from(seen.values());
}

/* ------------------------------------------------------------------ */
/*  Regional multipliers                                                */
/* ------------------------------------------------------------------ */

export const REGIONS: [string, string][] = [
  ["US", "United States"],
  ["EU", "Europe"],
  ["MX", "Mexico"],
  ["CN", "China"],
  ["IN", "India"],
  ["SA", "Saudi Arabia"],
];

export type RegionRow = { code: string; name: string; labor: string; material: string; tooling: string };

const mult = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? `×${v.toFixed(2)}` : "—");

export function regionsFromPayload(payload: unknown): RegionRow[] {
  const p = payload as Record<string, Record<string, unknown> | undefined> | null;
  if (!p?.region_labor) return [];
  return REGIONS.map(([code, name]) => ({
    code,
    name,
    labor: mult(p.region_labor?.[code]),
    material: mult(p.region_material?.[code]),
    tooling: mult(p.region_tooling?.[code]),
  }));
}

/** The regions saved checks were costed in, read from their recorded multipliers. */
export function regionsFromAssumptions(lists: (Assumption[] | null | undefined)[]): RegionRow[] {
  const seen = new Map<string, RegionRow>();
  for (const list of lists) {
    const by = new Map((list ?? []).map((a) => [a.name, a]));
    const lab = by.get("region_labor");
    const code = lab?.source.match(/region ([A-Z]{2})\b/)?.[1];
    if (!code || seen.has(code)) continue;
    seen.set(code, {
      code,
      name: REGIONS.find(([c]) => c === code)?.[1] ?? code,
      labor: mult(lab?.value),
      material: mult(by.get("region_material")?.value),
      tooling: mult(by.get("region_tooling")?.value),
    });
  }
  return REGIONS.map(([c]) => seen.get(c)).filter((r): r is RegionRow => !!r);
}

/* ------------------------------------------------------------------ */
/*  A part's headline estimate and cost lines                           */
/* ------------------------------------------------------------------ */

/** The quantity the sheet shows: 10 when the check had it, else the first. */
export function headlineQty(quantities: number[] | null | undefined): number | null {
  if (!quantities?.length) return null;
  return quantities.includes(10) ? 10 : quantities[0];
}

/** The recommended estimate at that quantity (the decision's own pick). */
export function headlineEstimate(d: RecordDetail): EstimateRow | null {
  const r = d.result;
  if (!r?.estimates?.length) return null;
  const qty = headlineQty(d.quantities);
  if (qty == null) return null;
  const rec = r.decision?.recommendation?.[String(qty)];
  const proc = rec?.process ?? r.decision?.make_now_process ?? d.make_now_process;
  const mat = rec?.material ?? r.decision?.make_now_material ?? null;
  return (
    r.estimates.find((e) => e.quantity === qty && e.process === proc && (mat == null || e.material === mat)) ??
    r.estimates.find((e) => e.quantity === qty && e.process === proc) ??
    null
  );
}

const LINE_NAMES: Record<string, string> = {
  labor_cost: "Labor, finishing",
  nre_cost: "Programming",
  inspection_cost: "Inspection",
  setup_cost: "Setup",
  machine_cost: "Machine",
  material_cost: "Material",
  consumables_cost: "Tools and coolant",
  tooling_cost: "Tooling",
  finish_machining: "Finish machining",
  support_material: "Support material",
  support_removal_cost: "Support removal",
  plate_removal_cost: "Plate removal",
  stress_relief_cost: "Stress relief",
  min_charge_floor: "Order minimum",
  // Declared part specs (Conditions): one line per finish, heat treatment, inspection.
  spec_bead_blast_cost: "Bead blast",
  spec_anodize_ii_cost: "Anodize, Type II",
  spec_anodize_iii_cost: "Hard anodize, Type III",
  spec_passivate_cost: "Passivation",
  spec_electropolish_cost: "Electropolish",
  spec_powder_coat_cost: "Powder coat",
  spec_plating_cost: "Plating",
  spec_stress_relief_cost: "Stress relief",
  spec_solution_age_cost: "Solution treat and age",
  spec_quench_temper_cost: "Quench and temper",
  spec_case_harden_cost: "Case hardening",
  spec_hip_cost: "HIP",
  spec_fai_as9102_cost: "First article report, AS9102",
  spec_cmm_report_cost: "CMM report",
  spec_full_100_cost: "100% inspection",
  spec_fine_finish_cost: "Grind or polish to the Ra",
};

/** Labor-paid lines: their dollars are hours × the labor rate. */
const LABOR_LINES = new Set([
  "labor_cost", "nre_cost", "inspection_cost", "setup_cost", "support_removal_cost", "plate_removal_cost",
  "spec_bead_blast_cost", "spec_fai_as9102_cost", "spec_cmm_report_cost", "spec_full_100_cost", "spec_fine_finish_cost",
]);

export type PreviewLine = { key: string; name: string; prov: Prov; tag: string; value: number; scales: boolean };

function rateIn(source: string, rate: number): boolean {
  const re = new RegExp(`\\$${String(rate).replace(".", "\\.")}(?:\\.0+)?/hr`);
  return re.test(source);
}

/**
 * The estimate's dollar lines. A line scales with labor when it's a labor-paid
 * line and its own recorded arithmetic uses this labor rate.
 */
export function costLines(e: EstimateRow, laborRate: number | null): PreviewLine[] {
  return e.drivers
    .filter((d: CostLine) => d.unit === "$" && typeof d.value === "number" && d.name !== "min_charge_floor")
    .map((d) => {
      const prov = provOf(d.provenance);
      const hours = d.source.match(/(\d+(?:\.\d+)?)\s?hr\b/)?.[1];
      let name = LINE_NAMES[d.name] ?? d.name.replace(/_cost$/, "").replace(/_/g, " ");
      if (d.name === "machine_cost") {
        const rate = d.source.match(/× \$(\d+(?:\.\d+)?)\/hr/)?.[1];
        if (rate) name = `Machine, at ${prov === "yours" ? "your " : ""}$${rate}/h`;
      } else if (hours && LABOR_LINES.has(d.name)) {
        name = `${name}, ${hours} h`;
      }
      const scales = laborRate != null && LABOR_LINES.has(d.name) && rateIn(d.source, laborRate);
      return { key: d.name, name, prov, tag: PROV_TAG[prov], value: d.value, scales };
    });
}

export type Preview = { lines: PreviewLine[]; delta: number; total: number | null; scaling: number };

/**
 * Lines and cost each at another labor rate. The total is the recorded cost
 * each plus the change on labor-paid lines; it's withheld (null) when an order
 * minimum, margin or overhead applies, since those aren't re-run here.
 */
export function previewAt(e: EstimateRow, baseRate: number, rate: number, opts: { margin?: number; overhead?: number } = {}): Preview {
  const lines = costLines(e, baseRate);
  const k = baseRate > 0 ? rate / baseRate : 1;
  let delta = 0;
  const out = lines.map((l) => {
    if (!l.scales) return l;
    const v = l.value * k;
    delta += v - l.value;
    return { ...l, value: v };
  });
  const floor = e.drivers.some((d) => d.name === "min_charge_floor" && /\(applied\)/.test(d.source));
  const plain = !floor && !(opts.margin ?? 0) && !(opts.overhead ?? 0);
  return { lines: out, delta, total: plain ? e.unit_cost_usd + delta : null, scaling: lines.filter((l) => l.scales).length };
}

/* ------------------------------------------------------------------ */
/*  Where cost inputs come from                                         */
/* ------------------------------------------------------------------ */

export type InputCounts = { parts: number; total: number; yours: number; file: number; typ: number; measured: number };

/** Count the dollar lines on each part's headline estimate by where they come from. */
export function countInputs(estimates: (EstimateRow | null)[]): InputCounts {
  const c: InputCounts = { parts: 0, total: 0, yours: 0, file: 0, typ: 0, measured: 0 };
  for (const e of estimates) {
    if (!e) continue;
    c.parts++;
    const lines = costLines(e, null);
    for (const l of lines) {
      c.total++;
      c[l.prov]++;
    }
    if (e.confidence?.validated) c.measured += lines.length;
  }
  return c;
}

/* ------------------------------------------------------------------ */
/*  A rate card draft: labor, overhead, margin, machine rates and       */
/*  material prices (ce-13)                                             */
/* ------------------------------------------------------------------ */

export type DraftForm = {
  labor: string;
  /** percent: "15" is 15% */
  overhead: string;
  /** percent: "10" is 10% */
  margin: string;
  /** process key → $/h, prefilled with the draft's own rate */
  machines: Record<string, string>;
  /** process key → the hand work and handling allowance, hours a part (post_hr_part; 0.5 h typical on CNC) */
  hands: Record<string, string>;
  /** material name → $/kg ("" = typical) */
  materials: { name: string; price: string }[];
};

const DEC = /^(?:\d+(?:\.\d*)?|\.\d+)$/;
const trimNum = (v: number) => String(Math.round(v * 10000) / 10000);

function g(payload: unknown, key: string): number | null {
  const v = (payload as { global?: Record<string, unknown> } | null)?.global?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function procs(payload: unknown): Record<string, Record<string, unknown>> {
  return ((payload as { process?: Record<string, Record<string, unknown>> } | null)?.process ?? {}) as Record<string, Record<string, unknown>>;
}

/** The form for a draft, prefilled with the draft's own values (percent fields as percents). */
export function draftFormFrom(payload: unknown): DraftForm {
  const machines: Record<string, string> = {};
  const hands: Record<string, string> = {};
  for (const [p, f] of Object.entries(procs(payload))) {
    const r = f?.machine_rate;
    if (typeof r === "number") machines[p] = trimNum(r);
    const h = f?.post_hr_part;
    if (typeof h === "number") hands[p] = trimNum(h);
  }
  const mp = ((payload as { material_prices?: Record<string, unknown> } | null)?.material_prices ?? {}) as Record<string, unknown>;
  return {
    labor: g(payload, "labor_rate") != null ? trimNum(g(payload, "labor_rate")!) : "",
    overhead: g(payload, "overhead") != null ? trimNum(g(payload, "overhead")! * 100) : "",
    margin: g(payload, "margin") != null ? trimNum(g(payload, "margin")! * 100) : "",
    machines,
    hands,
    materials: Object.entries(mp).filter(([, v]) => typeof v === "number").map(([name, v]) => ({ name, price: trimNum(v as number) })),
  };
}

/** "15", "15%" → 0.15. Percent from 0 to 300; null when it isn't one. */
export function parsePercent(v: string): number | null {
  const t = v.trim().replace(/\s*%$/, "");
  if (!DEC.test(t)) return null;
  const n = Number(t);
  return n >= 0 && n <= 300 ? n / 100 : null;
}

function dollars(v: string): number | null {
  const t = v.trim().replace(/^\$/, "").replace(/\s*\/\s*(h|kg)$/i, "");
  return DEC.test(t) && Number(t) > 0 ? Number(t) : null;
}

const m2 = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const p1 = (v: number) => `${Math.round(v * 1000) / 10}%`;

/**
 * The draft's new table from the form, with each change in words; or the
 * errors, by field ("overhead", "machine:cnc_3axis", "material:0"). Percent
 * fields take percents, so 15 is 15%, never 1,500%.
 */
export function applyDraft(
  payload: Record<string, unknown>,
  form: DraftForm,
  procLabel: (p: string) => string,
): { ok: true; payload: Record<string, unknown>; changes: string[] } | { ok: false; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const changes: string[] = [];
  const global = { ...((payload.global as Record<string, unknown>) ?? {}) };
  const labor = dollars(form.labor);
  if (labor == null) errors.labor = "Labor in dollars an hour, more than 0.";
  const overhead = parsePercent(form.overhead);
  if (overhead == null) errors.overhead = "Overhead as a percent, 0 to 300 (15 is 15%).";
  const margin = parsePercent(form.margin);
  if (margin == null) errors.margin = "Margin as a percent, 0 to 300 (10 is 10%).";
  const near = (a: unknown, b: number) => typeof a === "number" && Math.abs(a - b) < 1e-9;
  if (labor != null && !near(global.labor_rate, labor)) {
    changes.push(`Labor ${typeof global.labor_rate === "number" ? m2(global.labor_rate) : "—"}/h → ${m2(labor)}/h`);
    global.labor_rate = labor;
  }
  if (overhead != null && !near(global.overhead, overhead)) {
    changes.push(`Overhead ${typeof global.overhead === "number" ? p1(global.overhead) : "—"} → ${p1(overhead)}`);
    global.overhead = overhead;
  }
  if (margin != null && !near(global.margin, margin)) {
    changes.push(`Margin ${typeof global.margin === "number" ? p1(global.margin) : "—"} → ${p1(margin)}`);
    global.margin = margin;
  }
  const process: Record<string, Record<string, unknown>> = { ...procs(payload) };
  for (const [p, raw] of Object.entries(form.machines)) {
    if (!process[p] || raw.trim() === "") continue;
    const r = dollars(raw);
    if (r == null) {
      errors[`machine:${p}`] = "Dollars an hour, more than 0.";
      continue;
    }
    if (!near(process[p].machine_rate, r)) {
      changes.push(`${procLabel(p)} machine ${typeof process[p].machine_rate === "number" ? m2(process[p].machine_rate as number) : "—"}/h → ${m2(r)}/h`);
      process[p] = { ...process[p], machine_rate: r };
    }
  }
  for (const [p, raw] of Object.entries(form.hands ?? {})) {
    if (!process[p] || raw.trim() === "") continue;
    const t = raw.trim().replace(/\s*h$/i, "");
    const h = DEC.test(t) ? Number(t) : NaN;
    if (!(h >= 0 && h <= 24)) {
      errors[`hand:${p}`] = "Hours a part, 0 to 24.";
      continue;
    }
    if (!near(process[p].post_hr_part, h)) {
      changes.push(`${procLabel(p)} hand work ${typeof process[p].post_hr_part === "number" ? `${process[p].post_hr_part} h` : "—"} → ${h} h a part`);
      process[p] = { ...process[p], post_hr_part: h };
    }
  }
  const before = ((payload.material_prices as Record<string, unknown>) ?? {}) as Record<string, unknown>;
  const prices: Record<string, number> = {};
  form.materials.forEach((m, i) => {
    const name = m.name.trim();
    if (!name && !m.price.trim()) return;
    if (!name) {
      errors[`material:${i}`] = "Name the material.";
      return;
    }
    const v = dollars(m.price);
    if (v == null) {
      errors[`material:${i}`] = "Dollars a kilogram, more than 0.";
      return;
    }
    prices[name] = v;
  });
  for (const [name, v] of Object.entries(prices)) {
    const was = before[name];
    if (!near(was, v)) changes.push(`${name} ${typeof was === "number" ? `${m2(was)}/kg` : "typical"} → ${m2(v)}/kg`);
  }
  for (const name of Object.keys(before)) if (!(name in prices)) changes.push(`${name} ${typeof before[name] === "number" ? `${m2(before[name] as number)}/kg` : ""} → typical`);
  if (Object.keys(errors).length) return { ok: false, errors };
  return { ok: true, payload: { ...payload, global, process, material_prices: prices }, changes };
}
