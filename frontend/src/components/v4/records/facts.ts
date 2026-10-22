/**
 * What a saved record (a cost decision) says, read off its own immutable
 * engine result: material class, conditions, the machine verdict, the cheapest
 * way and your machines' way at each priced quantity, the outcome routes and
 * their locks, cost inputs with their sources, and the Compare deltas.
 *
 * Honesty: every figure is selected from the record's estimates or decision;
 * nothing is interpolated between priced quantities. A missing value is null
 * and the screen says so. Pure, so it runs under `node --test` (facts.test.ts).
 */
import type { CostDecisionDetail, CostDecisionSummary, CostEstimate, CostReport } from "@/lib/api";
import { OUTCOMES, VERDICT, materialClass, money, num, way, wayLower, type OutcomeKey, type Tone } from "./words.ts";
import { ROUNDING_KEY, footLines, lineDriver, roundingWords } from "../../../lib/cost-lines.ts";

/* ── reading the result ─────────────────────────────────────────────────── */

interface PerRoute {
  verdict?: string;
  best_machine?: string | null;
  machines_evaluated?: number;
}
interface Verification {
  verdict?: string;
  best_machine?: string | null;
  per_route?: Record<string, PerRoute>;
  env_exclusions?: { axis?: string; human?: string }[];
  inventory_declared?: boolean;
  environment_declared?: boolean;
}

export function verificationOf(r: CostReport | null | undefined): Verification | null {
  const v = (r as { verification?: unknown } | null | undefined)?.verification;
  return v && typeof v === "object" ? (v as Verification) : null;
}

const IN_HOUSE = new Set(["makeable_in_house", "makeable_with_secondary_op"]);

/** Quantities the record was priced at, ascending. */
export function quantitiesOf(r: CostReport | null | undefined): number[] {
  const qs = new Set<number>();
  for (const q of r?.quantities ?? []) if (Number.isFinite(q)) qs.add(q);
  if (!qs.size) for (const e of r?.estimates ?? []) qs.add(e.quantity);
  return [...qs].sort((a, b) => a - b);
}

function recAt(r: CostReport, q: number): { process: string; material: string; unit_cost_usd: number; lead_low_days: number | null; lead_high_days: number | null } | null {
  const map = r.decision?.recommendation;
  if (!map) return null;
  const hit = map[String(q)] ?? Object.entries(map).find(([k]) => Number(k) === q)?.[1];
  return hit && hit.process ? hit : null;
}

function estimateFor(r: CostReport, q: number, process: string, material?: string | null): CostEstimate | null {
  return r.estimates.find((e) => e.quantity === q && e.process === process && (!material || e.material === material)) ?? null;
}

export function dfmOk(e: CostEstimate | null | undefined): boolean {
  return !!e && e.dfm_ready === true && e.dfm_verdict !== "fail" && !(e.dfm_blockers && e.dfm_blockers.length);
}

/** The engine's cheapest way at a quantity (its recommendation), with the matching estimate. */
export interface Cheapest {
  process: string;
  material: string;
  usd: number;
  leadLo: number | null;
  leadHi: number | null;
  est: CostEstimate | null;
}

export function cheapestAt(r: CostReport | null | undefined, q: number): Cheapest | null {
  if (!r) return null;
  const p = recAt(r, q);
  if (!p) return null;
  return {
    process: p.process,
    material: p.material,
    usd: p.unit_cost_usd,
    leadLo: p.lead_low_days ?? null,
    leadHi: p.lead_high_days ?? null,
    est: estimateFor(r, q, p.process, p.material),
  };
}

/**
 * The cheapest way that works as drawn at a quantity, from the record's own
 * estimates: not ruled out by conditions, no design problem that stops it.
 * Compare's headline uses this, so it agrees with the table under it (a
 * revision whose draft fix made molding workable is compared on molding),
 * where the engine's recommendation may prefer a route without tooling.
 */
export function cheapestWorkableAt(r: CostReport | null | undefined, q: number): Cheapest | null {
  if (!r) return null;
  const ok = r.estimates.filter((e) => e.quantity === q && !e.environment_excluded && dfmOk(e) && Number.isFinite(e.unit_cost_usd));
  if (!ok.length) return null;
  const best = ok.reduce((a, b) => (b.unit_cost_usd < a.unit_cost_usd ? b : a));
  return {
    process: best.process,
    material: best.material,
    usd: best.unit_cost_usd,
    leadLo: best.lead_time?.low_days ?? null,
    leadHi: best.lead_time?.high_days ?? null,
    est: best,
  };
}

