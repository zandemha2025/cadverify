/**
 * The first run (boards N1–N7), as pure functions: the material question, the
 * three tips and when they show, the machine catalog sheet (search, what each
 * machine needs for a yes, where a prefilled value comes from, the body that is
 * saved), the before/now answer after a re-check on your machines, and Home
 * before and just after the first part.
 *
 * Every number here is selected from an engine response (a CostReport, the
 * machine-fit `verification` block, a catalog template the server serves) or
 * left out; nothing is invented. Pure: no React, no fetch, and only relative
 * `.ts` runtime imports, so it runs under `node --test` (first-run.test.ts).
 */
import type { CostEstimate, CostReport, ValidationResult } from "@/lib/api";
import type { FieldProvenance, MachineInput, OwnedMachine } from "@/lib/verify/machine-api";
import type { MachineCatalogTemplate } from "@/lib/verify/machine-catalog-api";
import { buildMethods, cheapestAt, days, defaultQty, isWorkable, machineViews, methodName, money, priceAt, qtyWord, quantitiesOf, trimNum, type MachineView, type Method } from "../part/model.ts";
import { readVerification } from "../../../lib/verify/verification.ts";

/* ── N1: what will it be made of ───────────────────────────────────────── */

/** The engine's material classes, in the order the question offers them. */
export const MATERIALS: [string, string][] = [
  ["polymer", "Plastic"],
  ["aluminum", "Aluminum"],
  ["steel", "Steel"],
  ["stainless", "Stainless"],
  ["titanium", "Titanium"],
];

export function materialWord(cls: string | null | undefined): string {
  const hit = MATERIALS.find(([k]) => k === cls);
  return hit ? hit[1].toLowerCase() : cls ? cls : "plastic";
}

/** The question's state line and note, from what was picked and whether a price exists yet. */
export function askCopy(picked: string | null, pricedWith: string | null, done: boolean): { state: string; note: string } {
  if (!picked && done) {
    return { state: "Priced in plastic", note: "Not chosen, so prices use plastic, the default. Pick one to re-price this part without another check." };
  }
  if (!picked) {
    return {
      state: "Not chosen",
      note: "Prices depend on it; the shape checks don’t. Skip it and prices use plastic, the default.",
    };
  }
  const w = materialWord(picked);
  if (done && pricedWith && pricedWith !== picked) return { state: `Re-pricing in ${w}`, note: "Same file, same check: only the prices change." };
  return { state: `Prices use ${w}`, note: done ? "Change it any time; a change re-prices this part without another check." : "Change it any time; a later change re-prices without another check." };
}

/* ── N2: three tips, once per person ───────────────────────────────────── */

export type TipStep = "tip1" | "tip2" | "tip3" | "done";

export interface TipsState {
  /** finished or skipped */
  done: boolean;
  /** when the tips first showed (ms); a later visit doesn't show them again */
  shownAt: number | null;
  /** the shop card after the tips: open, put off ("Not now"), or acted on */
  shop: "open" | "later" | "done";
}

export const TIPS_WINDOW_MS = 30 * 60 * 1000;

export function tipsKey(userId: number | string): string {
  return `scalecad_firstrun_v1:${userId}`;
}

export function parseTips(raw: string | null): TipsState {
  const none: TipsState = { done: false, shownAt: null, shop: "open" };
  if (!raw) return none;
  try {
    const v = JSON.parse(raw) as Partial<TipsState> | null;
    if (!v || typeof v !== "object") return none;
    return {
      done: v.done === true,
      shownAt: typeof v.shownAt === "number" && Number.isFinite(v.shownAt) ? v.shownAt : null,
      shop: v.shop === "later" || v.shop === "done" ? v.shop : "open",
    };
  } catch {
    return none;
  }
}

/** Show the tips: never finished, and first shown within this visit's window (or not yet). */
export function tipsDue(s: TipsState, now: number, windowMs = TIPS_WINDOW_MS): boolean {
  if (s.done) return false;
  return s.shownAt == null || now - s.shownAt < windowMs;
}

/** The shop card (or its chip) only right after the tips, in the same visit. */
export function shopCardDue(s: TipsState, now: number, windowMs = TIPS_WINDOW_MS): "card" | "chip" | null {
  if (!s.done || s.shownAt == null || now - s.shownAt >= windowMs) return null;
  return s.shop === "open" ? "card" : s.shop === "later" ? "chip" : null;
}

/** The tips this part shows, fixed when they start: turning needs the 3D view, the problem tip a lit finding. */
export function tipPlan(has3d: boolean, hasProblem: boolean): TipStep[] {
  return [...(has3d ? (["tip1"] as TipStep[]) : []), ...(hasProblem ? (["tip2"] as TipStep[]) : []), "tip3"];
}

export function nextTip(plan: TipStep[], step: TipStep): TipStep {
  const i = plan.indexOf(step);
  return i >= 0 && i < plan.length - 1 ? plan[i + 1] : "done";
}

/** "Tip 2 of 3", counting only the tips this part shows. */
export function tipNumber(plan: TipStep[], step: TipStep): { n: number; of: number } {
  return { n: Math.max(1, plan.indexOf(step) + 1), of: plan.length };
}

