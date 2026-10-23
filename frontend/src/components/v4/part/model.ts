/**
 * The part page's view model: every row, figure and sentence on the five lenses,
 * computed from the engine's own results for this part (the check's
 * ValidationResult, the CostReport and its machine-fit `verification` block, and
 * your machine inventory). Nothing here invents a number: a value is selected
 * from those responses, interpolated and labelled as such, or shown as missing.
 *
 * Pure: no React, no fetch, and only relative `.ts` runtime imports, so it runs
 * under `node --test` (model.test.ts).
 */
import type { CostDriver, CostEstimate, CostReport, Issue, ProcessScore, ValidationResult } from "@/lib/api";
import type { OwnedMachine } from "@/lib/verify/machine-api";
import type { FitFailure, PerRouteFit } from "@/lib/verify/verification";
import { gapText, readVerification } from "../../../lib/verify/verification.ts";
import { onceAndEach, unitCostAt } from "../../../lib/qty-model.ts";
import { ROUNDING_KEY, foldedTooling, footLines, lineDriver, roundingWords } from "../../../lib/cost-lines.ts";
import { MACHINE_KIND, processLabel } from "../process-names.ts";

/* ── formatting ─────────────────────────────────────────────────────────── */

export function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function qtyWord(q: number): string {
  return q.toLocaleString("en-US");
}

export function trimNum(v: number, digits = 1): string {
  const r = Math.round(v * 10 ** digits) / 10 ** digits;
  return r.toLocaleString("en-US", { maximumFractionDigits: digits });
}

export function dimsText(bbox: readonly number[] | null | undefined): string | null {
  if (!bbox || bbox.length !== 3 || !bbox.every((n) => Number.isFinite(n))) return null;
  return `${bbox.map((n) => trimNum(n, 1)).join(" × ")} mm`;
}

export function days(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo == null || hi == null || !Number.isFinite(lo) || !Number.isFinite(hi)) return "—";
  return `${Math.round(lo)}–${Math.round(hi)} days`;
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "";
}

