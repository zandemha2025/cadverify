/**
 * The words for "checked against your real numbers": one line per actual, the
 * summary with its honest thresholds, and what a calibration would change.
 * Pure (type imports only), so it runs under `node --test`.
 */
import { processLabel, processName } from "../process-names.ts";
import type { Comparison, FactorEntry, HourLine, Metric, Proposal, Stats, Summary } from "./api.ts";

/** Parts with actuals before ScaleCAD's accuracy for you is a fair picture (groundtruth_service.MIN_REAL_RECORDS). */
export const MIN_PARTS = 8;
/** Actuals a method needs before its own figure says much (costing/groundtruth.MIN_RESIDUALS). */
export const MIN_PER_METHOD = 3;

const MINUS = "−";

export function trim(n: number, digits = 1): string {
  const s = n.toFixed(digits);
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}

/** 0.0015 → "5 s", 0.42 → "25 min", 4.1 → "4.1 h", 1234 → "1,234 h". */
export function hoursWord(h: number | null | undefined): string {
  if (h == null || !Number.isFinite(h)) return "—";
  if (h * 60 < 1) return `${Math.max(1, Math.round(h * 3600))} s`;
  if (h < 1) return `${trim(h * 60, h * 60 < 10 ? 1 : 0)} min`;
  if (h < 100) return `${trim(h, 1)} h`;
  return `${Math.round(h).toLocaleString("en-US")} h`;
}

export function moneyWord(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const s = abs >= 1000 ? Math.round(abs).toLocaleString("en-US") : abs.toFixed(2);
  return `${v < 0 ? MINUS : ""}$${s}`;
}

/** +7.3 → "+7%", -12.4 → "−12%", 0.2 → "0%". */
export function pctWord(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "—";
  const r = Math.round(p);
  if (r === 0) return "0%";
  return `${r > 0 ? "+" : MINUS}${Math.abs(r)}%`;
}

/** A median error by size: 13.6 → "14%". */
export function absPct(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return "—";
  return `${Math.round(Math.abs(p))}%`;
}

export function metricValue(kind: "hours" | "cost", v: number | null | undefined): string {
  return kind === "hours" ? hoursWord(v) : moneyWord(v);
}

/** "Your actual: 4.1 h, ScaleCAD 4.4 h (+7%)". */
export function actualLine(kind: "hours" | "cost", m: Metric): string {
  const each = kind === "cost" ? " each" : "";
  // The printed numbers and a % a calculator gets from them, when the server gives them (ce-12).
  if (m.shown?.error) return `Your actual: ${m.shown.actual}${each}, ScaleCAD ${m.shown.estimate} (${m.shown.error})`;
  return `Your actual: ${metricValue(kind, m.actual)}${each}, ScaleCAD ${metricValue(kind, m.estimate)} (${pctWord(m.error_pct)})`;
}

/** Inside / outside the range ScaleCAD stated, with that range. */
export function rangeWord(kind: "hours" | "cost", m: Metric): string | null {
  if (m.inside == null || m.low == null || m.high == null) return null;
  const r = `${metricValue(kind, m.low)}–${metricValue(kind, m.high)}`;
  return m.inside ? `Inside ScaleCAD’s range, ${r}` : `Outside ScaleCAD’s range, ${r}`;
}

export function partsWord(n: number): string {
  return `${n} ${n === 1 ? "part" : "parts"}`;
}

/** The headline for a set of comparisons, honest about how many parts it rests on. */
export function summaryLine(s: Summary | null): string {
  if (!s) return "";
  if (s.parts === 0) {
    if (s.actuals > 0) return `${s.actuals} ${s.actuals === 1 ? "actual" : "actuals"} matched, none comparable with ScaleCAD’s estimates yet.`;
    return s.test ? "Only test rows so far. Real actuals are compared here." : "No actuals matched to your parts yet.";
  }
  if (!s.enough) {
    return `${partsWord(s.parts)} with actuals: not enough to say how accurate ScaleCAD is for you; ${s.min_parts} or more give a fair picture.`;
  }
  const bits: string[] = [];
  if (s.hours.n) bits.push(`machine hours within ${absPct(s.hours.median_abs_pct)}`);
  if (s.cost.n) bits.push(`cost within ${absPct(s.cost.median_abs_pct)}`);
  return `Checked against your real numbers on ${partsWord(s.parts)}: ${bits.join(", ")} (median).`;
}

