/**
 * Workbench derivations (boards F3 and F5 to F9). Every number here is read off
 * the engine's own report (`POST /validate/cost` or a saved cost decision) and
 * the DFM analysis (`POST /validate` or a saved analysis). The quantity slider
 * reads between costed quantities with the app's breakeven curves and says it
 * is approximate; nothing else is estimated here, and a missing field stays
 * missing ("—"), never zero.
 *
 * Pure and import-light (relative imports with extensions) so it unit-tests
 * under `node --test`.
 */
import type {
  CostAssumption,
  CostDecisionSummary,
  CostDriver,
  CostEstimate,
  CostOptions,
  CostReport,
  FeatureInfo,
  Issue,
  ShopProfileInfo,
  ValidationResult,
} from "@/lib/api";
import { deriveBreakeven, recommendAt, unitCostAt, type Breakeven, type ProcessCurve } from "../../../lib/breakeven.ts";
import { flattenIssues, issueProcesses } from "../../../lib/dfm-scope.ts";
import { parseCalibration } from "../../../lib/cost-views.ts";
import {
  assumptionName,
  assumptionValue,
  findingTitle,
  inSentence,
  lineName,
  materialName,
  methodName,
  money,
  qtyListText,
  qtyText,
} from "./words.ts";

/* ------------------------------------------------------------------ */
/*  Costing options (F9 sheet, F5 Adjust inputs)                       */
/* ------------------------------------------------------------------ */

export interface FormDraft {
  qty: string;
  mat: string;
  reg: string;
  units: "mm" | "inch";
  cx: string;
  cav: string;
}

export const DEFAULT_FORM: FormDraft = { qty: "50, 5000", mat: "polymer", reg: "auto", units: "mm", cx: "moderate", cav: "1" };

export const QTY_RULE = "Use 1 to 6 whole numbers from 1 to 10,000,000, separated by commas.";
export const CAV_RULE = "Enter a whole number, 1 or more.";

export function qtyParts(raw: string): string[] {
  return String(raw).split(",").map((s) => s.trim()).filter(Boolean);
}

/** Same rule as the server: 1 to 6 whole numbers, each 1 to 10,000,000. */
export function qtyProblem(raw: string): string | null {
  const parts = qtyParts(raw);
  if (parts.length < 1 || parts.length > 6) return QTY_RULE;
  if (parts.some((s) => !/^\d+$/.test(s) || Number(s) < 1 || Number(s) > 10_000_000)) return QTY_RULE;
  return null;
}

export function cavProblem(raw: string): string | null {
  const s = String(raw).trim();
  return /^\d+$/.test(s) && Number(s) >= 1 && Number.isSafeInteger(Number(s)) ? null : CAV_RULE;
}

export function formProblem(form: FormDraft): string | null {
  return qtyProblem(form.qty) ?? cavProblem(form.cav);
}

/** Draft → request options. Keeps the bound shop and overrides from `base`. */
export function formToOptions(form: FormDraft, base?: Pick<CostOptions, "shop" | "overrides"> | null): CostOptions {
  return {
    qty: qtyParts(form.qty).map((s) => String(Number(s))).join(","),
    region: form.reg,
    cavities: Math.max(1, Math.round(Number(form.cav) || 1)),
    complexity: form.cx,
    material_class: form.mat,
    units: form.units,
    shop: base?.shop ?? null,
    overrides: { ...(base?.overrides ?? {}) },
  };
}

export function optionsToForm(opts: CostOptions): FormDraft {
  return {
    qty: qtyParts(opts.qty).join(", "),
    mat: opts.material_class,
    reg: opts.region || "auto",
    units: opts.units,
    cx: opts.complexity,
    cav: String(opts.cavities),
  };
}

export function sameForm(a: FormDraft, b: FormDraft): boolean {
  return (
    qtyParts(a.qty).map(Number).join(",") === qtyParts(b.qty).map(Number).join(",") &&
    a.mat === b.mat && a.reg === b.reg && a.units === b.units && a.cx === b.cx && String(Number(a.cav)) === String(Number(b.cav))
  );
}

/**
 * The inputs behind a saved report, read off the report itself: its quantities,
 * material class, the complexity and cavity assumptions, the bound shop (from
 * the calibration note) and the region multiplier's own source line. Overrides
 * can't be recovered from a saved report, so they start empty.
 */
export function optionsFromReport(report: CostReport, shops: readonly ShopProfileInfo[], units: "mm" | "inch" = "mm"): CostOptions {
  const asm = new Map((report.assumptions ?? []).map((a) => [a.name, a] as const));
  const cx = asm.get("complexity")?.unit;
  const cav = asm.get("n_cavities")?.value;
  const cal = parseCalibration(report);
  const shop = cal.shopName ? shops.find((s) => s.name === cal.shopName)?.id ?? null : null;
  const regionSrc = asm.get("region_labor")?.source ?? "";
  const region = /region ([A-Z]{2})\b/.exec(regionSrc)?.[1] ?? null;
  return {
    qty: (report.quantities?.length ? report.quantities : [50, 5000]).join(","),
    region: shop || !region || region === "US" ? "auto" : region,
    cavities: cav && cav >= 1 ? Math.round(cav) : 1,
    complexity: cx && ["simple", "moderate", "complex", "very_complex"].includes(cx) ? cx : "moderate",
    material_class: report.material_class || "polymer",
    units,
    shop,
    overrides: {},
  };
}