export function plural(n: number, one: string, many?: string): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many ?? one + "s"}`;
}

/* ── methods ────────────────────────────────────────────────────────────── */

export type Family = "print" | "machine" | "form";
export type Verdict = "ok" | "warn" | "bad" | "out" | "unk";
export type Kind = "thin" | "support" | "reach" | "draft";

export const FAMILY_LABEL: Record<Family, string> = {
  print: "3D printing",
  machine: "Machining",
  form: "Molding, casting and forming",
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  ok: "Can make",
  warn: "Check first",
  bad: "Can't as drawn",
  out: "Ruled out",
  unk: "Not checked",
};

interface MethodInfo {
  name: string;
  short: string;
  family: Family;
  metalOnly?: boolean;
  group?: "metalprint" | "cast";
}

export const METHODS: Record<string, MethodInfo> = {
  fdm: { name: "Filament printing", short: "FDM/FFF", family: "print" },
  sla: { name: "Resin printing", short: "SLA", family: "print" },
  dlp: { name: "Resin printing", short: "DLP", family: "print" },
  sls: { name: "Nylon powder printing", short: "SLS", family: "print" },
  mjf: { name: "Nylon powder printing", short: "MJF", family: "print" },
  dmls: { name: "Metal powder printing", short: "DMLS", family: "print", metalOnly: true, group: "metalprint" },
  slm: { name: "Metal powder printing", short: "SLM", family: "print", metalOnly: true, group: "metalprint" },
  ebm: { name: "Electron-beam printing", short: "EBM", family: "print", metalOnly: true, group: "metalprint" },
  binder_jetting: { name: "Metal binder jetting", short: "Binder jet", family: "print", metalOnly: true, group: "metalprint" },
  ded: { name: "Metal deposition", short: "DED", family: "print", metalOnly: true, group: "metalprint" },
  waam: { name: "Wire-arc printing", short: "WAAM", family: "print", metalOnly: true, group: "metalprint" },
  cnc_3axis: { name: "3-axis milling", short: "CNC", family: "machine" },
  cnc_5axis: { name: "5-axis milling", short: "CNC", family: "machine" },
  cnc_turning: { name: "Turning", short: "CNC lathe", family: "machine" },
  wire_edm: { name: "Wire EDM", short: "EDM", family: "machine", metalOnly: true },
  sheet_metal: { name: "Sheet metal", short: "Bend and cut", family: "form" },
  injection_molding: { name: "Injection molding", short: "IM", family: "form" },
  investment_casting: { name: "Investment casting", short: "Investment", family: "form", metalOnly: true },
  die_casting: { name: "Die casting", short: "Die", family: "form", metalOnly: true, group: "cast" },
  sand_casting: { name: "Sand casting", short: "Sand", family: "form", metalOnly: true, group: "cast" },
  forging: { name: "Forging", short: "Forging", family: "form", metalOnly: true, group: "cast" },
};

export function methodName(code: string | null | undefined): string {
  if (!code) return "—";
  return METHODS[code]?.name ?? code.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function methodShort(code: string): string {
  return METHODS[code]?.short ?? code.toUpperCase();
}

/** An engine process in plain words with its acronym: "Filament printing (FDM/FFF)". One spelling for every screen. */
export { processLabel };

/**
 * The rates a saved record was priced at against the organization's rates now (ce-10): the one line the part
 * page shows near the price when they differ ("Priced at rates v0; your rates are v1."), else null.
 */
export function ratesNote(decision: { rates?: { priced: number; current: number; out_of_date: boolean; text?: string } | null } | null | undefined): string | null {
  const r = decision?.rates;
  if (!r || !r.out_of_date) return null;
  return r.text?.trim() || `Priced at rates v${r.priced}; your rates are v${r.current}.`;
}

/**
 * The problem count in words, from the same list the page counts ("Problems 9 · 5 stop a process"), so
 * "Why this verdict?" never says "no problems found" over a page that lists problems.
 */
export function problemWords(problems: { severity: string }[]): string {
  const n = problems.length;
  if (!n) return "no problems found on this part";
  const stopping = problems.filter((x) => x.severity === "error").length;
  return `${plural(n, "problem")} on this part, ${stopping ? `${stopping} ${stopping === 1 ? "stops" : "stop"} a process` : "none stops a process"}`;
}

/** The machine kind a process stands for, for machine rows ("3-axis mill"): shared with every screen. */
export { MACHINE_KIND };

export const MATERIAL_CLASS_LABEL: Record<string, string> = {
  polymer: "Plastic",
  aluminum: "Aluminum",
  steel: "Steel",
  stainless: "Stainless",
  titanium: "Titanium",
};

/** Which highlight color a finding gets on the part: the board's four kinds. */
export function issueKind(code: string): Kind | null {
  const c = code.toUpperCase();
  if (/THIN_WALL|THIN_BOSS|TOO_THIN|FRAGILE|SMALL_FEATURES|WALL_THICKNESS/.test(c)) return "thin";
  if (/OVERHANG|CUPPING|TRAPPED_VOLUME|RESIDUAL_STRESS|REORIENTATION/.test(c)) return "support";
  if (/SETUP_ACCESS|DEEP_HOLE|SHARP_INTERNAL|TOOL_REACH|HIGH_LD|FIXTURE|^UNDERCUT$/.test(c)) return "reach";
  if (/DRAFT|UNDERCUT_MOLDING/.test(c)) return "draft";
  return null;
}

export const KIND_COLOR: Record<Kind, string> = {
  thin: "#E5482A",
  support: "#2E6BE6",
  reach: "#B97F0C",
  draft: "#7A4FD6",
};

export interface Finding {
  issue: Issue;
  kind: Kind | null;
  text: string;
  faces: number[];
  region: [number, number, number] | null;
}

export interface Method {
  code: string;
  name: string;
  short: string;
  family: Family;
  /** Engine processes behind a grouped row ("Metal printing, 6 ways"). */
  members: string[];
  score: number | null;
  scoreRange: [number, number] | null;
  dfm: "pass" | "issues" | "fail" | null;
  verdict: Verdict;
  issues: Issue[];
  finding: Finding | null;
  /** Why it can't make the part, in the engine's own words (DFM gate or blocker). */
  blockedReason: string | null;
  excludedReason: string | null;
  /** ce-19: why it has no price in the part's material class, in the engine's words, or null. */
  notPricedReason?: string | null;
  /** ce-19: false when the process can't run the part's material class at all (FDM and steel). */
  runsClass?: boolean;
  /** Cheapest non-excluded estimate per computed quantity. */
  prices: Map<number, CostEstimate>;
  /** The machine of yours that clears every gate for this route, if any. */
  inHouse: string | null;
  fit: PerRouteFit | null;
  geometryPick: boolean;
  routePick: boolean;
  material: string | null;
  bestOf: number | null;
}

const SEV_RANK: Record<string, number> = { error: 0, warning: 1, info: 2 };

function primaryFinding(issues: Issue[]): Finding | null {
  if (!issues.length) return null;
  const ranked = [...issues].sort((a, b) => {
    const s = (SEV_RANK[a.severity] ?? 3) - (SEV_RANK[b.severity] ?? 3);
    if (s) return s;
    const ka = issueKind(a.code) && (a.affected_faces_sample?.length ?? 0) > 0 ? 0 : 1;
    const kb = issueKind(b.code) && (b.affected_faces_sample?.length ?? 0) > 0 ? 0 : 1;
    return ka - kb;
  });
  const issue = ranked[0];
  const faces = (issue.affected_faces_sample ?? []).filter((n) => Number.isInteger(n) && n >= 0);
  return {
    issue,
    kind: issueKind(issue.code),
    text: issue.message,
    faces,
    region: issue.region_center && issue.region_center.length === 3 ? issue.region_center : null,
  };
}

function cheapestByQty(estimates: CostEstimate[], process: string): Map<number, CostEstimate> {
  const out = new Map<number, CostEstimate>();
  for (const e of estimates) {
    if (e.process !== process || e.environment_excluded || e.spec_excluded) continue;
    const prev = out.get(e.quantity);
    if (!prev || e.unit_cost_usd < prev.unit_cost_usd) out.set(e.quantity, e);
  }
  return out;
}

function dfmFailureReason(fit: PerRouteFit | null | undefined): string | null {
  const dfm = fit?.failures?.find((f) => f.gate === "dfm");
  return dfm ? gapText(dfm) : null;
}

export interface PartInputs {
  validation: ValidationResult | null;
  cost: CostReport | null;
  machines: OwnedMachine[];
}

/** Every engine process for this part, with its verdict, finding and prices. */
export function buildMethods(input: PartInputs): Method[] {
  const { validation, cost } = input;
  const verification = readVerification(cost);
  const scores = new Map<string, ProcessScore>((validation?.process_scores ?? []).map((p) => [p.process, p]));
  const estimates = cost?.estimates ?? [];
  const feasibility = new Map((cost?.engine_feasibility ?? []).map((f) => [f.process, f]));
  const codes = new Set<string>([...scores.keys(), ...estimates.map((e) => e.process), ...feasibility.keys()]);
  const best = [...scores.values()].reduce<number | null>((m, p) => (m == null || p.score > m ? p.score : m), null);
  // A whole-file error (an open shell: "All manufacturing processes require a closed solid") stops every method,
  // even where that method's own score passed.
  const universalError = validation?.universal_issues?.find((i) => i.severity === "error") ?? null;
  const out: Method[] = [];
  for (const code of codes) {
    const info = METHODS[code] ?? { name: methodName(code), short: code.toUpperCase(), family: "form" as Family };
    const ps = scores.get(code) ?? null;
    const feas = feasibility.get(code) ?? null;
    const issues = ps?.issues ?? [];
    const prices = cheapestByQty(estimates, code);
    const all = estimates.filter((e) => e.process === code);
    const excluded = all.length > 0 && all.every((e) => e.environment_excluded || e.spec_excluded);
    const bySpecs = excluded && all.every((e) => e.spec_excluded && !e.environment_excluded);
    // The engine withheld every price for this process (a 20 mm block is under wire-arc printing's
    // size floor, or no setup fits the work area): ruled out in its words, not "Can make" with no price.
    const withheld = !excluded && all.length === 0 ? feas?.cost_exclusion_reason ?? null : null;
    const fit = verification?.per_route?.[code] ?? null;
    const dfm = (ps?.verdict ?? (feas?.verdict as ProcessScore["verdict"] | undefined) ?? null) as Method["dfm"];
    const score = ps?.score ?? feas?.score ?? null;
    const blocker = issues.find((i) => i.severity === "error")?.message ?? feas?.blockers?.[0] ?? null;
    let verdict: Verdict;
    if (excluded) verdict = "out";
    else if (dfm === "fail" || fit?.verdict === "not_makeable" || universalError) verdict = "bad";
    else if (withheld) verdict = "out";
    else if (issues.some((i) => i.severity === "warning" && /_UNVERIFIED$/.test(i.code))) verdict = "warn";
    else if (dfm == null && prices.size === 0) verdict = "unk";
    else verdict = "ok";
    const inHouse =
      fit && (fit.verdict === "makeable_in_house" || fit.verdict === "makeable_with_secondary_op") && verdict !== "bad" && verdict !== "out"
        ? fit.best_machine ?? null
        : null;
    const anyPrice = [...prices.values()][0];
    out.push({
      code,
      name: info.name,
      short: info.short,
      family: info.family,
      members: [code],
      score,
      scoreRange: score != null ? [score, score] : null,
      dfm,
      verdict,
      issues,
      finding: primaryFinding(issues),
      blockedReason: verdict === "bad" ? universalError?.message ?? dfmFailureReason(fit) ?? blocker : null,
      excludedReason: !excluded
        ? verdict === "out" ? withheld : null
        : bySpecs
          ? all.find((e) => e.spec_exclusion_reason)?.spec_exclusion_reason ?? "Can't meet the part's specs."
          : all.find((e) => e.environment_exclusion_reason)?.environment_exclusion_reason ?? "Ruled out by the declared service conditions.",
      prices,
      inHouse,
      fit,
      geometryPick: validation?.best_process === code,
      routePick: cost?.routing?.recommended_process === code,
      material: materialText(code, info, anyPrice?.material ?? null, cost?.material_class ?? null, !!cost),
      bestOf: best != null && score === best ? scores.size : null,
      notPricedReason: prices.size === 0 ? feas?.not_priced_reason ?? null : null,
      runsClass: feas?.runs_class === false ? false : !cannotRunClass(code, info, cost?.material_class ?? null),
    });
  }
  // ce-05: one material basis. A row priced in another grade than the one most rows use
  // says so, with the grade it is priced in.
  const grades = new Map<string, number>();
  for (const m of out) {
    const g = [...m.prices.values()][0]?.material;
    if (g) grades.set(g, (grades.get(g) ?? 0) + 1);
  }
  const basis = [...grades.entries()].sort((a, b) => b[1] - a[1])[0];
  if (basis && basis[1] > 1) {
    for (const m of out) {
      const g = [...m.prices.values()][0]?.material;
      if (g && g !== basis[0] && m.material === g) m.material = `${g}, not ${basis[0]}: the closest grade it runs`;
    }
  }
  return out;
}

/** True when a process can't run the material class at all (a plastic-only printer and steel). */
export function cannotRunClass(code: string, info: MethodInfo, cls: string | null): boolean {
  if (!cls) return false;
  const metal = !!info.metalOnly || code === "sheet_metal";
  return (metal && cls === "polymer") || (PLASTIC_ONLY.has(code) && cls !== "polymer");
}

/** "Can make N": processes whose DFM passes and that run the part's material class (ce-19). */
export function canMakeCount(methods: Method[]): number {
  return methods.filter((m) => (m.verdict === "ok" || m.verdict === "warn") && m.runsClass !== false).length;
}

const VERDICT_ORDER: Verdict[] = ["ok", "warn", "unk", "bad", "out"];

/** Collapse unpriced metal-only methods the board shows as one row (plastic parts). */
export function groupUnpriced(methods: Method[]): Method[] {
  // Grouped only with the same verdict (de-10): "Casting and forging, 3 ways · Can make" read
  // as all three when only die casting could, and sand casting and forging were blocked.
  const groups: Record<string, Method[]> = {};
  const rest: Method[] = [];
  for (const m of methods) {
    const g = METHODS[m.code]?.group;
    if (g && m.prices.size === 0 && m.verdict !== "out") (groups[`${g}␟${m.verdict}`] ??= []).push(m);
    else rest.push(m);
  }
  for (const [key, members] of Object.entries(groups)) {
    const g = key.split("␟")[0];
    if (members.length < 2) {
      rest.push(...members);
      continue;
    }
    const verdict = members.map((m) => m.verdict).sort((a, b) => VERDICT_ORDER.indexOf(a) - VERDICT_ORDER.indexOf(b))[0];
    const scores = members.map((m) => m.score).filter((s): s is number => s != null);
    rest.push({
      ...members[0],
      code: Object.keys(groups).filter((k) => k.startsWith(`${g}␟`) && groups[k].length > 1).length > 1 ? `group:${g}:${members[0].verdict}` : `group:${g}`,
      name: g === "metalprint" ? `Metal printing, ${members.length} ways` : `Casting and forging, ${members.length} ways`,
      short: members.map((m) => (g === "metalprint" ? m.short : m.name)).join(", "),
      members: members.map((m) => m.code),
      verdict,
      score: scores.length ? Math.max(...scores) : null,
      scoreRange: scores.length ? [Math.min(...scores), Math.max(...scores)] : null,
      issues: members.flatMap((m) => m.issues),
      finding: null,
      blockedReason: verdict === "bad" ? members.find((m) => m.blockedReason)?.blockedReason ?? null : null,
      inHouse: null,
      fit: null,
      geometryPick: members.some((m) => m.geometryPick),
      routePick: members.some((m) => m.routePick),
      material: null,
      bestOf: null,
    });
  }
  return rest;
}

export function priceAt(m: Method, q: number): number | null {
  const e = m.prices.get(q);
  return e ? e.unit_cost_usd : null;
}

/** A method can be ranked on price when it has a price and isn't ruled out. */
export function isPriced(m: Method): boolean {
  return m.prices.size > 0 && m.verdict !== "out";
}

/** A method you could order today: priced, not ruled out, not blocked by DFM. */
export function isWorkable(m: Method): boolean {
  return isPriced(m) && (m.verdict === "ok" || m.verdict === "warn");
}

export function cheapestAt(methods: Method[], q: number, pick: (m: Method) => boolean = isWorkable): Method | null {
  let best: Method | null = null;
  for (const m of methods) {
    if (!pick(m)) continue;
    const p = priceAt(m, q);
    if (p == null) continue;
    if (!best || p < (priceAt(best, q) ?? Infinity)) best = m;
  }
  return best;
}

export function quantitiesOf(cost: CostReport | null): number[] {
  const qs = cost?.quantities?.length ? cost.quantities : [...new Set((cost?.estimates ?? []).map((e) => e.quantity))];
  return [...new Set(qs)].filter((n) => Number.isFinite(n) && n > 0).sort((a, b) => a - b);
}

/** The quantity the page opens on: 10 if computed, else the smallest computed run of 10 or more. */
export function defaultQty(qs: number[]): number {
  if (qs.includes(10)) return 10;
  return qs.find((q) => q >= 10) ?? qs[qs.length - 1] ?? 1;
}

/**
 * The quantity a part opens at: its declared yearly quantity (a catalog run's
 * parts list, or set on the part) when the record priced it, so the part page,
 * its Decision and the run answer at the same quantity (op-08); else
 * `defaultQty` (10, else the first priced quantity of 10 or more, else the
 * largest). The backend's catalog_service opening quantity follows this rule.
 */
export function openingQty(qs: number[], yearly: number | null | undefined): number {
  if (yearly != null && yearly > 0 && qs.includes(yearly)) return yearly;
  return defaultQty(qs);
}

export interface MakeRow {
  kind: "group" | "row";
  label?: string;
  right?: string;
  method?: Method;
}

/** Make lens rows: families in board order, each sorted cheapest first at q. */
export function makeRows(methods: Method[], q: number): MakeRow[] {
  const rows: MakeRow[] = [];
  for (const fam of ["print", "machine", "form"] as Family[]) {
    const list = methods
      .filter((m) => m.family === fam)
      .sort((a, b) => {
        const pa = isPriced(a) ? priceAt(a, q) ?? 1e12 : 1e12;
        const pb = isPriced(b) ? priceAt(b, q) ?? 1e12 : 1e12;
        if (pa !== pb) return pa - pb;
        return VERDICT_ORDER.indexOf(a.verdict) - VERDICT_ORDER.indexOf(b.verdict) || a.name.localeCompare(b.name);
      });
    if (!list.length) continue;
    rows.push({ kind: "group", label: FAMILY_LABEL[fam], right: rows.length ? "" : `each at ${qtyWord(q)}` });
    for (const m of list) rows.push({ kind: "row", method: m });
  }
  return rows;
}

const PLASTIC_ONLY = new Set(["fdm", "sla", "dlp", "sls", "mjf", "injection_molding"]);

/**
 * The material a method's row names: the grade it is priced in, in the page's material class.
 * One material story per page (de-06, np-17): a process that can't run that class says so
 * ("can’t run plastic", or the metal it is priced in and why) instead of naming the first alloy
 * on its list (Inconel 718 on a plastic box); an unpriced row names no grade.
 */
export function materialText(code: string, info: MethodInfo, priced: string | null, cls: string | null, hasCost: boolean): string | null {
  const metal = !!info.metalOnly || code === "sheet_metal";
  const word = cls ? (MATERIAL_CLASS_LABEL[cls] ?? cls).toLowerCase() : null;
  const cannot = !!cls && ((metal && cls === "polymer") || (PLASTIC_ONLY.has(code) && cls !== "polymer"));
  if (priced) return cannot ? `${priced}, can’t run ${word}` : priced;
  if (!hasCost) return null;
  return cannot ? `can’t run ${word}` : null;
}

/** "DLP · Standard Resin · on your Haas VF-2 · highest design score" */
export function methodSub(m: Method): string {
  if (m.members.length > 1) return m.short;
  const parts = [m.short];
  if (m.material) parts.push(m.material);
  if (m.inHouse) parts.push(`on your ${m.inHouse}`);
  // "ScaleCAD's pick" is the one pick on the part page; the design-rule best is a score.
  if (m.geometryPick) parts.push("highest design score");
  else if (m.routePick) parts.push("typical for the shape");
  return parts.join(" · ");
}

export function dfmMeta(m: Method): string {
  const parts: string[] = [];
  if (m.scoreRange && m.members.length > 1 && m.scoreRange[0] !== m.scoreRange[1]) {
    parts.push(`DFM ${m.scoreRange[0].toFixed(1)}–${m.scoreRange[1].toFixed(1)}`);
  } else if (m.score != null) {
    parts.push(`DFM score ${m.score.toFixed(1)}${m.bestOf ? `, best of ${m.bestOf}` : ""}`);
  }
  if (m.dfm === "fail") parts.push("blocked");
  if (m.members.length > 1) parts.push(`${m.members.length} processes`);
  else parts.push(plural(m.issues.length, "finding"));
  return parts.join(" · ");
}

/** "Could be $6.37–$8.27 · 5–9 days at 10", from the engine's own band and queue model. */
export function priceMeta(m: Method, q: number): string | null {
  const e = m.prices.get(q);
  if (!e || m.verdict === "out") return null;
  const lo = e.confidence?.low_usd ?? e.unit_cost_usd * (1 - e.est_error_band_pct / 100);
  const hi = e.confidence?.high_usd ?? e.unit_cost_usd * (1 + e.est_error_band_pct / 100);
  return `Could be ${money(lo)}–${money(hi)} · ${days(e.lead_time?.low_days, e.lead_time?.high_days)} at ${qtyWord(q)}`;
}

export function methodWhy(m: Method, materialClass: string | null): string {
  if (m.excludedReason) return m.excludedReason;
  if (m.blockedReason) return m.blockedReason;
  if (m.notPricedReason) return m.notPricedReason;
  if (m.members.length > 1 && m.prices.size === 0 && materialClass === "polymer") return "Priced once you choose a metal.";
  if (m.finding) return m.finding.text;
  if (m.prices.size === 0 && METHODS[m.code]?.metalOnly && materialClass === "polymer") return "Needs a metal; not priced in plastic.";
  return m.issues.length ? m.issues[0].message : "No findings for this process.";
}

/* ── fixes (the priority list) ─────────────────────────────────────────── */

export interface Fix {
  n: number;
  where: string;
  fix: string;
  tone: "bad" | "warn" | "unk";
  sev: string;
}

export function fixesOf(validation: ValidationResult | null): Fix[] {
  return (validation?.priority_fixes ?? []).map((f, i) => {
    const tone = f.severity === "error" ? "bad" : f.severity === "warning" ? "warn" : "unk";
    const text = (f.fix ?? f.message ?? "").split(/\n\s*\n/)[0].trim();
    return {
      n: i + 1,
      where: f.process ? methodName(f.process) : "Every process",
      fix: text || f.message,
      tone,
      sev: tone === "bad" ? "Blocks" : tone === "warn" ? "Check" : "Note",
    };
  });
}

/* ── cost lines (where a price comes from) ─────────────────────────────── */

export type SrcKind = "file" | "yours" | "typ";

/** Where a cost line comes from. `rateCard`: the org's published rate card version its rate is from ("Your rates v1"). */
export function srcOf(provenance: string | null | undefined, rateCard?: number | null): { kind: SrcKind; label: string } {
  const p = String(provenance ?? "").toUpperCase();
  if (p === "MEASURED" || p === "CAD") return { kind: "file", label: "Your file" };
  if (p === "SHOP" && rateCard != null) return { kind: "yours", label: `Your rates v${rateCard}` };
  if (p === "USER" || p === "SHOP") return { kind: "yours", label: "Yours" };
  return { kind: "typ", label: "Typical" };
}

const DRIVER_LABEL: Record<string, (q: number, d: CostDriver) => string> = {
  labor_cost: () => "Labor",
  nre_cost: (q) => `Programming, shared over ${qtyWord(q)}`,
  inspection_cost: () => "Inspection",
  // A machine is set up once for the order; a printer once per plate (the engine's source says which).
  setup_cost: (q, d) => (/per plate/.test(d.source ?? "") ? "Setup, one per plate" : `Setup, shared over ${qtyWord(q)}`),
  machine_cost: () => "Machine",
  material_cost: () => "Material",
  consumables_cost: () => "Tools and coolant",
  tooling_cost: () => "Tooling, the whole tool",
  tooling_per_part: (q) => `Tooling, shared over ${qtyWord(q)}`,
  blank_outside_cost: () => "Blank cut outside",
  // de-20: a lot priced at the process's order minimum ($300 for wire-arc) says so.
  min_charge_floor: (q) => (q === 1 ? "Order minimum, on one part" : `Order minimum, shared over ${qtyWord(q)}`),
  finish_machining: () => "Finish machining",
  finishing_cost: () => "Finishing",
  post_process_cost: () => "Finishing",
  sintering_cost: () => "Sintering",
  energy_cost: () => "Energy",
  // Declared part specs (Conditions): each finish, heat treatment and inspection is its own line.
  spec_bead_blast_cost: () => "Bead blast",
  spec_anodize_ii_cost: () => "Anodize, Type II",
  spec_anodize_iii_cost: () => "Hard anodize, Type III",
  spec_passivate_cost: () => "Passivation",
  spec_electropolish_cost: () => "Electropolish",
  spec_powder_coat_cost: () => "Powder coat",
  spec_plating_cost: () => "Plating",
  spec_stress_relief_cost: () => "Stress relief",
  spec_solution_age_cost: () => "Solution treat and age",
  spec_quench_temper_cost: () => "Quench and temper",
  spec_case_harden_cost: () => "Case hardening",
  spec_hip_cost: () => "HIP",
  spec_fai_as9102_cost: (q) => `First article report, AS9102, shared over ${qtyWord(q)}`,
  spec_cmm_report_cost: (q) => `CMM report, shared over ${qtyWord(q)}`,
  spec_full_100_cost: () => "100% inspection",
  spec_fine_finish_cost: () => "Grind or polish to the Ra",
};

function driverLabel(d: CostDriver, q: number): string {
  const f = DRIVER_LABEL[d.name];
  if (f) return f(q, d);
  return d.name.replace(/_cost$/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export interface CostLine {
  key: string;
  name: string;
  value: number;
  src: { kind: SrcKind; label: string };
  how: string;
  band: string;
}

/** The dollar drivers of one estimate, largest first, each with its own derivation. */
// Secondary ops a machine fit names (the engine's op keys), in words.
const OP_WORD: Record<string, string> = {
  stress_relief: "stress relief", sinter: "sintering", hip: "HIP", grinding: "grinding or polishing",
  bead_blast: "bead blasting", anodize_ii: "Type II anodizing", anodize_iii: "hard anodizing", passivate: "passivation",
  electropolish: "electropolishing", powder_coat: "powder coating", plating: "plating", solution_age: "solution treating and ageing",
  quench_temper: "quench and temper", case_harden: "case hardening", fai_as9102: "an AS9102 first article report",
  cmm_report: "a CMM report", full_100: "100% inspection",
};

export function opWord(op: string): string {
  return OP_WORD[op] ?? op.replace(/_/g, " ");
}

function driverLine(d: CostDriver, q: number, value: number): CostLine {
  const src = srcOf(d.provenance, d.rate_card);
  return {
    key: d.name,
    name: driverLabel(d, q),
    value,
    src,
    how: d.source,
    band: `${d.error_band_pct != null ? `±${trimNum(d.error_band_pct, 0)}%` : "no stated band"} · ${d.rate_card != null ? `rate from your rates v${d.rate_card}` : src.kind === "yours" ? "your value" : src.kind === "file" ? "measured from your file" : "typical value"}`,
  };
}

/** The lines that make up one estimate's price, largest first, each with its own derivation
 *  (ce-01): the engine's summing lines rounded to the cent, then a Rounding line when they
 *  need one to add up to the price shown. Keys are the lines' driver names. */
export function costLines(e: CostEstimate | null | undefined): CostLine[] {
  if (!e) return [];
  const items = e.line_items ?? {};
  if (!Object.keys(items).length) {
    // An estimate without its lines (older shapes): its dollar drivers, as they are.
    return e.drivers
      .filter((d) => d.unit === "$" && Number.isFinite(d.value))
      .sort((a, b) => b.value - a.value)
      .map((d) => driverLine(d, e.quantity, d.value));
  }
  const f = footLines(items, e.unit_cost_usd);
  const byName = new Map(e.drivers.map((d) => [d.name, d]));
  const folded = foldedTooling(e);
  const lines = f.lines
    .map((l) => {
      const d = byName.get(lineDriver(l.key));
      if (d && folded && l.key === "amortized_fixed") {
        // Priced before tooling was its own line: this one holds the setup and the tool's share.
        const tool = byName.get("tooling_cost");
        return { ...driverLine(d, e.quantity, l.cents / 100), name: `Setup and tooling, shared over ${qtyWord(e.quantity)}`, how: `${d.source}; ${tool?.source ?? ""} ÷ ${qtyWord(e.quantity)}` };
      }
      if (d) return driverLine(d, e.quantity, l.cents / 100);
      return { key: l.key, name: l.key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()), value: l.cents / 100, src: { kind: "typ" as const, label: "Typical" }, how: "", band: "no stated band" };
    })
    .sort((a, b) => b.value - a.value);
  if (f.roundingCents && f.isRounding) {
    lines.push({ key: ROUNDING_KEY, name: "Rounding", value: f.roundingCents / 100, src: { kind: "typ", label: "Arithmetic" }, how: roundingWords(f), band: "the lines rounded to the cent" });
  }
  return lines;
}

/** ce-18: what an outside price is. With no overhead or margin on the rates it is a should-cost (what
 *  making it costs a shop), not a supplier's quote, and it says so; otherwise it says what it adds. */
export function shouldCostWords(assumptions: readonly { name: string; value: number }[] | null | undefined): string {
  const v = (n: string) => assumptions?.find((a) => a.name === n)?.value ?? 0;
  const pct = (x: number) => `${Math.round(x * 1000) / 10}%`;
  const oh = v("overhead");
  const mg = v("margin");
  if (!oh && !mg) return "Outside prices are should-costs: what making it costs a shop, with no overhead or margin added (a supplier’s quote adds both; set yours on Rates).";
  return `Outside prices add ${pct(oh)} overhead and ${pct(mg)} margin from your rates.`;
}

/** "2 of 9 from your data": drivers grounded in your file, rates or machines. */
export function groundedCount(e: CostEstimate | null | undefined): { grounded: number; total: number } {
  const total = e?.drivers.length ?? 0;
  const grounded = (e?.drivers ?? []).filter((d) => srcOf(d.provenance).kind !== "typ").length;
  return { grounded, total };
}

/** The note under cost lines when the biggest line is a typical value. */
export function biggestTypicalNote(e: CostEstimate | null | undefined, where: string): { title: string; text: string } | null {
  const lines = costLines(e);
  if (!e || !lines.length) return null;
  const top = lines[0];
  if (top.src.kind !== "typ" || e.unit_cost_usd <= 0) return null;
  const share = top.value / e.unit_cost_usd;
  const word = share >= 0.45 && share <= 0.55 ? "half" : share > 0.55 ? "most" : `${Math.round(share * 100)}%`;
  const c = e.confidence;
  const range = c ? ` Range ${money(c.low_usd)}–${money(c.high_usd)} (±${trimNum(c.half_width_pct, 0)}%, ${c.validated ? "checked against your jobs" : "not yet checked against your jobs"}).` : "";
  return {
    title: `${top.name.split(",")[0]} is ${word} of the ${where} cost, and it's a typical value`,
    text: `${money(top.value)} of ${money(e.unit_cost_usd)}: ${top.how}.${range} Lead ${days(e.lead_time?.low_days, e.lead_time?.high_days)} from a queue model, not your schedule.`,
  };
}