/* ── N3: your shop from the catalog ────────────────────────────────────── */

const CNC = new Set(["cnc_3axis", "cnc_5axis", "cnc_turning", "wire_edm"]);
/** Printers bounded by their build volume: makers publish no plate load, and the engine
 *  lets the work area decide (costing/makeability.py BUILD_VOLUME_BOUND). */
export const BUILD_VOLUME_BOUND = new Set(["fdm", "sla", "dlp", "sls", "mjf", "dmls", "slm", "ebm", "binder_jetting"]);
export const WEIGHT_BY_BUILD_VOLUME = "weight: no plate load published or declared; build volume governs";

export type CatKind = "cnc" | "print";

export function catKind(process: string): CatKind {
  return CNC.has(process) ? "cnc" : "print";
}

/** What the machine is, in words ("3-axis milling", "Filament printing"). */
export function catWhat(process: string): string {
  const k: Record<string, string> = {
    cnc_3axis: "3-axis milling",
    cnc_5axis: "5-axis milling",
    cnc_turning: "Lathe",
    wire_edm: "Wire EDM",
    fdm: "Filament printing",
    sla: "Resin printing (SLA)",
    dlp: "Resin printing (DLP)",
    sls: "Nylon powder printing (SLS)",
    mjf: "Nylon powder printing (MJF)",
    dmls: "Metal powder printing (DMLS)",
    slm: "Metal powder printing (SLM)",
    ebm: "Electron beam printing (EBM)",
    binder_jetting: "Binder jetting",
    ded: "Metal deposition",
    waam: "Wire-arc printing",
  };
  return k[process] ?? methodName(process);
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The work area as the catalog declares it: "762 × 406 × 508 mm", "Ø254 × 533 mm". */
export function envText(cap: Record<string, unknown> | null | undefined): string | null {
  const c = cap ?? {};
  const swing = num(c.swing_dia);
  const between = num(c.between_centers);
  if (swing != null || between != null) return `Ø${swing != null ? trimNum(swing, 1) : "?"} × ${between != null ? trimNum(between, 1) : "?"} mm`;
  const x = num(c.x);
  const y = num(c.y);
  const z = num(c.z);
  if (x == null || y == null) return null;
  return z != null ? `${trimNum(x, 1)} × ${trimNum(y, 1)} × ${trimNum(z, 1)} mm` : `${trimNum(x, 1)} × ${trimNum(y, 1)} mm`;
}

export function searchText(t: MachineCatalogTemplate): string {
  return `${t.name ?? ""} ${catWhat(t.process)} ${t.process}`.toLowerCase();
}

export interface CatGroup {
  kind: CatKind;
  label: string;
  items: { t: MachineCatalogTemplate; idx: number }[];
}

/** The catalog grouped Machining then Printers, filtered by a query on brand, model or kind. */
export function catalogGroups(templates: MachineCatalogTemplate[], q: string): { groups: CatGroup[]; matched: number; total: number; byKind: Record<CatKind, number> } {
  const needle = q.trim().toLowerCase();
  const words = needle.split(/\s+/).filter(Boolean);
  const hit = (t: MachineCatalogTemplate) => !words.length || words.every((w) => searchText(t).includes(w));
  const groups: CatGroup[] = [];
  const byKind: Record<CatKind, number> = { cnc: 0, print: 0 };
  let matched = 0;
  for (const [kind, label] of [
    ["cnc", "Machining"],
    ["print", "Printers"],
  ] as [CatKind, string][]) {
    const items = templates.map((t, idx) => ({ t, idx })).filter(({ t }) => catKind(t.process) === kind);
    byKind[kind] = items.length;
    const shown = items.filter(({ t }) => hit(t));
    matched += shown.length;
    if (shown.length) groups.push({ kind, label, items: shown });
  }
  return { groups, matched, total: templates.length, byKind };
}

/** One machine picked in the sheet, as typed so far. */
export interface Draft {
  idx: number;
  count: number;
  /** engine material classes (CNC) or the catalog's material names (printers) */
  materials: string[];
  /** printers with no materials in the catalog: what the shop types */
  matsText: string;
  kg: string;
  rate: string;
}

export function draftFrom(t: MachineCatalogTemplate, idx: number): Draft {
  return {
    idx,
    count: Math.max(1, t.count ?? 1),
    materials: [...(t.materials ?? [])],
    matsText: "",
    kg: t.max_workpiece_kg != null ? trimNum(t.max_workpiece_kg, 1).replace(/,/g, "") : "",
    rate: "",
  };
}

export function parseNum(s: string): number | null {
  const v = Number(String(s).replace(/[$,\s]/g, ""));
  return s.trim() && Number.isFinite(v) && v > 0 ? v : null;
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  const x = new Set(a.map((s) => s.toLowerCase()));
  const y = new Set(b.map((s) => s.toLowerCase()));
  return x.size === y.size && [...x].every((s) => y.has(s));
}

export function draftMaterials(t: MachineCatalogTemplate, d: Draft): string[] {
  if (catKind(t.process) === "print" && !(t.materials ?? []).length) {
    return d.matsText.split(",").map((s) => s.trim()).filter(Boolean);
  }
  return d.materials;
}

/** Whether the weight field matters for a yes: CNC and bead deposition yes; build-volume printers no. */
export function weightNeeded(t: MachineCatalogTemplate): boolean {
  return !BUILD_VOLUME_BOUND.has(t.process);
}

/** The fields still missing for a yes: materials, and the heaviest part where it's checked. */
export function missingFor(t: MachineCatalogTemplate, d: Draft): ("materials" | "kg")[] {
  const out: ("materials" | "kg")[] = [];
  if (!draftMaterials(t, d).length) out.push("materials");
  if (weightNeeded(t) && parseNum(d.kg) == null) out.push("kg");
  return out;
}

/**
 * Where a shown value comes from: the maker's published spec (with its page),
 * while the value is exactly the catalog's, else the shop's own (null). Same
 * rule as the server, which re-labels on every save.
 */
export function provenanceOf(t: MachineCatalogTemplate, d: Draft, field: "max_workpiece_kg" | "materials"): FieldProvenance | null {
  const p = t.field_provenance?.[field] ?? null;
  if (!p) return null;
  if (field === "materials") return sameSet(draftMaterials(t, d), t.materials ?? []) && (t.materials ?? []).length ? p : null;
  const kg = parseNum(d.kg);
  return kg != null && t.max_workpiece_kg != null && Math.abs(kg - t.max_workpiece_kg) < 1e-6 ? p : null;
}

/** The body saved for a picked machine: the template as served, with what the shop changed. */
export function machineBody(t: MachineCatalogTemplate, d: Draft): MachineInput {
  const rate = parseNum(d.rate);
  const kg = parseNum(d.kg);
  const mats = draftMaterials(t, d);
  return {
    name: t.name ?? null,
    process: t.process,
    count: Math.max(1, Math.round(d.count)),
    max_workpiece_kg: kg,
    hourly_rate_usd: rate,
    capital_frac: t.capital_frac ?? null,
    materials: mats.length ? mats : null,
    capabilities: t.capabilities ?? null,
    material_thickness_map: t.material_thickness_map ?? null,
    notes: t.notes ?? null,
  };
}

/** The typical machine rate the engine used for a process on this part ($/h), from its own drivers. */
export function typicalRate(cost: CostReport | null | undefined, process: string): number | null {
  const e = (cost?.estimates ?? []).find((x) => x.process === process && !x.environment_excluded);
  return e ? rateOf(e) : null;
}

function driver(e: CostEstimate | null | undefined, name: string): number | null {
  const d = e?.drivers?.find((x) => x.name === name);
  return d && Number.isFinite(d.value) ? d.value : null;
}

function driverProv(e: CostEstimate | null | undefined, name: string): string | null {
  return e?.drivers?.find((x) => x.name === name)?.provenance ?? null;
}

/**
 * machine_cost ÷ cycle_time: the hourly rate a price used for the machine line.
 * The engine reports both to 4 decimals, so the quotient is rounded to whole
 * dollars (to the cent below $10/h) rather than shown as $74.97 for $75.
 */
export function rateOf(e: CostEstimate | null | undefined): number | null {
  const mc = driver(e, "machine_cost");
  const ct = driver(e, "cycle_time");
  if (mc == null || ct == null || ct <= 0) return null;
  const r = mc / ct;
  return r >= 10 ? Math.round(r) : Math.round(r * 100) / 100;
}

/** A machine you own is priced without its paid-off capital share: the in-house rate for an hourly rate. */
export function ownedRate(rate: number, capitalFrac: number): number {
  return Math.round(rate * (1 - capitalFrac) * 100) / 100;
}

/**
 * How the engine priced the machine line on a machine you own, in its own words
 * ("0.0242 hr × $75/hr × (1-0.35) on a machine you own: running cost only …"): the
 * hourly rate it started from and the capital share it took off. Null when the
 * line wasn't priced as owned.
 */
export function ownedBasis(e: CostEstimate | null | undefined): { rate: number; cap: number; yours: boolean } | null {
  const d = e?.drivers?.find((x) => x.name === "machine_cost");
  // Current wording "× (1-0.35) on a machine you own"; saved reports may carry the older
  // "× (1-0.35 capital sunk) OWNED-IN-HOUSE".
  const m = d?.source ? /× \$([\d.]+)\/hr(?: \([^)]*\))? × \(1-([\d.]+)(?: capital sunk\) OWNED-IN-HOUSE|\) on a machine you own)/.exec(d.source) : null;
  if (!d || !m) return null;
  return { rate: Number(m[1]), cap: Number(m[2]), yours: d.provenance === "USER" };
}