/* ------------------------------------------------------------------ */
/*  Quantity scale (F5 slider, log 1 to a whole decade)                */
/* ------------------------------------------------------------------ */

export function scaleMax(be: Breakeven | null): number {
  const top = Math.max(10, be?.qtyMax ?? 10000);
  return 10 ** Math.ceil(Math.log10(top) - 1e-9);
}

/** Slider position 0..1000 → quantity on a log scale from 1 to `max`. */
export function posToQ(pos: number, max: number): number {
  const p = Math.min(1000, Math.max(0, pos));
  return Math.max(1, Math.round(Math.exp((Math.log(max) * p) / 1000)));
}

export function qToPos(q: number, max: number): number {
  const v = Math.min(max, Math.max(1, q));
  return Math.round((Math.log(v) / Math.log(max)) * 1000);
}

export function decadeTicks(max: number): number[] {
  const out: number[] = [];
  for (let v = 1; v <= max * 1.0001; v *= 10) out.push(Math.round(v));
  return out;
}

/** The quantity the Decision opens on: the engine's crossover, else the largest costed quantity. */
export function defaultQty(report: CostReport): number {
  const cross = report.decision?.crossover_qty;
  if (cross && Number.isFinite(cross)) return Math.round(cross);
  const qs = report.quantities?.length ? report.quantities : [1];
  return Math.max(...qs);
}

/* ------------------------------------------------------------------ */
/*  The decision at a quantity (F5)                                    */
/* ------------------------------------------------------------------ */

export function costedQtys(report: CostReport): number[] {
  return [...new Set(report.estimates.filter((e) => !e.environment_excluded).map((e) => e.quantity))].sort((a, b) => a - b);
}

/** The costed quantity nearest `q` on a log scale. */
export function nearestQty(qs: readonly number[], q: number): number | null {
  if (!qs.length) return null;
  return qs.reduce((best, x) => (Math.abs(Math.log(x) - Math.log(q)) < Math.abs(Math.log(best) - Math.log(q)) ? x : best), qs[0]);
}

export function estimateFor(report: CostReport, process: string, qty: number, material?: string | null): CostEstimate | null {
  const rows = report.estimates.filter((e) => e.process === process && !e.environment_excluded && (!material || e.material === material));
  const exact = rows.filter((e) => e.quantity === qty);
  const pool = exact.length ? exact : rows;
  if (!pool.length) return null;
  const near = nearestQty([...new Set(pool.map((e) => e.quantity))], qty);
  const atNear = pool.filter((e) => e.quantity === near);
  return atNear.reduce((a, b) => (b.unit_cost_usd < a.unit_cost_usd ? b : a), atNear[0]);
}

export function bandPct(e: CostEstimate | null | undefined): number | null {
  if (!e) return null;
  const v = e.confidence?.half_width_pct ?? e.est_error_band_pct;
  return v == null || !Number.isFinite(v) ? null : Math.round(v * 10) / 10;
}

export interface CostAtRow {
  process: string;
  name: string;
  material: string;
  unit: number;
  ready: boolean;
  pick: boolean;
  tag: "Pick" | "Ready" | "Redesign";
  chip: "c-ok" | "c-unk" | "c-warn";
}

export function costsAt(be: Breakeven, q: number): CostAtRow[] {
  const rec = recommendAt(be, q);
  return be.curves
    .map((c) => ({ c, u: unitCostAt(c, q) }))
    .filter((x) => Number.isFinite(x.u))
    .sort((a, b) => a.u - b.u)
    .map(({ c, u }) => {
      const pick = !!rec && rec.curve === c;
      return {
        process: c.process,
        name: methodName(c.process),
        material: c.material,
        unit: u,
        ready: c.dfmReady,
        pick,
        tag: pick ? "Pick" : c.dfmReady ? "Ready" : "Redesign",
        chip: pick ? (c.dfmReady ? "c-ok" : "c-warn") : c.dfmReady ? "c-unk" : "c-warn",
      };
    });
}

export interface DecisionAt {
  curve: ProcessCurve;
  name: string;
  ready: boolean;
  unit: number;
  exact: boolean;
  estimate: CostEstimate | null;
  band: number | null;
  lo: number | null;
  hi: number | null;
  leadLo: number | null;
  leadHi: number | null;
}