/** Your machines' way at a quantity: for each route your machines can make, its cheapest surviving estimate. */
export interface MineRoute {
  process: string;
  material: string;
  usd: number;
  machine: string | null;
  est: CostEstimate;
}

export function inHouseAt(r: CostReport | null | undefined, q: number): MineRoute[] {
  const v = verificationOf(r);
  if (!r || !v?.per_route) return [];
  const out: MineRoute[] = [];
  for (const [process, fit] of Object.entries(v.per_route)) {
    if (!fit || !IN_HOUSE.has(fit.verdict ?? "")) continue;
    const pool = r.estimates.filter((e) => e.quantity === q && e.process === process && !e.environment_excluded);
    if (!pool.length) continue;
    const best = pool.reduce((a, b) => (b.unit_cost_usd < a.unit_cost_usd ? b : a));
    out.push({ process, material: best.material, usd: best.unit_cost_usd, machine: fit.best_machine ?? v.best_machine ?? null, est: best });
  }
  return out.sort((a, b) => a.usd - b.usd);
}

/** The quantity a record opens at: the recorded outcome's, else 10 when priced, else the first priced. */
export function defaultQty(d: Picked<CostDecisionDetail, "result" | "disposition_basis">): number | null {
  const qs = quantitiesOf(d.result);
  const b = d.disposition_basis?.quantity;
  if (b != null && qs.includes(b)) return b;
  if (qs.includes(10)) return 10;
  return qs[0] ?? null;
}
type Picked<T, K extends keyof T> = { [P in K]: T[P] };

/* ── the record's facts ─────────────────────────────────────────────────── */

export interface RecordFacts {
  material: string;
  materialCode: string | null;
  /** true: conditions were declared when it was checked; false: none; null: not recorded. */
  envDeclared: boolean | null;
  verdict: string | null;
  verdictLabel: string;
  verdictTone: Tone;
  bestMachine: string | null;
  inventoryDeclared: boolean;
  ruledOut: string[];
  quantities: number[];
}

export function recordFacts(r: CostReport | null | undefined): RecordFacts {
  const v = verificationOf(r);
  const vd = v?.verdict ?? null;
  const [label, tone] = vd && VERDICT[vd] ? VERDICT[vd] : ["Not checked", "unk" as Tone];
  return {
    material: materialClass(r?.material_class),
    materialCode: r?.material_class ?? null,
    envDeclared: v ? v.environment_declared === true : null,
    verdict: vd,
    verdictLabel: v ? label : "Not checked",
    verdictTone: v ? tone : "unk",
    bestMachine: v?.best_machine ?? null,
    inventoryDeclared: v?.inventory_declared === true,
    ruledOut: (v?.env_exclusions ?? []).map((x) => x.axis ?? "").filter(Boolean),
    quantities: quantitiesOf(r),
  };
}

/** "Stainless · sour gas", "Plastic", "Aluminum · conditions not recorded". `tag` is the part's conditions in a word. */
export function whatLine(f: RecordFacts, tag: string | null, sep = " · "): string {
  if (f.envDeclared === true) return `${f.material}${sep}${tag ?? "with conditions"}`;
  if (f.envDeclared === null) return f.material;
  return f.material;
}

/** One sentence for what the record found at a quantity (list/compare "answer"). */
export function answerLine(r: CostReport | null | undefined, q: number | null): string {
  const f = recordFacts(r);
  if (!r || q == null) return "No priced quantity";
  const ch = cheapestAt(r, q);
  const mine = inHouseAt(r, q)[0] ?? null;
  const cheapest = ch ? `cheapest ${money(ch.usd)} by ${wayLower(ch.process)}` : "";
  switch (f.verdict) {
    case "makeable_in_house":
    case "makeable_with_secondary_op":
      return `On your ${f.bestMachine ?? "machine"}${mine ? ` · ${money(mine.usd)} at ${num(q)}` : ""}${ch && mine && ch.usd < mine.usd ? ` · outside ${money(ch.usd)}` : ""}`;
    case "environment_excluded":
      return "Ruled out by the conditions";
    case "makeable_not_on_owned":
      return `Not on your machines${cheapest ? ` · ${cheapest}` : ""}`;
    case "makeable_outsource_only":
      return `Outside only${cheapest ? ` · ${cheapest}` : ""}`;
    case "not_makeable":
      return "Can't be made as drawn";
    default:
      return `Priced before machines were added${cheapest ? ` · ${cheapest}` : ""}`;
  }
}