/* ── N4: before and now ────────────────────────────────────────────────── */

export interface AhaRow {
  k: string;
  b: string;
  bs: string;
  a: string;
  as: string;
  tone: "ok" | "plain";
}

export interface AhaMachine {
  id: string;
  name: string;
  sub: string;
  tone: MachineView["tone"];
  verdict: string;
  cost: string;
  on: boolean;
}

export interface AhaModel {
  /** "before" ran on machines too (a machine added later), so it isn't "no machines" */
  beforeOn: boolean;
  /** the machine of yours that can make it, cheapest first */
  best: { name: string; process: string; price: number | null } | null;
  lead: { a: string; b: string; tone: "ok" | "no" | "plain" };
  sub: string;
  rows: AhaRow[];
  machines: AhaMachine[];
  foot: string;
  ticket: { k: string; big: string; s: string } | null;
  labor: string | null;
  /** how many machines the re-check ran against */
  n: number;
}

function laborRate(cost: CostReport | null): { v: number; yours: boolean } | null {
  const a = cost?.assumptions?.find((x) => x.name === "labor_rate");
  return a && Number.isFinite(a.value) ? { v: a.value, yours: a.provenance !== "DEFAULT" } : null;
}

function rateWord(v: number | null): string {
  return v == null ? "" : `$${trimNum(v, 2)}/h`;
}