/* ── the quantity chart ────────────────────────────────────────────────── */

export interface ChartLine {
  code: string;
  pts: string;
  stroke: string;
  w: number;
  dash: string;
  cx: number;
  cy: number | null;
  r: number;
}

export interface ChartModel {
  width: number;
  height: number;
  x: (q: number) => number;
  y: (v: number) => number;
  gridY: { y: number; label: string }[];
  gridX: { x: number; label: string }[];
  lines: ChartLine[];
  crossoverX: number | null;
  qFromX: (px: number) => number;
}

const NICE = [0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000, 300000];

export function chartModel(methods: Method[], qs: number[], q: number, selected: string | null, crossover: number | null): ChartModel {
  const width = 760;
  const top = 16;
  const bottom = 340;
  const left = 90;
  const right = 690;
  const priced = methods.filter(isPriced);
  const vals = priced.flatMap((m) => [...m.prices.values()].map((e) => e.unit_cost_usd)).filter((v) => v > 0);
  const lo = vals.length ? Math.min(...vals) * 0.8 : 1;
  const hi = vals.length ? Math.max(...vals) * 1.25 : 100;
  const lqMin = Math.log10(qs[0] ?? 1);
  const lqMax = Math.log10(qs[qs.length - 1] ?? 10);
  const span = lqMax - lqMin || 1;
  const x = (qq: number) => left + ((Math.log10(Math.max(qq, 1e-9)) - lqMin) / span) * (right - left);
  const y = (v: number) => top + ((Math.log(hi) - Math.log(Math.max(v, lo))) / (Math.log(hi) - Math.log(lo) || 1)) * (bottom - top);
  const gridY = NICE.filter((v) => v >= lo && v <= hi).map((v) => ({ y: y(v), label: "$" + v.toLocaleString("en-US") }));
  const gridX = qs.map((qq) => ({ x: x(qq), label: qtyWord(qq) }));
  const lines: ChartLine[] = priced.map((m) => {
    const isSel = m.code === selected;
    const draft = m.verdict === "bad";
    const pts = qs
      .filter((qq) => m.prices.has(qq))
      .map((qq) => `${x(qq).toFixed(1)},${y(m.prices.get(qq)!.unit_cost_usd).toFixed(1)}`)
      .join(" ");
    const p = priceAt(m, q);
    return {
      code: m.code,
      pts,
      stroke: isSel ? "#141414" : m.inHouse ? "#5B3FC4" : draft ? "#7A4FD6" : "#BFC5CC",
      w: isSel ? 3 : m.inHouse ? 2 : 1.6,
      dash: draft ? "5 5" : "none",
      cx: x(q),
      cy: p != null ? y(p) : null,
      r: isSel ? 6 : 3.5,
    };
  }).sort((a, b) => a.w - b.w);
  const crossoverX = crossover != null && crossover > (qs[0] ?? 0) && crossover < (qs[qs.length - 1] ?? 0) ? x(crossover) : null;
  const qFromX = (px: number) => {
    let best = qs[0] ?? q;
    for (const qq of qs) if (Math.abs(x(qq) - px) < Math.abs(x(best) - px)) best = qq;
    return best;
  };
  return { width, height: 400, x, y, gridY, gridX, lines, crossoverX, qFromX };
}