/* ── the record list (summary fields only) ──────────────────────────────── */

export type RecordStatus = { label: string; tone: Tone };

export function statusOf(r: Picked<CostDecisionSummary, "approval_status" | "user_disposition" | "is_stale">): RecordStatus {
  if (r.is_stale) return { label: "Out of date", tone: "warn" };
  if (r.approval_status === "approved") return { label: "Approved", tone: "ok" };
  if (r.user_disposition) return { label: "Decided", tone: "ok" };
  return { label: "Not reviewed", tone: "unk" };
}

export type RecordFilter = "all" | "review" | "decided" | "stale";

export function keepRecord(r: Picked<CostDecisionSummary, "approval_status" | "user_disposition" | "is_stale">, f: RecordFilter): boolean {
  if (f === "review") return r.approval_status !== "approved";
  if (f === "decided") return !!r.user_disposition;
  if (f === "stale") return r.is_stale === true;
  return true;
}

/** A list row's two lines from the summary alone (the list endpoint carries no material or verdict). */
export function summaryLines(r: CostDecisionSummary): { what: string; answer: string } {
  const qs = [...(r.quantities ?? [])].sort((a, b) => a - b);
  const qText = qs.length ? (qs.length === 1 ? `priced at ${num(qs[0])}` : `priced at ${num(qs[0])} to ${num(qs[qs.length - 1])}`) : "no priced quantity";
  const basis = r.disposition_basis;
  const what = r.user_disposition_label
    ? `${r.user_disposition_label}${basis ? ` · ${wayLower(basis.process)} at ${num(basis.quantity)}` : ""}`
    : r.make_now_process
      ? `ScaleCAD’s pick: ${wayLower(r.make_now_process)}`
      : "No process priced";
  const cross = r.crossover_qty != null ? ` · tooling pays off near ${num(Math.round(r.crossover_qty))}` : "";
  return { what, answer: `${qText}${cross} · #${r.id.slice(-6)}` };
}

/** Records grouped by part (mesh hash, else file name), parts in first-seen order. */
export function groupByPart<T extends { mesh_hash?: string; filename: string }>(rows: T[]): { key: string; filename: string; rows: T[] }[] {
  const out: { key: string; filename: string; rows: T[] }[] = [];
  const at = new Map<string, number>();
  for (const r of rows) {
    const key = r.mesh_hash || `file:${r.filename}`;
    const i = at.get(key);
    if (i == null) {
      at.set(key, out.length);
      out.push({ key, filename: r.filename, rows: [r] });
    } else out[i].rows.push(r);
  }
  return out;
}

/* ── outcome routes and their locks ─────────────────────────────────────── */

export interface RouteOption {
  value: string;
  label: string;
  process: string;
  material: string;
  mine: boolean;
  est: CostEstimate | null;
}

export function routeValue(process: string, material: string): string {
  return `${process}~${material}`;
}

/** The routes an outcome can be about at a quantity: your machines' ways first, then the cheapest when it differs. */
export function routeOptions(r: CostReport | null | undefined, q: number | null): RouteOption[] {
  if (!r || q == null) return [];
  const out: RouteOption[] = [];
  for (const m of inHouseAt(r, q)) {
    out.push({
      value: routeValue(m.process, m.material),
      label: `Your ${m.machine ?? "machine"}: ${way(m.process)} · ${money(m.usd)}`,
      process: m.process,
      material: m.material,
      mine: true,
      est: m.est,
    });
  }
  const ch = cheapestAt(r, q);
  if (ch && !out.some((o) => o.process === ch.process && o.material === ch.material)) {
    out.push({ value: routeValue(ch.process, ch.material), label: `Cheapest: ${way(ch.process)} · ${money(ch.usd)}`, process: ch.process, material: ch.material, mine: false, est: ch.est });
  }
  return out;
}