function whereMade(m: Method | null, machine: string | null): string {
  if (!m) return "Not priced";
  return machine ? `your ${machine}` : `${m.name}, outside`;
}

/**
 * The before/now answer once a part is re-checked against your machines: the
 * same file and engine, before (no machines) and now (your machines).
 */
export function ahaModel(input: {
  before: CostReport;
  now: CostReport;
  machines: OwnedMachine[];
  validation: ValidationResult | null;
  q: number;
  showBefore: boolean;
}): AhaModel {
  const { before, now, machines, validation, q } = input;
  const bm = buildMethods({ validation, cost: before, machines: [] });
  const nm = buildMethods({ validation, cost: now, machines });
  const bbox = validation?.geometry.bounding_box_mm ?? now.geometry?.bbox_mm ?? null;
  const views = machineViews(machines, nm, now, q, bbox);
  const can = views.filter((v) => v.tone === "ok").sort((a, b) => (a.cost ?? Infinity) - (b.cost ?? Infinity));
  const best = can[0] ?? null;
  const qw = qtyWord(q);
  const mat = materialWord(now.material_class);
  const bestMethod = best ? nm.find((m) => m.code === best.process) ?? null : null;
  const beforeMethod = best ? bm.find((m) => m.code === best.process) ?? null : null;
  const nowE = bestMethod?.prices.get(q) ?? null;
  const beforeE = beforeMethod?.prices.get(q) ?? null;
  const cheapB = cheapestAt(bm, q, isWorkable);
  const cheapN = cheapestAt(nm, q, isWorkable);
  const cheapNMachine = cheapN ? can.find((v) => v.process === cheapN.code)?.name ?? null : null;
  const labB = laborRate(before);
  const labN = laborRate(now);
  const fitNow = best ? readVerification(now)?.per_route?.[best.process] ?? null : null;
  const kgMax = best ? machines.find((m) => m.id === best.id)?.max_workpiece_kg ?? null : null;
  // "Before" may itself have run on machines (a machine added later): read where it was made then.
  const vb = readVerification(before);
  const beforeOn = ranOnMachines(before);
  const inHouse = (v: string | null | undefined) => v === "makeable_in_house" || v === "makeable_with_secondary_op";
  const beforeMachineFor = (code: string | null | undefined): string | null => {
    if (!beforeOn || !code) return null;
    const r = vb?.per_route?.[code];
    return r && inHouse(r.verdict) ? r.best_machine ?? null : null;
  };
  const beforeBest = best ? beforeMachineFor(best.process) : null;
  const cheapBMachine = cheapB ? beforeMachineFor(cheapB.code) : null;

  // Lead and sub.
  let lead: AhaModel["lead"];
  let sub: string;
  if (input.showBefore && beforeBest) {
    lead = { a: "Made on your ", b: beforeBest, tone: "ok" };
    sub = beforeE ? `${money(beforeE.unit_cost_usd)} each at ${qw}, in-house, before this change.` : "In-house, before this change.";
  } else if (input.showBefore && beforeOn) {
    lead = { a: "In-house ", b: "no machine fit", tone: "no" };
    sub = "Before this change, none of your machines cleared every check.";
  } else if (input.showBefore) {
    lead = { a: "In-house ", b: "not checked", tone: "plain" };
    const m = beforeMethod ?? cheapB;
    sub = m && priceAt(m, q) != null ? `No machines added. ${m.name} at a typical shop: ${money(priceAt(m, q))} each at ${qw}.` : "No machines added, so in-house wasn’t checked.";
  } else if (best) {
    lead = { a: "You can make it on your ", b: best.name, tone: "ok" };
    const price = best.cost;
    const material = nowE?.material ?? mat;
    const cheaper = cheapN && cheapN.code !== best.process && price != null && (priceAt(cheapN, q) ?? Infinity) < price ? cheapN : null;
    sub = price != null ? `${money(price)} each at ${qw}, in-house in ${material}.${cheaper ? ` Outside, ${cheaper.name.toLowerCase()} is ${money(priceAt(cheaper, q))}.` : " The cheapest way as drawn."}` : `Fits and clears every check. Not priced in ${mat} at ${qw}.`;
  } else if (views.length) {
    const warn = views.find((v) => v.tone === "warn");
    lead = { a: "None of your machines can make it ", b: warn ? "yet" : "as drawn", tone: "no" };
    sub = warn ? `${warn.name}: ${warn.why}` : views.map((v) => `${v.name}: ${v.why}`).slice(0, 2).join(" ");
  } else {
    lead = { a: "In-house ", b: "not checked", tone: "plain" };
    sub = "No machines added, so in-house wasn’t checked.";
  }

  // What changed.
  const rows: AhaRow[] = [];
  rows.push({
    k: "Where it’s made",
    b: beforeBest ?? "Outside",
    bs: beforeBest ? "in-house" : beforeOn ? "none of your machines fit" : "in-house not checked",
    a: best ? best.name : "Outside",
    as: best ? ["in-house", kgMax != null ? `fits, ${trimNum(kgMax, 0)} kg max` : fitNow?.notes?.includes(WEIGHT_BY_BUILD_VOLUME) ? "fits the build volume" : "fits"].join(" · ") : views.length ? `none of your ${views.length} clears every check` : "no machines",
    tone: best ? "ok" : "plain",
  });
  if (best && bestMethod) {
    const rb = rateOf(beforeE);
    const ownB = ownedBasis(beforeE);
    const own = ownedBasis(nowE);
    const yours = driverProv(nowE, "machine_cost") === "USER";
    rows.push({ k: `${bestMethod.name}, each`, b: money(beforeE?.unit_cost_usd), bs: beforeBest ? `your ${beforeBest}` : "typical shop", a: money(nowE?.unit_cost_usd), as: `your ${best.name}`, tone: "plain" });
    rows.push({
      k: "Machine time",
      b: money(driver(beforeE, "machine_cost")),
      bs: ownB ? `${ownB.yours ? "your" : "typical"} ${rateWord(ownB.rate)}, owned` : rb != null ? `typical ${rateWord(rb)}` : "typical",
      a: money(driver(nowE, "machine_cost")),
      as: own ? `${own.yours || yours ? "your" : "typical"} ${rateWord(own.rate)}, owned` : yours ? `your ${rateWord(fitNow?.machine_rate_usd ?? null) || "rate"}` : `typical ${rateWord(rateOf(nowE))}`,
      tone: "plain",
    });
    rows.push({
      k: "Labor",
      b: money(driver(beforeE, "labor_cost")),
      bs: labB ? `${labB.yours ? "your" : "typical"} ${rateWord(labB.v)}` : "",
      a: money(driver(nowE, "labor_cost")),
      as: labN?.yours ? `your ${rateWord(labN.v)}` : "still typical",
      tone: "plain",
    });
  }
  rows.push({
    k: "Cheapest as drawn",
    b: cheapB ? money(priceAt(cheapB, q)) : "—",
    bs: cheapB ? whereMade(cheapB, cheapBMachine) : "not priced",
    a: cheapN ? money(priceAt(cheapN, q)) : "—",
    as: cheapN ? whereMade(cheapN, cheapNMachine) : "not priced",
    tone: cheapN && cheapNMachine ? "ok" : "plain",
  });

  const machinesOut: AhaMachine[] = views.map((v) => ({
    id: v.id,
    name: v.name,
    sub: v.tone === "ok" ? `${v.sub} · ${v.checks || "clears every check"}` : `${v.sub ? `${v.sub} · ` : ""}${v.why}`,
    tone: v.tone,
    verdict: v.verdict,
    cost: v.cost != null ? money(v.cost) : "—",
    on: best?.id === v.id,
  }));

  // The foot says exactly what moved the price.
  let foot: string;
  if (input.showBefore) foot = beforeOn ? "The answer before this change, same file and engine. Lead times are a queue model, not a schedule." : "Typical machines and rates, fully loaded. Lead times are a queue model, not a schedule.";
  else if (best && nowE && beforeE) {
    const delta = Math.round((beforeE.unit_cost_usd - nowE.unit_cost_usd) * 100) / 100;
    const own = ownedBasis(nowE);
    const yours = own?.yours || driverProv(nowE, "machine_cost") === "USER";
    const band = nowE.est_error_band_pct ? ` ±${trimNum(nowE.est_error_band_pct, 0)}%, not yet checked against your jobs.` : "";
    const rest = `Labor, setup and programming are ${labN?.yours ? "from your rate card" : "typical"}.`;
    const also = can.filter((v) => v.id !== best.id && v.name !== beforeBest);
    const alsoText = also.length ? ` ${also.map((v) => `Your ${v.name} can make it too${v.cost != null ? `, at ${money(v.cost)}` : ""}.`).join(" ")}` : "";
    if (delta === 0 && beforeBest === best.name) foot = `Same machine and price as before.${alsoText} ${rest}${band}`;
    else if (delta === 0) foot = `Where it’s made changed, not the price.${alsoText} ${rest}${band}`;
    else if (own)
      foot = `Only the machine line moved, by ${money(Math.abs(delta))}: a machine you own is priced without its paid-off capital share, ${Math.round(own.cap * 100)}% of ${yours ? "your" : "the typical"} ${rateWord(own.rate)} (${rateWord(ownedRate(own.rate, own.cap))} in-house).${yours ? "" : " Add your rate to price it at yours."} ${rest}${band}`;
    else foot = `Only the machine line is yours, so the price moved ${money(Math.abs(delta))}. ${rest}${band}`;
  } else if (best) foot = "Fits and clears every check the engine ran.";
  else foot = "The fit checks work area, weight and materials for each machine, from this re-check.";

  let ticket: AhaModel["ticket"] = null;
  if (input.showBefore && beforeMethod) {
    const e = beforeMethod.prices.get(q);
    if (e) ticket = { k: `${beforeMethod.name} · ${beforeBest ? `${beforeBest} · in-house` : "typical shop"} · ${qw} parts`, big: `${money(e.unit_cost_usd)} each`, s: `${beforeBest ? "In-house" : "Outside"} · ${days(e.lead_time?.low_days, e.lead_time?.high_days)} · queue model` };
  } else if (best && nowE) {
    const lo = nowE.confidence?.low_usd ?? nowE.unit_cost_usd * (1 - nowE.est_error_band_pct / 100);
    const hi = nowE.confidence?.high_usd ?? nowE.unit_cost_usd * (1 + nowE.est_error_band_pct / 100);
    ticket = { k: `${best.name} · in-house · ${qw} parts`, big: `${money(nowE.unit_cost_usd)} each`, s: `Could be ${money(lo)}–${money(hi)} · ${days(nowE.lead_time?.low_days, nowE.lead_time?.high_days)} · queue model` };
  }

  const labCost = driver(nowE, "labor_cost");
  const labor = nowE && labCost != null && labN ? `${money(labCost)} of the ${money(nowE.unit_cost_usd)} at ${qw} is labor at ${labN.yours ? "your" : "a typical"} ${rateWord(labN.v)}. Your labor rate changes every in-house price.` : null;

  return {
    beforeOn,
    best: best ? { name: best.name, process: best.process, price: best.cost } : null,
    lead,
    sub,
    rows,
    machines: machinesOut,
    foot,
    ticket,
    labor,
    n: views.length,
  };
}