/** The model's own price for a method at ``target`` parts (ce-06): read from the structure
 *  kept with its priced estimates (fixed ÷ quantity + each part's lines, with the same
 *  learning), never a line drawn between two priced quantities. Null when the record was
 *  priced before the model was kept: then only "Price N" gives a number. */
export function modelPrice(m: Method, qs: number[], target: number): { value: number; est: CostEstimate } | null {
  const pts = qs.filter((qq) => m.prices.has(qq));
  if (!pts.length || !(target >= 1)) return null;
  const near = [...pts].sort((a, b) => Math.abs(Math.log(a / target)) - Math.abs(Math.log(b / target)));
  for (const q of near) {
    const est = m.prices.get(q)!;
    const value = unitCostAt(est, target);
    if (value != null) return { value, est };
  }
  return null;
}

/** The quantities to price with ``n`` added (the engine prices at most ``max``): the one
 *  whose neighbours sit closest together without it (in ratio) gives way, never the
 *  first, the last or ``n``. */
export function withQuantity(qs: number[], n: number, max = 6): number[] {
  const out = [...new Set([...qs.filter((x) => x > 0), Math.round(n)])].sort((a, b) => a - b);
  while (out.length > max) {
    let drop = -1;
    let best = Infinity;
    for (let i = 1; i < out.length - 1; i++) {
      if (out[i] === Math.round(n)) continue;
      const gap = Math.log(out[i + 1] / out[i - 1]);
      if (gap < best) {
        best = gap;
        drop = i;
      }
    }
    if (drop < 0) break;
    out.splice(drop, 1);
  }
  return out;
}