/** "Median 14% on 9 parts · worst +38% · 8 of 9 inside ScaleCAD's range". */
export function statsLine(st: Stats): string {
  if (!st.n) return "No actuals";
  const bits = [`Median ${absPct(st.median_abs_pct)} on ${partsWord(st.parts)}`, `worst ${pctWord(st.worst_pct)}`];
  if (st.with_range) bits.push(`${st.inside} of ${st.with_range} inside ScaleCAD’s range`);
  return bits.join(" · ");
}

/** Which way ScaleCAD leans for a method: "ScaleCAD runs 9% high". */
export function leanWord(st: Stats): string | null {
  if (!st.n || st.median_pct == null || Math.abs(st.median_pct) < 1) return null;
  return `ScaleCAD runs ${absPct(st.median_pct)} ${st.median_pct > 0 ? "high" : "low"}`;
}

export function basisWord(b: string | null | undefined): string {
  switch (b) {
    case "file_hash":
      return "file hash";
    case "part_number":
      return "part number";
    case "file_name":
      return "file name";
    case "chosen":
      return "chosen by you";
    default:
      return "";
  }
}

/* ------------------------------------------------------------------ */
/*  Calibration                                                        */
/* ------------------------------------------------------------------ */

function lowerMethod(process: string): string {
  const n = processName(process);
  return /^[A-Z][a-z]/.test(n) ? n[0].toLowerCase() + n.slice(1) : n;
}

/** "Your 3-axis milling runs 12% faster than ScaleCAD's typical estimate". */
export function changeWord(process: string, kind: "hours" | "cost", factor: number): string {
  const d = Math.round(Math.abs(factor - 1) * 100);
  const m = lowerMethod(process);
  if (kind === "hours") return factor < 1 ? `Your ${m} runs ${d}% faster than ScaleCAD’s typical estimate` : `Your ${m} takes ${d}% longer than ScaleCAD’s typical estimate`;
  return factor < 1 ? `Your ${m} costs ${d}% less than ScaleCAD’s estimate` : `Your ${m} costs ${d}% more than ScaleCAD’s estimate`;
}

/**
 * The calibration's lead line for the state it's in (ce-12): no matched actuals,
 * matched but too few (with each method's count against what it needs), or what to change.
 */
export function calibrationLead(p: Proposal, hasOffer: boolean): string {
  if (!p.processes.length) return "Nothing to calibrate yet: no actual matches a checked part. Log a job against a part, or import actuals with a file name or part number.";
  if (!p.enough) {
    const counts = p.processes.map((x) => `${methodWord(x.process)} has ${Math.max(x.hours.n, x.cost.n)}`).join(", ");
    return `${partsWord(p.parts)} with actuals. A calibration needs ${p.min_parts} parts or more, and ${p.min_per_method} actuals for each method it changes (${counts}).`;
  }
  return hasOffer
    ? "What your actuals say ScaleCAD should change. Each figure is checked part by part: the part’s own actual never grades the factor fitted on it."
    : "Your actuals don’t support a change for any method right now.";
}

/** 0.8796 → "−12% (× 0.88)". */
export function factorWord(f: number): string {
  return `${pctWord((f - 1) * 100)} (× ${trim(f, 2)})`;
}

/** "Median error 14% now, 2% with it. Each part checked with a factor fitted on your other parts." */
export function effectWord(e: FactorEntry): string | null {
  if (e.before_pct == null || e.after_pct == null) return null;
  return `Median error ${absPct(e.before_pct)} now, ${absPct(e.after_pct)} with it, on ${partsWord(e.parts)}.`;
}