/** Did this report run against declared machines? (a "before" has none) */
export function ranOnMachines(cost: CostReport | null | undefined): boolean {
  const v = readVerification(cost);
  return !!v && (v.inventory_declared === true || Object.values(v.per_route ?? {}).some((r) => (r.machines_evaluated ?? 0) > 0));
}

/* ── N5: Home before the first part, and just after ────────────────────── */

export type HomeMode = "loading" | "first" | "back" | "normal";

/** Home's first-run mode: before any part, the three ways; with a few parts and setup open, pick up where you left off. */
export function homeMode(i: { records: number | null; parts: number | null; dismissed: boolean; maxParts?: number }): HomeMode {
  if (i.records == null) return "loading";
  if (i.records === 0) return "first";
  if (i.dismissed) return "normal";
  if (i.parts == null) return "loading";
  return i.parts <= (i.maxParts ?? 3) ? "back" : "normal";
}

export type StepTone = "done" | "part" | "warn" | "unk" | "lock" | "bad";

export interface FirstStep {
  key: "check" | "machines" | "rates" | "programs" | "actuals" | "team";
  title: string;
  detail: string;
  chip: string;
  tone: StepTone;
  go?: { label: string; href: string };
  next?: boolean;
}

export interface FirstStepsInput {
  records: number | null;
  parts: number | null;
  /** the newest part's file and whether it was priced on machines */
  part: { file: string; material: string | null; onMachines: boolean; href: string } | null;
  machines: { name: string; count: number; hourly_rate_usd: number | null }[] | null;
  rates: { using_governed: boolean; source: string } | null;
  yours: { yours: number; total: number } | null;
  labor: number | null;
  programs: { programs: number; notIn: number | null } | null;
  actuals: number | null;
  members: number | null;
  failed: Partial<Record<"records" | "machines" | "rates" | "programs" | "actuals" | "members", boolean>>;
  hrefs: { check: string; shop: string; rates: string; programs: string; actuals: string; team: string; addMachines: string };
}