/** Why each outcome can't be recorded on a route (null = allowed). Mirrors the server's rules. */
export function outcomeLocks(r: CostReport | null | undefined, route: RouteOption | null, q: number | null, hasMine: boolean): Record<OutcomeKey, string | null> {
  const none = q == null ? "No priced quantity on this record." : `No computed price at ${num(q)}. Pick another quantity.`;
  // Keep buying from our supplier needs no route of ScaleCAD's, only a quantity.
  const all = (why: string | null) =>
    Object.fromEntries(OUTCOMES.map((o) => [o.key, o.key === "supplier" && q != null ? null : why])) as Record<OutcomeKey, string | null>;
  if (!r || !route || !route.est) return all(none);
  if (r.status === "GEOMETRY_INVALID") return all("The file's geometry didn't pass, so no outcome can be recorded. Check a repaired file.");
  if (route.est.environment_excluded) return all("The part's conditions rule out this route. Pick a route that survives them.");
  const out = all(null);
  if (!route.mine) out.inhouse = `Make in-house needs a route on your machines.${hasMine ? " Pick your machine's route above." : " None of yours can make this record."}`;
  else if (!dfmOk(route.est)) out.inhouse = "This route doesn't pass the design checks, so Make in-house stays locked. Record Redesign, Make outside or Acquire capability.";
  if (!dfmOk(route.est)) out.outside = "This route can't make the part as drawn. Record Redesign for it, or pick a route that passes.";
  return out;
}

/* ── cost inputs ────────────────────────────────────────────────────────── */

const DRIVER: Record<string, string> = {
  material_cost: "Material",
  // A dollar line is "Machine"; machine time is the hours on the cycle line (ce-20).
  machine_cost: "Machine",
  labor_cost: "Labor",
  setup_cost: "Setup",
  nre_cost: "Programming",
  inspection_cost: "Inspection",
  consumables_cost: "Tools and coolant",
  tooling_cost: "Tooling, the whole tool",
  tooling_per_part: "Tooling, a part",
  finishing_cost: "Finishing",
  sinter_cost: "Sintering",
  post_process_cost: "Post-processing",
  min_charge_floor: "Minimum charge",
  support_cost: "Supports",
  energy_cost: "Energy",
  // A spec's own line reads as the spec is named (backend src/costing/part_specs.py).
  spec_bead_blast_cost: "Bead blast",
  spec_anodize_ii_cost: "Anodize (Type II)",
  spec_anodize_iii_cost: "Hard anodize (Type III)",
  spec_passivate_cost: "Passivation",
  spec_electropolish_cost: "Electropolish",
  spec_powder_coat_cost: "Powder coat",
  spec_plating_cost: "Plating",
  spec_stress_relief_cost: "Stress relief",
  spec_solution_age_cost: "Solution treat and age",
  spec_quench_temper_cost: "Quench and temper",
  spec_case_harden_cost: "Case hardening",
  spec_hip_cost: "HIP (hot isostatic pressing)",
  spec_fai_as9102_cost: "First article inspection (AS9102)",
  spec_cmm_report_cost: "CMM report",
  spec_full_100_cost: "100% inspection",
  spec_fine_finish_cost: "Grind or polish to the Ra",
  blank_outside_cost: "Blank cut outside",
};