/** The priced quantity that pricing ``n`` would replace (the engine prices six at most), or null when ``n`` is added (ce-08). */
export function replacedBy(qs: number[], n: number, max = 6): number | null {
  const after = withQuantity(qs, n, max);
  const gone = qs.filter((x) => x > 0 && !after.includes(x));
  return gone.length ? gone[0] : null;
}

export function otherQtyNote(methods: Method[], qs: number[], raw: string): { on: boolean; text: string; value: number | null } {
  const n = Number.parseInt(raw, 10);
  const computed = `Computed at ${qs.map(qtyWord).join(", ").replace(/, ([^,]*)$/, " and $1")}.`;
  if (!(n > 0) || qs.includes(n)) return { on: false, text: computed, value: null };
  const workable = methods.filter(isWorkable);
  let best: Method | null = null;
  let bestP: { value: number; est: CostEstimate } | null = null;
  for (const m of workable) {
    const p = modelPrice(m, qs, n);
    if (p && (!bestP || p.value < bestP.value)) {
      best = m;
      bestP = p;
    }
  }
  if (!best || !bestP) {
    const priced = workable.some((m) => qs.some((qq) => m.prices.has(qq)));
    return { on: true, text: priced ? `Not priced at ${qtyWord(n)} yet: this record was priced before ScaleCAD kept its model, so there is no number to show.` : "Nothing priced.", value: null };
  }
  // The words add up: what the order pays once, shared over n, plus what each part adds.
  const model = bestP.est.qty_model!;
  const c = (bestP.est as { calibration?: { cost_factor?: number | null } | null }).calibration?.cost_factor;
  const once = onceAndEach(model, n).once * (typeof c === "number" && c > 0 ? c : 1);
  const each = bestP.value - once / n;
  const split = once > 0 ? `: ${money(once)} once for the order ÷ ${qtyWord(n)} + ${money(each)} a part` : "";
  return { on: true, text: `${money(bestP.value)} each by ${best.name.toLowerCase()} at ${qtyWord(n)}, from the model's own lines${split}.`, value: bestP.value };
}