function cardName(r: { using_governed: boolean; source: string }): string {
  if (r.using_governed) return "Your rate card";
  const m = /^default_rate_card_(v\d+)$/.exec(r.source);
  return m ? `Default rate card ${m[1]}` : r.source.replace(/_/g, " ");
}

function pl(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

/** The six setup steps (N5's right sheet), in the board's words, from the org's own data. */
export function firstSteps(i: FirstStepsInput): FirstStep[] {
  const f = i.failed;
  const has = (i.records ?? 0) > 0;
  const steps: FirstStep[] = [];
  if (i.records == null) steps.push({ key: "check", title: "Check your first part", detail: f.records ? "Records didn’t load" : "Checking records", chip: "Unknown", tone: f.records ? "bad" : "unk" });
  else if (has) steps.push({ key: "check", title: "Check your first part", detail: i.part ? [i.part.file, i.part.material, pl(i.records, "record")].filter(Boolean).join(" · ") : pl(i.records, "record"), chip: "Done", tone: "done" });
  else steps.push({ key: "check", title: "Check your first part", detail: "Your file, the sample or a simple part from Design Studio", chip: "To do", tone: "warn" });

  const nm = i.machines ? i.machines.reduce((n, m) => n + (m.count ?? 1), 0) : null;
  if (nm == null) steps.push({ key: "machines", title: "Add your machines", detail: f.machines ? "Machines didn’t load" : "Checking machines", chip: "Unknown", tone: f.machines ? "bad" : "unk" });
  else if (nm > 0) {
    const names = i.machines!.map((m) => m.name).filter(Boolean);
    steps.push({ key: "machines", title: "Add your machines", detail: `${pl(nm, "machine")} · ${names.slice(0, 3).join(", ")}${names.length > 3 ? ` and ${names.length - 3} more` : ""}`, chip: "Done", tone: "done", go: { label: "Open machines", href: i.hrefs.shop } });
  } else if (!has)
    // me-19: Your shop takes machines before any check, so this step is never locked: add them first and the first answer names the machine.
    steps.push({ key: "machines", title: "Add your machines", detail: "Before your first check, or after · answers then name the machine that can make it", chip: "To do", tone: "warn", go: { label: "Add machines", href: i.hrefs.addMachines } });
  else steps.push({ key: "machines", title: "Add your machines", detail: i.part && !i.part.onMachines ? `Not added yet · ${i.part.file} was priced at typical shops only` : "Not added yet · answers use typical machines", chip: "To do", tone: "warn", go: { label: "Add machines", href: i.hrefs.addMachines } });

  if (!i.rates) steps.push({ key: "rates", title: "Set your rates", detail: f.rates ? "Rates didn’t load" : "Checking rates", chip: "Unknown", tone: f.rates ? "bad" : "unk" });
  else {
    const card = cardName(i.rates);
    const rated = (i.machines ?? []).filter((m) => m.hourly_rate_usd != null).length;
    const lab = i.labor != null ? ` ($${trimNum(i.labor, 2)}/h)` : "";
    if (i.rates.using_governed) steps.push({ key: "rates", title: "Set your rates", detail: `${card}${i.yours ? ` · ${i.yours.yours} of ${i.yours.total} cost inputs yours` : ""}`, chip: "Done", tone: "done", go: { label: "Open rates", href: i.hrefs.rates } });
    else if (rated > 0) steps.push({ key: "rates", title: "Set your rates", detail: `${pl(rated, "machine rate")} yours · labor${lab}, setup and programming typical`, chip: "Partly", tone: "part", go: { label: "Set labor rate", href: i.hrefs.rates } });
    else steps.push({ key: "rates", title: "Set your rates", detail: `${card} · every input typical`, chip: "Typical", tone: "unk", go: { label: "Open rates", href: i.hrefs.rates } });
  }

  if (!has) steps.push({ key: "programs", title: "Programs and yearly volume", detail: "After your first checked part", chip: "Locked", tone: "lock" });
  else if (!i.programs) steps.push({ key: "programs", title: "Programs and yearly volume", detail: f.programs ? "Programs didn’t load" : "Checking programs", chip: "Unknown", tone: f.programs ? "bad" : "unk" });
  else
    steps.push({
      key: "programs",
      title: "Programs and yearly volume",
      detail: [pl(i.programs.programs, "program"), i.programs.notIn != null ? `${pl(i.programs.notIn, "part")} not in a program` : null].filter(Boolean).join(" · "),
      chip: i.programs.programs > 0 ? "Done" : "Optional",
      tone: i.programs.programs > 0 ? "done" : "unk",
      go: { label: "Open programs", href: i.hrefs.programs },
    });

  if (!has) steps.push({ key: "actuals", title: "Actual costs", detail: "After your first checked part", chip: "Locked", tone: "lock" });
  else if (i.actuals == null) steps.push({ key: "actuals", title: "Actual costs", detail: f.actuals ? "Actual costs didn’t load" : "Checking actual costs", chip: "Unknown", tone: f.actuals ? "bad" : "unk" });
  else steps.push({ key: "actuals", title: "Actual costs", detail: `${i.actuals} logged · a process’s range turns measured after 3 held-out jobs`, chip: i.actuals >= 8 ? "Done" : i.actuals > 0 ? "Partly" : "Optional", tone: i.actuals >= 8 ? "done" : i.actuals > 0 ? "part" : "unk", go: { label: "Add real costs", href: i.hrefs.actuals } });

  if (i.members == null) steps.push({ key: "team", title: "Team", detail: f.members ? "Team didn’t load" : "Checking team", chip: "Optional", tone: "unk", go: { label: "Invite", href: i.hrefs.team } });
  else steps.push({ key: "team", title: "Team", detail: i.members <= 1 ? `1 member · you${nm ? " · invited people get these machines and rates" : ""}` : `${pl(i.members, "member")}`, chip: i.members > 1 ? "Done" : "Optional", tone: i.members > 1 ? "done" : "unk", go: { label: "Invite", href: i.hrefs.team } });

  // The first step still to do with an action is "next" (the strong button).
  if (!has) steps[0].next = true;
  else {
    const n = steps.find((s) => s.go && (s.tone === "warn" || s.tone === "part")) ?? steps.find((s) => s.go && s.tone !== "done" && s.tone !== "lock" && s.tone !== "bad");
    if (n) n.next = true;
  }
  return steps;
}

export interface ResumeCard {
  k: string;
  title: string;
  text: string;
  meta: string;
  go: { label: string; href: string };
  alt: { label: string; href: string };
}

/** "Pick up where you left off": the next thing that makes the answers about this shop. */
export function resumeCard(i: {
  file: string;
  partHref: string;
  cost: CostReport | null;
  machines: number | null;
  onMachines: boolean;
  /** Whether a machine was added after this check: true, false, or null when it isn't known. */
  addedAfter?: boolean | null;
  hrefs: { addMachines: string; rates: string; recheck: string };
}): ResumeCard | null {
  const cost = i.cost;
  // me-07: with machines declared, nothing is said about the check until its record has loaded (no flash of a wrong card).
  if (!cost && (i.machines ?? 0) > 0) return null;
  const qs = quantitiesOf(cost);
  const q = qs.length ? defaultQty(qs) : null;
  if (i.machines == null) return null;
  const methods = cost ? buildMethods({ validation: null, cost, machines: [] }) : [];
  const cheap = q != null ? cheapestAt(methods, q) : null;
  const cheapText = cheap && q != null ? `cheapest at ${qtyWord(q)} is ${money(priceAt(cheap, q))} by ${cheap.name.toLowerCase()}, outside` : null;
  if (i.machines === 0) {
    return {
      k: "Next: add your machines",
      title: `${i.file} hasn’t been checked against your machines`,
      text: `${cheapText ? `It was priced at typical shops: ${cheapText}. ` : "It was priced at typical shops. "}Add what you have and it re-checks.`,
      meta: "About 2 minutes · re-checking the same file doesn’t use a check",
      go: { label: "Add your machines", href: i.hrefs.addMachines },
      alt: { label: "Open the part", href: i.partHref },
    };
  }
  if (!i.onMachines) {
    // "Checked before your machines were added" only when one was (me-07); otherwise the true thing: it wasn't checked on them.
    return {
      k: "Next: re-check on your machines",
      title: i.addedAfter ? `${i.file} was checked before your machines were added` : `${i.file} wasn’t checked against your machines`,
      text: "Re-check it and the answer names the machine that can make it, at your rates.",
      meta: "Re-checking the same file doesn’t use a check",
      go: { label: "Re-check", href: i.hrefs.recheck },
      alt: { label: "Open the part", href: i.partHref },
    };
  }
  const v = readVerification(cost);
  const best = v?.best_machine ?? null;
  const m = best && cost ? Object.entries(v?.per_route ?? {}).find(([, r]) => r.best_machine === best && (r.verdict === "makeable_in_house" || r.verdict === "makeable_with_secondary_op")) : null;
  const e = m && q != null ? (cost?.estimates ?? []).filter((x) => x.process === m[0] && x.quantity === q && !x.environment_excluded).sort((a, b) => a.unit_cost_usd - b.unit_cost_usd)[0] ?? null : null;
  const lab = driver(e, "labor_cost");
  const labRate = laborRate(cost);
  return {
    k: "Next: your labor rate",
    title: best && e ? `${i.file}: on your ${best}, ${money(e.unit_cost_usd)} each at ${qtyWord(q!)}` : `${i.file}: checked on your machines`,
    text: e && lab != null && labRate ? `${money(lab)} of that is labor at ${labRate.yours ? "your" : "a typical"} $${trimNum(labRate.v, 2)}/h. Your labor rate changes every in-house price.` : "Your labor rate changes every in-house price.",
    meta: "Rates › Labor · one rate for the whole shop",
    go: { label: "Set labor rate", href: i.hrefs.rates },
    alt: { label: "Open the part", href: i.partHref },
  };
}

/* ── N5: what a free account gets, said once ──────────────────────────── */

/**
 * The own-part card's words: what one check uses (and that the phone check
 * comes first, when it does), and the catalog run's allowance next to it, so
 * "15 free checks" and "50 free catalog parts" read as two separate things.
 */
export function allowanceLines(i: {
  checksLeft: number | null;
  plan: string | null;
  phoneFirst: boolean;
  catalog: { cap: number | null; left: number | null; started: boolean } | null;
}): { drop: string; uses: string; batch: string | null } {
  const kind = i.plan === "pro" ? "Pro" : "free";
  const uses = (i.checksLeft == null ? "Uses 1 check" : `Uses 1 of ${i.checksLeft} ${kind} ${i.checksLeft === 1 ? "check" : "checks"}`) + (i.phoneFirst ? " · phone check first" : "");
  const drop = i.phoneFirst
    ? "Drop a part here. Verify your phone first (we text you a code once), then it checks and opens on its own page."
    : "Drop a part here. It checks right away and opens on its own page.";
  const c = i.catalog;
  let batch: string | null = null;
  if (c?.cap != null) {
    const yours = i.checksLeft == null ? "your checks" : `your ${i.checksLeft} ${kind} ${i.checksLeft === 1 ? "check" : "checks"}`;
    batch = c.started && c.left != null
      ? `Many parts at once: ${c.left} of ${c.cap} free catalog parts left, separate from ${yours}`
      : `Many parts at once: up to ${c.cap} free, separate from ${yours}`;
  }
  return { drop, uses, batch };
}