/** A cost input's plain name: "First article inspection (AS9102)", never "Spec fai as9102". */
export function driverLabel(name: string): string {
  return DRIVER[name] ?? name.replace(/^spec_/, "").replace(/_cost$/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export type SrcKind = "file" | "yours" | "typ";

export interface CostLine {
  key: string;
  label: string;
  usd: number;
  src: SrcKind;
  srcLabel: string;
  source: string;
}

export function srcOf(provenance: string | null | undefined, rateCard?: number | null): { kind: SrcKind; label: string } {
  const p = String(provenance ?? "").toUpperCase();
  if (p === "USER") return { kind: "yours", label: "Yours" };
  if (p === "SHOP") return { kind: "yours", label: rateCard != null ? `Your rates v${rateCard}` : "Your shop" };
  if (p === "MEASURED" || p === "CAD") return { kind: "file", label: "File" };
  return { kind: "typ", label: "Typical" };
}

/** The dollar inputs behind one estimate, each with where it came from. */
/** The record's cost lines (ce-01): the engine's summing lines, each rounded to the cent and
 *  told by its driver, then a Rounding line when they need one to add up to the price shown.
 *  An estimate without its lines falls back to its dollar drivers. */
export function costLines(e: CostEstimate | null | undefined): CostLine[] {
  if (!e) return [];
  const asLine = (d: CostEstimate["drivers"][number], usd: number): CostLine => {
    const s = srcOf(d.provenance, d.rate_card);
    const base = driverLabel(d.name);
    return { key: d.name, label: d.name === "material_cost" ? `${base}, ${e.material}` : base, usd, src: s.kind, srcLabel: s.label, source: d.source ?? "" };
  };
  const items = e.line_items ?? {};
  if (!Object.keys(items).length) {
    return (e.drivers ?? [])
      .filter((d) => {
        const u = String(d.unit ?? "").toLowerCase();
        return (u === "$" || u === "usd") && Number.isFinite(d.value);
      })
      .map((d) => asLine(d, d.value));
  }
  const f = footLines(items, e.unit_cost_usd);
  const byName = new Map((e.drivers ?? []).map((d) => [d.name, d]));
  const out: CostLine[] = f.lines.map((l) => {
    const d = byName.get(lineDriver(l.key));
    return d ? asLine(d, l.cents / 100) : { key: l.key, label: driverLabel(l.key), usd: l.cents / 100, src: "typ", srcLabel: "Typical", source: "" };
  });
  if (f.roundingCents && f.isRounding) out.push({ key: ROUNDING_KEY, label: "Rounding", usd: f.roundingCents / 100, src: "typ", srcLabel: "Arithmetic", source: roundingWords(f) });
  return out;
}

/** "$15.77–$47.31" and "±50%" for an estimate; `validated` says whether real costs back the band. */
export function rangeOf(e: CostEstimate | null | undefined): { text: string; pct: number | null; validated: boolean; n: number } | null {
  if (!e) return null;
  const c = e.confidence;
  if (c && Number.isFinite(c.low_usd) && Number.isFinite(c.high_usd)) {
    return { text: `${money(c.low_usd)}–${money(c.high_usd)}`, pct: Number.isFinite(c.half_width_pct) ? Math.round(c.half_width_pct) : null, validated: c.validated === true, n: c.n_samples ?? 0 };
  }
  if (Number.isFinite(e.est_error_band_pct)) {
    const p = e.est_error_band_pct / 100;
    return { text: `${money(e.unit_cost_usd * (1 - p))}–${money(e.unit_cost_usd * (1 + p))}`, pct: Math.round(e.est_error_band_pct), validated: false, n: 0 };
  }
  return null;
}

/* ── compare ────────────────────────────────────────────────────────────── */

export interface WayCell {
  usd: number | null;
  band: number | null;
  /** "ok": workable as drawn; "redesign": priced but fails design checks; "out": conditions rule out every material. */
  state: "ok" | "redesign" | "out";
  material: string | null;
}

/** The cheapest workable material for one way at a quantity (redesign-only when none passes; "out" when all are ruled out). */
export function wayCell(r: CostReport | null | undefined, process: string, q: number): WayCell | null {
  if (!r) return null;
  const pool = r.estimates.filter((e) => e.process === process && e.quantity === q);
  if (!pool.length) return null;
  const alive = pool.filter((e) => !e.environment_excluded);
  if (!alive.length) return { usd: null, band: null, state: "out", material: null };
  const ok = alive.filter(dfmOk);
  const from = ok.length ? ok : alive;
  const best = from.reduce((a, b) => (b.unit_cost_usd < a.unit_cost_usd ? b : a));
  return { usd: best.unit_cost_usd, band: Number.isFinite(best.est_error_band_pct) ? Math.round(best.est_error_band_pct) : null, state: ok.length ? "ok" : "redesign", material: best.material };
}

export interface WayRow {
  process: string;
  a: WayCell | null;
  b: WayCell | null;
  /** B vs A in whole percent (a decimal kept at the ±100% edge), only when both are priced and neither is ruled out. */
  pct: number | null;
  pick: boolean;
}

/** A change in percent, whole unless it rounds to the ±100% edge: $30,123.93 → $21.94 is −99.9%, never −100% (ce-20). */
export function changePct(a: number, b: number): number {
  const p = (100 * (b - a)) / a;
  const m = Math.abs(p);
  const d = m >= 99.5 && m < 100 ? (m >= 99.95 ? 100 : 10) : 1;
  return Math.round(p * d) / d;
}

export function wayTable(A: CostReport | null | undefined, B: CostReport | null | undefined, q: number): WayRow[] {
  const procs = new Set<string>();
  for (const e of A?.estimates ?? []) if (e.quantity === q) procs.add(e.process);
  for (const e of B?.estimates ?? []) if (e.quantity === q) procs.add(e.process);
  const pa = cheapestWorkableAt(A, q)?.process ?? null;
  const pb = cheapestWorkableAt(B, q)?.process ?? null;
  const rows = [...procs].map((p) => {
    const a = wayCell(A, p, q);
    const b = wayCell(B, p, q);
    const both = a?.usd != null && b?.usd != null && a.usd > 0;
    return { process: p, a, b, pct: both ? changePct(a!.usd!, b!.usd!) : null, pick: p === pa || p === pb };
  });
  const key = (r: WayRow) => Math.min(r.a?.usd ?? Infinity, r.b?.usd ?? Infinity);
  return rows.sort((x, y) => key(x) - key(y) || x.process.localeCompare(y.process));
}

/** Quantities both records were priced at. */
export function sharedQuantities(A: CostReport | null | undefined, B: CostReport | null | undefined): number[] {
  const b = new Set(quantitiesOf(B));
  return quantitiesOf(A).filter((q) => b.has(q));
}

/** Ways that can make the part at a quantity: workable as drawn, and priced but only after a redesign. */
export function waysCount(r: CostReport | null | undefined, q: number): { ok: number; redesign: number } {
  const procs = new Set((r?.estimates ?? []).filter((e) => e.quantity === q).map((e) => e.process));
  let ok = 0;
  let redesign = 0;
  for (const p of procs) {
    const c = wayCell(r, p, q);
    if (c?.state === "ok") ok += 1;
    else if (c?.state === "redesign") redesign += 1;
  }
  return { ok, redesign };
}

/** Make now (cheapest way without tooling) against the tooling way, at every priced quantity. */
export interface ToolingChart {
  qs: number[];
  make: (number | null)[];
  makeWay: (string | null)[];
  tool: (number | null)[];
  toolWay: string;
  toolNeedsRedesign: boolean;
  crossover: number | null;
}

export function toolingChart(r: CostReport | null | undefined): ToolingChart | null {
  const tp = r?.decision?.tooling_process;
  if (!r || !tp) return null;
  const qs = quantitiesOf(r);
  const make = qs.map((q) => cheapestAt(r, q)?.usd ?? null);
  const makeWay = qs.map((q) => cheapestAt(r, q)?.process ?? null);
  const tool = qs.map((q) => {
    const c = wayCell(r, tp, q);
    return c && c.usd != null ? c.usd : null;
  });
  if (!make.some((v) => v != null) || !tool.some((v) => v != null)) return null;
  const toolNeedsRedesign = qs.some((q) => wayCell(r, tp, q)?.state === "redesign") || r.decision?.tooling_dfm_ready === false;
  return { qs, make, makeWay, tool, toolWay: tp, toolNeedsRedesign, crossover: r.decision?.crossover_qty ?? null };
}

/** SVG paths for the chart (log quantity × log price) in a 600×190 box. */
export function chartPaths(c: ToolingChart, at: number): { make: string; tool: string; marker: string; cross: string } {
  const lx = (q: number) => Math.log10(q);
  const x0 = lx(c.qs[0]);
  const x1 = lx(c.qs[c.qs.length - 1]);
  const X = (q: number) => (c.qs.length > 1 && x1 > x0 ? 8 + (584 * (lx(q) - x0)) / (x1 - x0) : 300);
  const vals = [...c.make, ...c.tool].filter((v): v is number => v != null && v > 0);
  const y0 = Math.log10(Math.min(...vals));
  const y1 = Math.log10(Math.max(...vals));
  const Y = (v: number) => 182 - 172 * (y1 > y0 ? (Math.log10(v) - y0) / (y1 - y0) : 0.5);
  const path = (arr: (number | null)[]) => {
    let s = "";
    let pen = false;
    arr.forEach((v, i) => {
      if (v == null || v <= 0) {
        pen = false;
        return;
      }
      s += `${pen ? "L" : "M"}${X(c.qs[i]).toFixed(1)} ${Y(v).toFixed(1)} `;
      pen = true;
    });
    return s.trim();
  };
  const q = c.qs[Math.max(0, Math.min(c.qs.length - 1, at))];
  const cross = c.crossover != null && c.crossover >= c.qs[0] && c.crossover <= c.qs[c.qs.length - 1] ? `M${X(c.crossover).toFixed(1)} 4V186` : "";
  return { make: path(c.make), tool: path(c.tool), marker: `M${X(q).toFixed(1)} 4V186`, cross };
}