/* ── machines (Shop lens) ──────────────────────────────────────────────── */

export interface MachineView {
  id: string;
  name: string;
  process: string;
  sub: string;
  tone: "ok" | "warn" | "bad" | "unk";
  verdict: string;
  cost: number | null;
  why: string;
  checks: string;
  envelope: [number, number, number] | null;
  method: Method | null;
}

function capNum(m: OwnedMachine, ...keys: string[]): number | null {
  for (const k of keys) {
    const v = m.capabilities?.[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

export function machineEnvelope(m: OwnedMachine): [number, number, number] | null {
  const x = capNum(m, "x", "bed_x", "platen_x");
  const y = capNum(m, "y", "bed_y", "platen_y");
  const z = capNum(m, "z", "daylight");
  if (x != null && y != null && z != null) return [x, y, z];
  const swing = capNum(m, "swing_dia", "swing_dia_mm");
  const between = capNum(m, "between_centers");
  if (swing != null && between != null) return [swing, swing, between];
  return null;
}

/** Sorted-dimension comparison of the measured part box with a declared work area. */
export function fitsEnvelope(part: readonly number[] | null, env: readonly number[] | null): boolean | null {
  if (!part || !env) return null;
  const a = [...part].sort((p, q) => p - q);
  const b = [...env].sort((p, q) => p - q);
  return a.every((v, i) => v <= b[i]);
}

function joinWords(xs: string[]): string {
  if (xs.length <= 1) return xs.join("");
  return `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

export function machineViews(machines: OwnedMachine[], methods: Method[], cost: CostReport | null, q: number, bbox: readonly number[] | null): MachineView[] {
  const verification = readVerification(cost);
  const cls = cost?.material_class ?? null;
  return machines.map((mc) => {
    const name = mc.name || methodName(mc.process);
    const method = methods.find((m) => m.code === mc.process) ?? null;
    const env = machineEnvelope(mc);
    const sizeOk = fitsEnvelope(bbox, env);
    const declared = (mc.materials ?? []).map((m) => m.toLowerCase());
    // The material this route is priced in (PLA for a filament printer): a machine
    // declared for it, or for its class, is set up for it, as the engine's fit reads it.
    const routeMat = method?.prices.get(q)?.material ?? method?.material ?? null;
    const fit = verification?.per_route?.[mc.process] ?? null;
    const fitsHere = !!fit && (fit.verdict === "makeable_in_house" || fit.verdict === "makeable_with_secondary_op") && (!fit.best_machine || fit.best_machine === mc.name);
    const materialOk = fitsHere ? true : cls ? declared.length === 0 ? null : declared.includes(cls) || (!!routeMat && declared.includes(routeMat.toLowerCase())) : null;
    const failures: FitFailure[] = fit?.failures ?? [];
    const kind = MACHINE_KIND[mc.process] ?? methodName(mc.process);
    const sub = [kind, mc.hourly_rate_usd != null ? `$${trimNum(mc.hourly_rate_usd, 2)}/h` : null, mc.max_workpiece_kg != null ? `${trimNum(mc.max_workpiece_kg, 0)} kg max` : null]
      .filter(Boolean)
      .join(" · ");
    const checkParts: string[] = [];
    if (sizeOk != null) checkParts.push(`Size ${sizeOk ? "✓" : "✗ too big"}`);
    if (fit && (fit.verdict === "makeable_in_house" || fit.verdict === "makeable_with_secondary_op") && fit.best_machine === mc.name) checkParts.push("weight ✓");
    if (materialOk != null && cls) checkParts.push(`material ${materialOk ? "✓" : "✗ not declared"}`);
    if (method && method.dfm === "fail") checkParts.push("shape ✗");
    let tone: MachineView["tone"] = "unk";
    let verdict = "Not checked";
    let why = "Fit wasn't evaluated in this check.";
    let price: number | null = null;
    if (method?.verdict === "out") {
      tone = "bad";
      verdict = "Ruled out";
      why = method.excludedReason ?? "Ruled out by the declared service conditions.";
    } else if (method?.verdict === "bad") {
      tone = "bad";
      verdict = "Can't";
      why = method.blockedReason ?? "Not makeable as drawn on this route.";
    } else if (materialOk === false && cls && !fitsHere) {
      tone = "warn";
      verdict = "Not set up";
      why = `Declared for ${joinWords(mc.materials ?? [])}, not ${routeMat ?? (MATERIAL_CLASS_LABEL[cls] ?? cls).toLowerCase()}.`;
    } else if (fitsHere && fit) {
      tone = "ok";
      verdict = "Can make";
      price = method ? priceAt(method, q) : null;
      why = env ? `Fits its ${env.map((n) => trimNum(n, 0)).join(" × ")} mm work area.` : "Clears every gate the engine checked.";
      // The machine's own post-processing the shop was assumed to do (never said either way) is said as an
      // assumption; any other step it needs afterwards is listed as a need.
      const assumed = fit.assumed_in_house ?? [];
      const after = (fit.secondary_ops ?? []).filter((op) => !assumed.includes(op));
      if (after.length) why += ` Needs ${joinWords(after.map(opWord))} afterwards.`;
      if (assumed.length) why += ` Assumes your shop does its own ${joinWords(assumed.map(opWord))}; change this in Your shop.`;
    } else if (fit?.verdict === "unknown" && failures.length && failures.every((f) => f.have == null)) {
      // Fits as far as it was declared; something it needs was never declared (a material, an op).
      tone = "warn";
      verdict = "Can't confirm";
      const shopOnly = failures.every((f) => f.gate === "secondary_op" || f.gate === "certification");
      why = shopOnly
        ? `Not declared on Your shop: ${joinWords(failures.map((f) => (f.gate === "certification" ? String(f.need ?? f.axis) : opWord(String(f.axis)))))}. Declare what you do in-house, send out or hold to confirm.`
        : `${failures.map(gapText).join(" · ")}. Declare it in Your shop to confirm.`;
    } else if (failures.length) {
      tone = "bad";
      verdict = "Doesn't fit";
      why = failures.map(gapText).join(" · ");
    } else if (fit && fit.best_machine && fit.best_machine !== mc.name) {
      tone = "unk";
      verdict = "Another machine";
      why = `Your ${fit.best_machine} is the one checked for this route.`;
    } else if (!method || method.prices.size === 0) {
      tone = "unk";
      verdict = "Not priced";
      why = cls ? `Its route isn't priced in ${(MATERIAL_CLASS_LABEL[cls] ?? cls).toLowerCase()}.` : "Its route isn't priced in this check.";
    }
    return {
      id: mc.id,
      name,
      process: mc.process,
      sub,
      tone,
      verdict,
      cost: price,
      why,
      checks: checkParts.join(" · "),
      envelope: env,
      method,
    };
  });
}

/* ── decide ────────────────────────────────────────────────────────────── */

export type Disposition = "inhouse" | "outside" | "acquire" | "redesign" | "supplier";

export interface DecideOption {
  id: string;
  kind: Disposition;
  label: string;
  sub: string;
  cost: number | null;
  off: boolean;
  /** The exact estimate the outcome records (process, material, quantity). */
  route: { process: string; material: string; quantity: number } | null;
}

function route(e: CostEstimate | undefined | null) {
  return e ? { process: e.process, material: e.material, quantity: e.quantity } : null;
}