export function decisionAt(report: CostReport, be: Breakeven, q: number): DecisionAt | null {
  const rec = recommendAt(be, q);
  if (!rec) return null;
  const qs = costedQtys(report);
  const near = nearestQty(qs, q) ?? q;
  const estimate = estimateFor(report, rec.curve.process, near, rec.curve.material);
  const exact = qs.includes(q) && estimate?.quantity === q;
  const band = bandPct(estimate);
  const conf = exact ? estimate?.confidence : null;
  const lo = conf ? conf.low_usd : band != null ? rec.unitCost * (1 - band / 100) : null;
  const hi = conf ? conf.high_usd : band != null ? rec.unitCost * (1 + band / 100) : null;
  return {
    curve: rec.curve,
    name: methodName(rec.curve.process),
    ready: rec.dfmReady,
    unit: rec.unitCost,
    exact,
    estimate,
    band,
    lo,
    hi,
    leadLo: estimate?.lead_time?.low_days ?? null,
    leadHi: estimate?.lead_time?.high_days ?? null,
  };
}

export function crossText(report: CostReport): string {
  const x = report.decision?.crossover_qty;
  return x && Number.isFinite(x) ? `Tooling pays off near ${qtyText(x)}` : "No tooling crossover";
}

/** "114852 sidewall faces (100.0% of sidewall area) below 5.0° draft for forging." → plain words. */
export function blockerSentence(text: string | null | undefined): string {
  const t = (text ?? "").trim();
  const m = /([0-9]+) sidewall faces \(([0-9.]+)% of sidewall area\) below ([0-9.]+)° draft/.exec(t);
  if (!m) return t;
  const share = Number(m[2]) >= 100 ? "Every sidewall" : `${m[2]}% of the sidewall area`;
  return `${share} is under ${Number(m[3])}° draft (${Number(m[1]).toLocaleString("en-US")} faces).`;
}

export function redesignNote(report: CostReport): { process: string; title: string; text: string } | null {
  const dec = report.decision;
  if (!dec?.tooling_process || dec.tooling_dfm_ready !== false) return null;
  const est = report.estimates.find((e) => e.process === dec.tooling_process && !e.environment_excluded && e.dfm_blockers?.length);
  const blocker = est?.dfm_blockers?.[0] ?? report.engine_feasibility.find((f) => f.process === dec.tooling_process)?.blockers?.[0];
  return {
    process: dec.tooling_process,
    title: `${methodName(dec.tooling_process)} needs a design change first`,
    text: `${blocker ? blockerSentence(blocker) + " " : ""}Its cost is for a redesigned part, not a quote.`,
  };
}

/** The engine's crossover reading, in the Workbench's method names. */
export function crossoverSentence(report: CostReport): string {
  const dec = report.decision;
  if (!dec) return "";
  const procs = [...new Set(Object.values(dec.recommendation ?? {}).map((r) => r.process))];
  const head = procs.length === 1
    ? `${methodName(procs[0])} is the lowest-cost no-tooling route at the costed quantities.`
    : "The lowest-cost no-tooling route varies by quantity.";
  if (dec.crossover_qty == null || !dec.tooling_process) return `${head} No tooling crossover is identified.`;
  return `${head} ${methodName(dec.tooling_process)} pays off near ${qtyText(dec.crossover_qty)}${dec.tooling_dfm_ready ? "." : ", after a redesign."}`;
}

/* ------------------------------------------------------------------ */
/*  Cost-by-quantity chart (F5)                                        */
/* ------------------------------------------------------------------ */

export interface ChartModel {
  grid: string;
  others: string;
  notReady: string;
  rec: string;
  recDots: string;
  qLine: string;
  qx: number;
  qAnchor: "start" | "middle" | "end";
  xTicks: { x: number; label: string; anchor: "start" | "middle" | "end" }[];
  yTicks: { y: number; label: string }[];
  aria: string;
  notReadyNames: string[];
}

function dollarTick(v: number): string {
  if (v >= 1) return `$${Math.round(v).toLocaleString("en-US")}`;
  return `$${+v.toFixed(4)}`;
}

/** Chart viewBox: `width` × CHART_H (drawn at its pixel width so labels stay legible). Log x (1 to `max`); log y over the curves' decades. */
export const CHART_H = 258;