/** Why a method has no change to apply, in plain words. */
export function whyNot(e: FactorEntry, kind: "hours" | "cost", orgParts: number, minParts = MIN_PARTS): string {
  const what = kind === "hours" ? "machine hours" : "costs";
  switch (e.why) {
    case "few":
    case "none":
      return `${e.n} ${e.n === 1 ? "actual" : "actuals"} with ${what}; ${MIN_PER_METHOD} or more are needed for this method.`;
    case "out_of_range":
      return e.factor != null && e.factor > 1
        ? `Your ${what} are ${trim(e.factor, 1)}× ScaleCAD’s. Check the column is per part, not for the whole order, and in the right unit.`
        : `Your ${what} are ${trim(1 / (e.factor || 1), 1)}× lower than ScaleCAD’s. Check the column is per part and in the right unit.`;
    case "no_change":
      return `Within 3% of your actuals: nothing to change.`;
    case "no_better":
      return `One factor wouldn’t make ScaleCAD more accurate here: your actuals vary more than they lean one way.`;
    case "org_few":
      return `${minParts} parts with actuals are needed before a calibration is applied; you have ${orgParts}.`;
    default:
      return "";
  }
}

export function methodWord(process: string | null | undefined): string {
  return process ? processLabel(process) : "No method";
}

/** The comparisons a part page shows, newest first, real before test. */
export function partLines(rows: Comparison[]): { kind: "hours" | "cost"; text: string; range: string | null; row: Comparison }[] {
  const out: { kind: "hours" | "cost"; text: string; range: string | null; row: Comparison }[] = [];
  for (const r of [...rows].sort((a, b) => Number(a.test) - Number(b.test))) {
    if (r.hours) out.push({ kind: "hours", text: actualLine("hours", r.hours), range: rangeWord("hours", r.hours), row: r });
    if (r.cost) out.push({ kind: "cost", text: actualLine("cost", r.cost), range: rangeWord("cost", r.cost), row: r });
  }
  return out;
}

/** One setup, labor or inspection line of an actual: "Labor a part: yours 24.00 min, ScaleCAD 30.00 min · 30.00 min ÷ 24.00 min − 1 = +25.0%". */
export function hourLineWord(l: HourLine): string {
  if (!l.shown?.formula) return `${l.label}: yours ${hoursWord(l.actual)}${l.note ? ` · ${l.note}` : ""}`;
  return `${l.label}: yours ${l.shown.actual}, ScaleCAD ${l.shown.estimate} · ${l.shown.formula}`;
}

/** Which rates the compared costs were priced at, and the rows left out for older rates. */
export function ratesWord(s: Summary | null): string | null {
  if (!s) return null;
  const bits: string[] = [];
  const cards = s.rates_priced ?? [];
  if (cards.length === 1) bits.push(`Costs compared at ${cards[0] ? `your rates v${cards[0]}` : "typical rates (v0)"}.`);
  else if (cards.length > 1) bits.push(`Costs compared at rates ${cards.map((v) => `v${v}`).join(", ")}.`);
  const x = s.rates_excluded ?? 0;
  if (x) bits.push(`${x} ${x === 1 ? "cost isn’t" : "costs aren’t"} graded: ${x === 1 ? "its record was" : "their records were"} priced before your current rates. Re-check ${x === 1 ? "that part" : "those parts"} to compare.`);
  return bits.length ? bits.join(" ") : null;
}

/** "3-axis milling, 25 parts, job J-118, 14 Mar 2026". */
export function contextLine(r: Comparison): string {
  const bits = [methodWord(r.process)];
  if (r.quantity) bits.push(`${r.quantity.toLocaleString("en-US")} ${r.quantity === 1 ? "part" : "parts"}`);
  if (r.machine) bits.push(`on ${r.machine}`);
  if (r.reference && !/STAND-IN/i.test(r.reference)) bits.push(r.reference);
  if (r.date) bits.push(dateWord(r.date));
  if (r.test) bits.push("test numbers");
  return bits.join(" · ");
}

export function dateWord(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`;
}