export function decideOptions(methods: Method[], cost: CostReport | null, q: number, machinesDeclared: number): DecideOption[] {
  const opts: DecideOption[] = [];
  const workable = methods.filter((m) => isWorkable(m) && m.prices.has(q)).sort((a, b) => (priceAt(a, q) ?? 0) - (priceAt(b, q) ?? 0));
  const inHouse = workable.find((m) => m.inHouse) ?? null;
  if (inHouse) {
    const e = inHouse.prices.get(q)!;
    opts.push({ id: "inhouse", kind: "inhouse", label: "Make in-house", sub: `${inHouse.inHouse} · ${inHouse.short} ${e.material} · ${days(e.lead_time?.low_days, e.lead_time?.high_days)}`, cost: e.unit_cost_usd, off: false, route: route(e) });
  } else {
    const unconfirmed = methods.find((m) => m.fit?.verdict === "unknown" && m.fit.best_machine && m.verdict !== "bad" && m.verdict !== "out");
    const sub = unconfirmed
      ? `Can't confirm on your ${unconfirmed.fit!.best_machine}: ${unconfirmed.fit!.failures.map(gapText).join(" · ")}`
      : machinesDeclared
        ? "No machine of yours can make it as checked"
        : "No machines declared yet";
    opts.push({ id: "inhouse", kind: "inhouse", label: "Make in-house", sub, cost: null, off: true, route: null });
  }
  const outside = workable.filter((m) => m !== inHouse).slice(0, 2);
  outside.forEach((m, i) => {
    const e = m.prices.get(q)!;
    opts.push({ id: `outside-${i}`, kind: "outside", label: "Make outside", sub: `${m.name} · ${m.short} ${e.material} · ${days(e.lead_time?.low_days, e.lead_time?.high_days)}`, cost: e.unit_cost_usd, off: false, route: route(e) });
  });
  if (!outside.length) opts.push({ id: "outside-0", kind: "outside", label: "Make outside", sub: "Nothing can make it as drawn at this quantity", cost: null, off: true, route: null });
  const d = cost?.decision ?? null;
  const tooling = d?.tooling_process ? methods.find((m) => m.code === d.tooling_process) ?? null : null;
  const toolingAtQ = tooling?.prices.get(q) ?? null;
  const qs = quantitiesOf(cost);
  const qMax = qs[qs.length - 1];
  const toolingMax = tooling?.prices.get(qMax) ?? null;
  let acquireSub: string;
  if (tooling && d?.crossover_qty) acquireSub = `${tooling.name} pays back from about ${qtyWord(Math.round(d.crossover_qty))} parts`;
  else if (inHouse) acquireSub = `Not needed now: your ${inHouse.inHouse} can make it`;
  else acquireSub = "Add the capability to make it in-house";
  opts.push({ id: "acquire", kind: "acquire", label: "Acquire capability", sub: acquireSub, cost: null, off: false, route: route(toolingAtQ) });
  const blocked = methods.filter((m) => m.verdict === "bad" && m.members.length === 1);
  let redesignSub: string;
  if (tooling && d && !d.tooling_dfm_ready && toolingMax) redesignSub = `Fix what blocks ${tooling.name.toLowerCase()}: ${money(toolingMax.unit_cost_usd)} each at ${qtyWord(qMax)}`;
  else if (blocked.length) redesignSub = `Fix what blocks ${joinWords(blocked.slice(0, 3).map((m) => m.name.toLowerCase()))}`;
  else redesignSub = "Not needed: nothing is blocked as drawn";
  opts.push({ id: "redesign", kind: "redesign", label: "Redesign", sub: redesignSub, cost: null, off: false, route: tooling && !d?.tooling_dfm_ready ? route(toolingAtQ) : null });
  return opts;
}

/* ── the check's progress (X10) ────────────────────────────────────────── */

export type StepState = "done" | "now" | "wait" | "bad" | "skip";

export interface Step {
  t: string;
  d: string;
  state: StepState;
}

export interface ProgressInput {
  fileName: string;
  sample: boolean;
  validation: ValidationResult | null;
  cost: CostReport | null;
  costError: string | null;
  geometryInvalid: string | null;
  done: boolean;
  /** A step waiting on a busy server (busy-state.ts): "measure" (the probe or /validate) or "price"
   *  (/validate/cost); `live` while ScaleCAD is still asking. It reads "Waiting for room", never "Didn't finish". */
  busy?: { step: "measure" | "price"; live: boolean; text?: string } | null;
}

const WAITING_FOR_ROOM = "Waiting for room";

function ext(name: string): string {
  return (name.split(".").pop() ?? "").toUpperCase();
}

const ARCHETYPE: Record<string, string> = {
  prismatic_block: "Solid block",
  general_solid: "General solid",
  rotational: "Turned part",
  sheet: "Sheet part",
  thin_shell: "Thin shell",
  organic: "Organic shape",
};

export function measuredLine(v: ValidationResult): string {
  const g = v.geometry;
  const parts = [dimsText(g.bounding_box_mm), `${trimNum(g.volume_mm3 / 1000, 2)} cm³`, g.is_watertight ? "watertight" : "not watertight"];
  return parts.filter(Boolean).join(" · ");
}

export function progressSteps(p: ProgressInput): Step[] {
  const v = p.validation;
  const measuredBad = !!v && !v.geometry.is_watertight;
  // Busy is about the server, not the file: the waiting step says so, calmly, and nothing after it failed.
  // A request stopped on ScaleCAD's side says so in `text` ("Took too long on our side"), calmly too.
  const room = (live: boolean, text?: string): Pick<Step, "d" | "state"> => ({ d: text ?? WAITING_FOR_ROOM, state: live ? "now" : "wait" });
  const measureBusy = !v && p.busy?.step === "measure" ? room(p.busy.live, p.busy.text) : null;
  const priceBusy = !p.cost && p.busy?.step === "price" ? room(p.busy.live, p.busy.text) : null;
  if (p.sample) {
    return [
      { t: "Read and measure the shape", ...(measureBusy ?? { d: v ? measuredLine(v) : "Reading the shape now…", state: v ? "done" : "now" }) },
      { t: `Compare ${v ? v.process_scores.length : 21} ways to make it`, d: v ? `${methodName(v.best_process)} has the highest design score` : "Waiting", state: v ? "done" : "wait" },
      { t: "Price it and list what’s uncertain", ...(priceBusy ?? { d: p.cost ? `${p.cost.estimates.length} prices · ${p.cost.saved ? `record ${shortId(p.cost.saved.id)}` : "not saved"}` : p.costError ? "Didn’t finish" : v ? "Pricing now…" : "Waiting", state: p.cost ? "done" : p.costError ? "bad" : v ? "now" : "wait" }) },
    ];
  }
  const verification = readVerification(p.cost);
  const received: Step = { t: "Received", d: `${p.fileName} · ${ext(p.fileName)}`, state: "done" };
  if (measuredBad || p.geometryInvalid) {
    const edges = p.geometryInvalid ?? "not a closed solid";
    return [
      received,
      { t: "Measured", d: v ? `${dimsText(v.geometry.bounding_box_mm) ?? ""} · ${edges}`.replace(/^ · /, "") : edges, state: "bad" },
      { t: "Process chosen", d: "Not computed", state: "skip" },
      { t: "Machines checked", d: "Not computed", state: "skip" },
      { t: "Record saved", d: "Not computed", state: "skip" },
    ];
  }
  const routing = p.cost?.routing;
  const routed = routing ? `${ARCHETYPE[routing.archetype] ?? routing.archetype.replace(/_/g, " ")} → ${methodShort(routing.recommended_process)} · confidence ${routing.confidence.toFixed(2)}` : p.cost ? `${methodName(p.cost.decision?.make_now_process)} is the cheapest route` : "";
  let machines = "No machines declared";
  if (verification) {
    if (verification.best_machine) machines = `${verification.best_machine} clears every check`;
    else if (verification.inventory_declared) machines = "None of your machines clears every check";
  }
  const costFailed = !!p.costError && !priceBusy;
  return [
    received,
    { t: "Measured", ...(measureBusy ?? { d: v ? measuredLine(v) : "Measuring the shape…", state: v ? "done" : "now" }) },
    { t: "Process chosen", ...(priceBusy ?? { d: p.cost ? routed : costFailed ? "Didn’t finish" : v ? "Choosing the process and pricing…" : "Waiting", state: p.cost ? "done" : costFailed ? "bad" : v ? "now" : "wait" }) },
    { t: "Machines checked", d: p.cost ? machines : costFailed ? "Not computed" : "Waiting", state: p.cost ? "done" : costFailed ? "skip" : "wait" },
    { t: "Record saved", d: p.cost ? p.cost.saved ? `Record ${shortId(p.cost.saved.id)}` : "Not saved: record keeping is off" : costFailed ? "Not computed" : "Waiting", state: p.cost ? (p.cost.saved ? "done" : "skip") : costFailed ? "skip" : "wait" },
  ];
}