export function chartModel(be: Breakeven, q: number, recProcess: string | null, max: number, width = 880): ChartModel {
  const X0 = 56, X1 = width - 8, Y0 = 230, Y1 = 22;
  const lmax = Math.log10(max);
  const X = (v: number) => X0 + (Math.log10(Math.max(1, v)) / lmax) * (X1 - X0);
  const samples: number[] = [];
  for (let i = 0; i <= 60; i++) samples.push(10 ** ((lmax * i) / 60));
  let lo = Infinity, hi = -Infinity;
  for (const c of be.curves) {
    for (const s of samples) {
      const u = unitCostAt(c, s);
      if (Number.isFinite(u) && u > 0) {
        lo = Math.min(lo, u);
        hi = Math.max(hi, u);
      }
    }
  }
  if (!Number.isFinite(lo)) { lo = 1; hi = 10; }
  let ylo = Math.floor(Math.log10(lo));
  let yhi = Math.ceil(Math.log10(hi));
  if (yhi - ylo < 1) yhi = ylo + 1;
  if (yhi - ylo > 6) ylo = yhi - 6;
  const Y = (u: number) => {
    const l = Math.log10(Math.max(10 ** ylo, Math.min(10 ** yhi, u)));
    return Y0 - ((l - ylo) / (yhi - ylo)) * (Y0 - Y1);
  };
  const path = (c: ProcessCurve) => samples.map((s, i) => `${i ? "L" : "M"}${X(s).toFixed(1)} ${Y(unitCostAt(c, s)).toFixed(1)}`).join(" ");
  const rec = be.curves.find((c) => c.process === recProcess) ?? null;
  const xs = decadeTicks(max);
  const ys: number[] = [];
  for (let d = ylo; d <= yhi; d++) ys.push(10 ** d);
  const grid = [
    ...xs.map((v) => `M${X(v).toFixed(1)} ${Y1} L${X(v).toFixed(1)} ${Y0}`),
    ...ys.map((v) => `M${X0} ${Y(v).toFixed(1)} L${X1} ${Y(v).toFixed(1)}`),
  ].join(" ");
  const qx = X(q);
  const others = be.curves.filter((c) => c !== rec && c.dfmReady);
  const notReady = be.curves.filter((c) => c !== rec && !c.dfmReady);
  const at = rec ? unitCostAt(rec, q) : null;
  return {
    grid,
    others: others.map(path).join(" "),
    notReady: notReady.map(path).join(" "),
    rec: rec ? path(rec) : "",
    recDots: rec ? rec.points.map((p) => `M${X(p.qty).toFixed(1)} ${Y(p.unit).toFixed(1)} l0.01 0`).join(" ") : "",
    qLine: `M${qx.toFixed(1)} ${Y1} L${qx.toFixed(1)} ${Y0}`,
    qx,
    qAnchor: qx > X1 - 70 ? "end" : qx < X0 + 34 ? "start" : "middle",
    xTicks: xs.map((v, i) => ({ x: X(v), label: qtyText(v), anchor: i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle" })),
    yTicks: ys.map((v) => ({ y: Y(v) - 4, label: dollarTick(v) })),
    aria: `Cost each from 1 to ${qtyText(max)} parts for ${be.curves.length} methods.${rec && at != null ? ` At ${qtyText(q)}: ${methodName(rec.process)} ${money(at)}.` : ""}`,
    notReadyNames: notReady.map((c) => methodName(c.process)),
  };
}

/* ------------------------------------------------------------------ */
/*  Findings (F6)                                                      */
/* ------------------------------------------------------------------ */

export type FindingKind = "thin" | "support" | "reach" | "draft" | "none";
export type Sev = "error" | "warning" | "info";

export interface FindingRow {
  key: string;
  issue: Issue;
  faces: number[];
  processes: string[];
  sev: Sev;
  title: string;
  sub: string;
  localized: boolean;
  kind: FindingKind;
  /** each method's own required value, when the engine states one */
  needs: { process: string; issue: Issue }[];
  /** the flattened issue keys this row stands for */
  members: string[];
}

const KIND_BY_CODE: Record<string, FindingKind> = {
  INSUFFICIENT_DRAFT: "draft",
  SETUP_ACCESS_UNVERIFIED: "reach",
  UNDERCUT: "reach",
  TOOL_ACCESS: "reach",
  RESIDUAL_STRESS_RISK: "support",
  CUPPING_RISK: "support",
  OVERHANG: "support",
  SUPPORT_REQUIRED: "support",
  THIN_WALL: "thin",
  THIN_WALL_MOLDING: "thin",
};

export function findingKind(issue: Pick<Issue, "code" | "severity">, localized: boolean): FindingKind {
  if (!localized) return "none";
  const k = KIND_BY_CODE[issue.code];
  if (k) return k;
  if (/DRAFT/.test(issue.code)) return "draft";
  if (/OVERHANG|SUPPORT/.test(issue.code)) return "support";
  if (/THIN/.test(issue.code)) return "thin";
  return issue.severity === "error" ? "thin" : "reach";
}

function sevOf(s: string): Sev {
  return s === "error" || s === "critical" || s === "fail" ? "error" : s === "warning" || s === "warn" ? "warning" : "info";
}

function procList(names: string[]): string {
  return names.length > 3 ? `${names.slice(0, 3).join(", ")} +${names.length - 3}` : names.join(", ");
}

/**
 * One row per finding, processes attached: required fixes first, then
 * advisory, then notes. Rows with the same code and severity on the same faces
 * merge (the engine words them per method); each method's own required value
 * is kept in `needs`.
 */
export function findingRows(v: ValidationResult | null): FindingRow[] {
  if (!v) return [];
  const rank: Record<Sev, number> = { error: 0, warning: 1, info: 2 };
  const merged = new Map<string, FindingRow>();
  const order: FindingRow[] = [];
  for (const row of flattenIssues(v)) {
    const issue = row.issue;
    const sev = sevOf(issue.severity);
    const processes = [...issueProcesses(row)];
    const localized = row.faces.length > 0 || !!issue.region_center;
    const sig = `${issue.code}|${sev}|${issue.region_center?.join(",") ?? ""}|${row.faces.join(",")}`;
    const need = issue.required_value != null ? processes.map((p) => ({ process: p, issue })) : [];
    const hit = merged.get(sig);
    if (hit) {
      for (const p of processes) if (!hit.processes.includes(p)) hit.processes.push(p);
      hit.needs.push(...need);
      hit.members.push(row.key);
      hit.sub = hit.processes.length ? procList(hit.processes.map(methodName)) : "Every method";
      continue;
    }
    const r: FindingRow = {
      key: row.key,
      issue,
      faces: row.faces,
      processes,
      sev,
      title: findingTitleFor(issue),
      sub: processes.length ? procList(processes.map(methodName)) : "Every method",
      localized,
      kind: findingKind(issue, localized),
      needs: need,
      members: [row.key],
    };
    merged.set(sig, r);
    order.push(r);
  }
  return order
    .map((r, i) => ({ r, i }))
    .sort((a, b) => rank[a.r.sev] - rank[b.r.sev] || a.i - b.i)
    .map(({ r }) => r);
}

export function findingTitleFor(issue: Pick<Issue, "code" | "measured_value" | "measurement_unit" | "message">): string {
  return findingTitle(issue.code, issue.measured_value ?? null, issue.measurement_unit ?? null, issue.message);
}

/** The measured / required line for the selected-finding card. */
export function measureLine(issue: Issue, fmt: (i: Issue, f?: "measured_value" | "required_value") => string): string {
  const m = issue.measured_value != null ? fmt(issue) : null;
  const r = issue.required_value != null ? fmt(issue, "required_value") : null;
  if (m && r) return `Measured ${m} · needs ${r}`;
  if (m) return `Measured ${m}`;
  if (r) return `Needs ${r}`;
  const n = issue.affected_face_count;
  if (n != null && n > 0) return `${n.toLocaleString("en-US")} faces`;
  return "";
}

/* ------------------------------------------------------------------ */
/*  All methods matrix (F6)                                            */
/* ------------------------------------------------------------------ */

export interface MethodRow {
  process: string;
  name: string;
  verdict: "pass" | "issues" | "fail";
  chip: "c-ok" | "c-warn" | "c-bad";
  chipLabel: string;
  score: number;
  cost: number | null;
  note: string;
  cls: "" | "geo-pick" | "cost-pick";
  first: { key: string | null; title: string } | null;
}

export interface Matrix {
  rows: MethodRow[];
  qty: number | null;
  costPick: string | null;
  geoPick: string | null;
  cantAsDrawn: number;
  total: number;
  foot: string | null;
}

const CHIP: Record<MethodRow["verdict"], [MethodRow["chip"], string]> = {
  pass: ["c-ok", "Ready"],
  issues: ["c-warn", "Check first"],
  fail: ["c-bad", "Can’t as drawn"],
};

export function methodMatrix(v: ValidationResult | null, report: CostReport | null, q: number | null, findings: FindingRow[]): Matrix {
  const qs = report ? costedQtys(report) : [];
  const qty = q != null ? nearestQty(qs, q) : qs[0] ?? null;
  const geoPick = report?.routing?.recommended_process ?? v?.best_process ?? null;
  const costAt = (process: string): number | null => {
    if (!report || qty == null) return null;
    const rows = report.estimates.filter((e) => e.process === process && e.quantity === qty && !e.environment_excluded);
    return rows.length ? Math.min(...rows.map((e) => e.unit_cost_usd)) : null;
  };
  const excluded = (process: string) => !!report && report.estimates.some((e) => e.process === process) &&
    report.estimates.filter((e) => e.process === process).every((e) => e.environment_excluded);
  let costPick: string | null = null;
  if (report?.decision && qty != null) costPick = report.decision.recommendation?.[String(qty)]?.process ?? null;
  const base: { process: string; verdict: MethodRow["verdict"]; score: number; n: number; firstText: string | null }[] = v
    ? v.process_scores.map((ps) => ({
        process: ps.process,
        verdict: ps.verdict,
        score: Math.round((ps.score ?? 0) * 100),
        n: ps.issues.length,
        firstText: ps.issues.find((i) => sevOf(i.severity) === "error")?.code ?? null,
      }))
    : (report?.engine_feasibility ?? []).map((f) => ({
        process: f.process,
        verdict: (f.verdict === "pass" || f.verdict === "fail" ? f.verdict : "issues") as MethodRow["verdict"],
        score: Math.round((f.score ?? 0) * 100),
        n: f.blockers?.length ?? 0,
        firstText: f.blockers?.[0] ?? null,
      }));
  const mat = report ? materialName(report.material_class).toLowerCase() : "";
  const rows: MethodRow[] = base.map((b) => {
    const cost = costAt(b.process);
    const fr = b.firstText && v ? findings.find((f) => f.sev === "error" && f.issue.code === b.firstText && f.processes.includes(b.process)) : null;
    const first = b.verdict === "fail" && b.firstText
      ? { key: fr?.key ?? null, title: fr ? fr.title : v ? findingTitle(b.firstText) : b.firstText }
      : null;
    const nText = `${b.n} finding${b.n === 1 ? "" : "s"}`;
    const note = b.process === geoPick ? `Geometry pick · ${nText}`
      : b.process === costPick && qty != null ? `Cost pick at ${qtyText(qty)} · ${nText}`
      : cost != null ? nText
      : excluded(b.process) ? "Ruled out by the service conditions"
      : report ? `Fit only · not priced${mat ? ` in ${mat}` : ""}`
      : nText;
    const [chip, chipLabel] = CHIP[b.verdict] ?? CHIP.issues;
    return {
      process: b.process,
      name: methodName(b.process),
      verdict: b.verdict,
      chip,
      chipLabel,
      score: b.score,
      cost,
      note,
      cls: b.process === geoPick ? "geo-pick" : b.process === costPick ? "cost-pick" : "",
      first,
    };
  });
  rows.sort((a, b) => Number(a.verdict === "fail") - Number(b.verdict === "fail") || b.score - a.score);
  let foot: string | null = null;
  if (costPick && geoPick && qty != null) {
    foot = costPick === geoPick
      ? `Cheapest at ${qtyText(qty)} is ${inSentence(methodName(costPick))}, which is also how the geometry reads.`
      : `Cheapest at ${qtyText(qty)} is ${inSentence(methodName(costPick))}. The geometry reads as ${inSentence(methodName(geoPick))}. Pick on intent, not only price.`;
  }
  return { rows, qty, costPick, geoPick, cantAsDrawn: rows.filter((r) => r.verdict === "fail").length, total: rows.length, foot };
}

export function featureCells(features: FeatureInfo[] | null | undefined): { n: string; label: string }[] {
  if (!features?.length) return [];
  const byKind = new Map<string, FeatureInfo[]>();
  for (const f of features) byKind.set(f.kind, [...(byKind.get(f.kind) ?? []), f]);
  const cells: { n: string; label: string }[] = [];
  for (const [kind, list] of byKind) {
    if (kind === "flat") cells.push({ n: String(list.length), label: list.length === 1 ? "Flat face" : "Flat faces" });
    else if (kind === "cylinder_hole") {
      const one = list.length === 1 ? list[0] : null;
      const size = one && one.radius != null ? ` · Ø${+(one.radius * 2).toFixed(2)}${one.depth != null ? ` × ${+one.depth.toFixed(2)}` : ""} mm` : "";
      cells.push({ n: String(list.length), label: `${list.length === 1 ? "Through hole" : "Holes"}${size}` });
    } else cells.push({ n: String(list.length), label: kind.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) });
  }
  const conf = Math.min(...features.map((f) => f.confidence).filter((c) => Number.isFinite(c)));
  if (Number.isFinite(conf)) cells.push({ n: `${Math.round(conf * 100)}%`, label: "Lowest confidence" });
  return cells;
}

/* ------------------------------------------------------------------ */
/*  Glass box (F3)                                                     */
/* ------------------------------------------------------------------ */

export type ProvKind = "file" | "shop" | "yours" | "typ";

export function provOf(p: string | null | undefined): { cls: string; label: string; kind: ProvKind; color: string } {
  switch (p) {
    case "MEASURED":
    case "CAD":
      return { cls: "s-file", label: "Your file", kind: "file", color: "#1F4FC4" };
    case "SHOP":
      return { cls: "s-shop", label: "Shop", kind: "shop", color: "#0E7C86" };
    case "USER":
      return { cls: "s-yours", label: "Yours", kind: "yours", color: "#5B3FC4" };
    default:
      return { cls: "s-typ", label: "Typical", kind: "typ", color: "#9AA3AE" };
  }
}

export function driverValue(d: Pick<CostDriver, "value" | "unit">): string {
  if (d.unit === "$") return money(d.value);
  if (d.unit === "hr") return `${+d.value.toFixed(4)} h`;
  if (d.unit === "×") return `×${+d.value.toFixed(3)}`;
  if (d.unit === "parts") return `${+d.value.toFixed(2)} parts`;
  return `${+d.value.toFixed(4)} ${d.unit}`.trim();
}

export interface MethodChoice {
  process: string;
  name: string;
  material: string;
  unit: number;
  ready: boolean;
}

/** Each priced method at `qty`, cheapest first (cheapest material when a method has several). */
export function methodsAt(report: CostReport, qty: number): MethodChoice[] {
  const by = new Map<string, CostEstimate>();
  for (const e of report.estimates) {
    if (e.environment_excluded || e.quantity !== qty) continue;
    const cur = by.get(e.process);
    if (!cur || e.unit_cost_usd < cur.unit_cost_usd) by.set(e.process, e);
  }
  return [...by.values()]
    .sort((a, b) => a.unit_cost_usd - b.unit_cost_usd)
    .map((e) => ({ process: e.process, name: methodName(e.process), material: e.material, unit: e.unit_cost_usd, ready: e.dfm_ready }));
}

export function lineRows(e: CostEstimate): { label: string; v: number }[] {
  return Object.entries(e.line_items ?? {}).map(([k, v]) => ({ label: lineName(k), v }));
}

export function sumCheck(e: CostEstimate): { sum: number; coherent: boolean } {
  const sum = Object.values(e.line_items ?? {}).reduce((s, v) => s + (Number.isFinite(v) ? v : 0), 0);
  return { sum, coherent: Math.abs(sum - e.unit_cost_usd) < Math.max(0.02, e.unit_cost_usd * 0.001) };
}

export function governance(drivers: readonly CostDriver[]) {
  const counts: Record<ProvKind, number> = { file: 0, shop: 0, yours: 0, typ: 0 };
  for (const d of drivers) counts[provOf(d.provenance).kind] += 1;
  const total = drivers.length;
  const order: ProvKind[] = ["file", "shop", "yours", "typ"];
  const color: Record<ProvKind, string> = { file: "#1F4FC4", shop: "#0E7C86", yours: "#5B3FC4", typ: "#9AA3AE" };
  const label: Record<ProvKind, string> = { file: "Your file", shop: "Shop", yours: "Yours", typ: "Typical" };
  return {
    grounded: total - counts.typ,
    total,
    segs: order.filter((k) => counts[k]).map((k) => ({ n: counts[k], c: color[k] })),
    rows: order.map((k) => ({ label: label[k], n: counts[k] })),
    aria: order.map((k) => `${label[k]} ${counts[k]}`).join(", "),
  };
}

/** Assumption overrides the glass box can re-cost, with their editor label and unit. */
export const EDITABLE_ASSUMPTIONS: Record<string, [string, string]> = {
  labor_rate: ["Labor rate", "$/h"],
  margin: ["Margin", "fraction, 0.25 = 25%"],
  overhead: ["Overhead", "fraction"],
  utilization: ["Utilization", "fraction, 0 to 1"],
  stock_allowance: ["Stock allowance", "× billet"],
  daily_machine_hours: ["Machine hours per day", "h"],
  n_cavities: ["Mold cavities", "count"],
};

/** The override key an assumption edit sets (`cavities` is a costing option, not a rate). */
export function assumptionKey(name: string): string {
  return name === "n_cavities" ? "cavities" : name;
}

export function rateChips(assumptions: readonly CostAssumption[], overrides: Record<string, number> | undefined) {
  const ov = overrides ?? {};
  const t = (a: CostAssumption) => `${assumptionName(a.name)} ${assumptionValue(a.name, a.value, a.unit)}`;
  return {
    bound: assumptions.filter((a) => a.provenance === "SHOP").map(t),
    still: assumptions.filter((a) => a.provenance === "DEFAULT" && ov[a.name] == null).map(t),
  };
}

/* ------------------------------------------------------------------ */
/*  Compare (F7)                                                       */
/* ------------------------------------------------------------------ */

export interface CompareCell {
  process: string;
  qty: number;
  run: string;
  unit: number | null;
  band: number | null;
}

export interface CompareRow {
  process: string;
  name: string;
  sub: string;
  cells: CompareCell[];
  change: number | null;
}

/** Each method at the first and last costed quantity, cheapest at the last first. */
export function compareByQty(report: CostReport): { qa: number | null; qb: number | null; rows: CompareRow[] } {
  const qs = costedQtys(report);
  if (!qs.length) return { qa: null, qb: null, rows: [] };
  const qa = qs[0], qb = qs[qs.length - 1];
  const procs = [...new Set(report.estimates.filter((e) => !e.environment_excluded).map((e) => e.process))];
  const rows = procs.map((p) => {
    const a = estimateFor(report, p, qa);
    const b = estimateFor(report, p, qb);
    const ea = a?.quantity === qa ? a : null;
    const eb = b?.quantity === qb ? b : null;
    const ready = (ea ?? eb)?.dfm_ready ?? true;
    const cells: CompareCell[] = [{ process: p, qty: qa, run: "base", unit: ea?.unit_cost_usd ?? null, band: bandPct(ea) }];
    if (qb !== qa) cells.push({ process: p, qty: qb, run: "base", unit: eb?.unit_cost_usd ?? null, band: bandPct(eb) });
    const change = ea && eb && qb !== qa && ea.unit_cost_usd > 0 ? ((eb.unit_cost_usd - ea.unit_cost_usd) / ea.unit_cost_usd) * 100 : null;
    return { process: p, name: methodName(p), sub: `${(ea ?? eb)?.material ?? ""}${ready ? "" : " · if redesigned"}`, cells, change };
  });
  rows.sort((x, y) => (x.cells[x.cells.length - 1].unit ?? Infinity) - (y.cells[y.cells.length - 1].unit ?? Infinity));
  return { qa, qb, rows };
}

/** Each method at one quantity under several rate sets (one engine run each). */
export function compareByRates(runs: { id: string; report: CostReport | null }[], qty: number): CompareRow[] {
  const procs: string[] = [];
  for (const r of runs) for (const e of r.report?.estimates ?? []) if (!e.environment_excluded && !procs.includes(e.process)) procs.push(e.process);
  const rows = procs.map((p) => {
    const cells = runs.map((r) => {
      const e = r.report ? estimateFor(r.report, p, qty) : null;
      const exact = e?.quantity === qty ? e : null;
      return { process: p, qty, run: r.id, unit: exact?.unit_cost_usd ?? null, band: bandPct(exact) };
    });
    const any = runs.map((r) => (r.report ? estimateFor(r.report, p, qty) : null)).find(Boolean) ?? null;
    return { process: p, name: methodName(p), sub: `${any?.material ?? ""}${any && !any.dfm_ready ? " · if redesigned" : ""}`, cells, change: null };
  });
  rows.sort((x, y) => (x.cells[0].unit ?? Infinity) - (y.cells[0].unit ?? Infinity));
  return rows;
}

export function changeText(pct: number | null): { text: string; cls: "dn" | "up" | "" } {
  if (pct == null || !Number.isFinite(pct)) return { text: "—", cls: "" };
  return { text: `${pct < 0 ? "−" : "+"}${Math.abs(pct).toFixed(0)}%`, cls: pct < 0 ? "dn" : "up" };
}

/* ------------------------------------------------------------------ */
/*  History and the decision summary (F8)                              */
/* ------------------------------------------------------------------ */

export interface HistoryRow {
  id: string;
  created_at: string;
  title: string;
  sub: string;
  chip: "c-ok" | "c-warn" | "c-unk";
  tag: string;
  share: string;
  cur: boolean;
}

export function historyRows(list: readonly CostDecisionSummary[], currentId: string | null): HistoryRow[] {
  return list.map((d) => {
    const cur = d.id === currentId;
    const cross = d.crossover_qty && Number.isFinite(d.crossover_qty) ? ` · tooling pays off near ${qtyText(d.crossover_qty)}` : " · no tooling crossover";
    const approved = d.approval_status === "approved";
    return {
      id: d.id,
      created_at: d.created_at,
      title: d.make_now_process ? `Make now: ${methodName(d.make_now_process)}` : "No make-now pick",
      sub: `${qtyListText(d.quantities ?? [])}${cross}${cur ? " · this decision" : ""}`,
      chip: d.is_stale ? "c-warn" : approved ? "c-ok" : "c-unk",
      tag: d.is_stale ? "Out of date" : approved ? "Approved" : "Unreviewed",
      share: d.is_public ? "Shared" : "Private",
      cur,
    };
  });
}

const VERDICT_WORDS: Record<string, string> = { pass: "ready as drawn", issues: "issues to check", fail: "can’t as drawn", unknown: "not checked" };

/** Plain text for email or a ticket: the decision at `q`, each costed quantity, the crossover and the DFM read. */
export function decisionSummary(report: CostReport | null, v: ValidationResult | null, q: number | null): string {
  if (!report) return "";
  const lines = [`ScaleCAD — ${report.filename}`];
  const be = deriveBreakeven(report);
  const at = be && q != null ? decisionAt(report, be, q) : null;
  if (at && q != null) {
    lines.push(`Make by ${inSentence(at.name)} / ${at.curve.material} at quantity ${qtyText(q)}`);
    if (!at.exact) lines.push("  Approximate at this quantity; re-cost it to include batch rounding and minimum charges.");
  } else {
    lines.push("No make-now pick in this decision.");
  }
  const dec = report.decision;
  for (const qty of report.quantities ?? []) {
    const r = dec?.recommendation?.[String(qty)];
    if (!r) continue;
    const lead = r.lead_low_days != null && r.lead_high_days != null ? `, ${+r.lead_low_days.toFixed(1)}-${+r.lead_high_days.toFixed(1)} days` : "";
    lines.push(`  qty ${qtyText(qty)}: ${inSentence(methodName(r.process))} — ${money(r.unit_cost_usd)}/unit${lead}`);
  }
  if (dec) lines.push(crossoverSentence(report));
  const process = at?.curve.process ?? report.routing?.recommended_process ?? null;
  if (process) {
    const ps = v?.process_scores.find((p) => p.process === process);
    lines.push(`DFM · ${methodName(process)}: ${VERDICT_WORDS[ps?.verdict ?? "unknown"] ?? "not checked"}`);
  }
  return lines.join("\n");
}

/* ------------------------------------------------------------------ */
/*  Session words                                                      */
/* ------------------------------------------------------------------ */

export function newPartText(overrides: number, scenarios: number): string {
  if (!overrides && !scenarios) return "This part’s saved decision stays in Records.";
  const bits = [
    overrides ? `${overrides} override${overrides === 1 ? "" : "s"}` : "",
    scenarios ? `${scenarios} saved scenario${scenarios === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return `Drops this session’s ${bits.join(" and ")}. The saved decision stays in Records.`;
}

export function scenarioLabel(shopName: string | null, overrides: Record<string, number> | undefined): string {
  const parts: string[] = [];
  if (shopName) parts.push(shopName);
  for (const [k, v] of Object.entries(overrides ?? {})) parts.push(`${k} ${v}`);
  return parts.length ? parts.join(" · ") : "Engine";
}