/* ── answers (the Ask dock and the search palette) ─────────────────────── */

export interface Answer {
  tag: "Computed" | "Not computable";
  title: string;
  rows: { k: string; v: string }[];
  text: string;
  link?: { label: string; href: string };
}

export function routesAnswer(methods: Method[], q: number): Answer | null {
  const ranked = methods.filter(isPriced).filter((m) => m.prices.has(q)).sort((a, b) => priceAt(a, q)! - priceAt(b, q)!);
  if (!ranked.length) return null;
  const rows = ranked.slice(0, 3).map((m) => ({
    k: `${m.inHouse ? `Your ${m.inHouse}` : m.name} · ${m.short} ${m.prices.get(q)!.material}${m.verdict === "bad" ? ", after redesign" : ""}`,
    v: money(priceAt(m, q)),
  }));
  let text = "Only one route is priced at this quantity.";
  if (ranked.length > 1) {
    const a = ranked[0].prices.get(q)!;
    const b = ranked[1].prices.get(q)!;
    const la = new Map(costLines(a).map((l) => [l.key, l]));
    let best: { name: string; da: number; db: number } | null = null;
    for (const lb of costLines(b).filter((l) => l.key !== ROUNDING_KEY)) {
      const l = la.get(lb.key);
      const da = l?.value ?? 0;
      if (!best || Math.abs(lb.value - da) > Math.abs(best.db - best.da)) best = { name: lb.name, da, db: lb.value };
    }
    text = best ? `Biggest difference: ${best.name.toLowerCase()}, ${money(best.da)} against ${money(best.db)}.` : "The two cheapest routes differ in total only.";
  }
  return { tag: "Computed", title: `Routes at ${qtyWord(q)}`, rows, text };
}

export function verdictAnswer(methods: Method[], validation: ValidationResult | null, cost: CostReport | null, problems: { severity: string }[] = []): Answer {
  const singles = methods.filter((m) => m.members.length === 1);
  const can = singles.filter((m) => (m.verdict === "ok" || m.verdict === "warn") && m.runsClass !== false);
  const blocked = singles.filter((m) => m.verdict === "bad").map((m) => m.name);
  const gp = singles.find((m) => m.geometryPick);
  const rows = [{ k: "Can make", v: `${can.length} of ${singles.length} processes` }];
  if (gp) rows.push({ k: "Highest design score", v: `${gp.name}, DFM ${gp.score?.toFixed(1) ?? "—"}` });
  if (cost?.routing) rows.push({ k: "Typical for the shape", v: `${methodName(cost.routing.recommended_process)}, confidence ${cost.routing.confidence.toFixed(1)}` });
  if (blocked.length) rows.push({ k: "Blocked", v: joinWords([...new Set(blocked)].slice(0, 4)) });
  const text = [cost?.routing?.reasoning, `${problemWords(problems).replace(/^./, (c) => c.toUpperCase())}.`].filter(Boolean).join(" ");
  return { tag: "Computed", title: "Why this verdict", rows, text };
}

export function methodAnswer(m: Method, q: number, materialClass: string | null): Answer {
  const rows = [{ k: "Verdict", v: VERDICT_LABEL[m.verdict] }];
  if (m.score != null) rows.push({ k: "DFM score", v: m.score.toFixed(1) });
  const p = priceAt(m, q);
  if (p != null && m.verdict !== "out") rows.push({ k: `Each at ${qtyWord(q)}`, v: money(p) });
  return { tag: "Computed", title: m.name, rows, text: methodWhy(m, materialClass) };
}

export function leadAnswer(methods: Method[], q: number): Answer | null {
  const c = cheapestAt(methods, q);
  if (!c) return null;
  const rows = [{ k: c.name, v: days(c.prices.get(q)!.lead_time?.low_days, c.prices.get(q)!.lead_time?.high_days) }];
  const ih = methods.find((m) => m.inHouse && m.prices.has(q) && m !== c);
  if (ih) rows.push({ k: `Your ${ih.inHouse}`, v: days(ih.prices.get(q)!.lead_time?.low_days, ih.prices.get(q)!.lead_time?.high_days) });
  return { tag: "Computed", title: `Lead time at ${qtyWord(q)}`, rows, text: "From a queue model: queue, production, finishing and shipping. Not your scheduler." };
}

export function driversAnswer(m: Method | null, q: number): Answer | null {
  const e = m?.prices.get(q);
  if (!m || !e) return null;
  const lines = costLines(e);
  const g = groundedCount(e);
  return {
    tag: "Computed",
    title: `Cost drivers, ${m.inHouse ?? m.name} at ${qtyWord(q)}`,
    rows: lines.slice(0, 4).map((l) => ({ k: l.name, v: money(l.value) })),
    text: `${g.grounded} of ${g.total} cost inputs come from your file, your shop or you. The cost breakdown has every line and its formula.`,
  };
}

export const REFUSAL: Answer = {
  tag: "Not computable",
  title: "Not in the model",
  rows: [],
  text: "ScaleCAD prices from geometry, materials and rates, not from market behaviour. Ask about processes, cost drivers, lead time, materials or quantity.",
};

export type AskRoute = { kind: "method"; code: string } | { kind: "lead" } | { kind: "drivers" } | { kind: "routes"; qty: number | null } | { kind: "why" } | { kind: "saved" } | { kind: "refuse" };

/** Keyword routing of a typed ask to an answer this part's results can give. */
export function routeAsk(text: string, methods: Method[]): AskRoute {
  const t = text.toLowerCase();
  const num = t.match(/(\d[\d,]*)\s*(k\b)?/);
  const qty = num ? Number(num[1].replace(/,/g, "")) * (num[2] ? 1000 : 1) : null;
  const alias: [RegExp, string][] = [
    [/\blathe|turn(ing|ed)?\b/, "cnc_turning"],
    [/\b5[- ]?axis\b/, "cnc_5axis"],
    [/\b3[- ]?axis|\bmill(ing)?\b|\bcnc\b/, "cnc_3axis"],
    [/\bedm\b/, "wire_edm"],
    [/\bmold(ing)?\b|\binjection\b/, "injection_molding"],
    [/\bsheet\b/, "sheet_metal"],
    [/\bforg/, "forging"],
    [/\bsand\b/, "sand_casting"],
    [/\bdie[- ]cast/, "die_casting"],
    [/\binvestment\b/, "investment_casting"],
    [/\bfdm\b|\bfilament\b/, "fdm"],
    [/\bsla\b/, "sla"],
    [/\bdlp\b|\bresin\b/, "dlp"],
    [/\bmjf\b/, "mjf"],
    [/\bsls\b|\bnylon\b/, "sls"],
    [/\bbinder\b/, "binder_jetting"],
  ];
  for (const [re, code] of alias) if (re.test(t) && methods.some((m) => m.code === code)) return { kind: "method", code };
  if (/lead|days|when|how long|deliver/.test(t)) return { kind: "lead" };
  if (/driver|labor|labour|breakdown|why.*cost|cost.*why/.test(t)) return { kind: "drivers" };
  if (/saved|decision|record|previous|compare/.test(t)) return { kind: "saved" };
  if (qty != null || /route|cheap|price|cost/.test(t)) return { kind: "routes", qty };
  if (/why|verdict|make it|makeable/.test(t)) return { kind: "why" };
  return { kind: "refuse" };
}

export function nearestComputed(qs: number[], qty: number | null, fallback: number): number {
  if (qty == null || !qs.length) return fallback;
  return qs.reduce((b, qq) => (Math.abs(Math.log(qq) - Math.log(qty)) < Math.abs(Math.log(b) - Math.log(qty)) ? qq : b), qs[0]);
}
