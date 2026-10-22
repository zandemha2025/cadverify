import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { Comparison, FactorEntry, Stats, Summary } from "./api.ts";
import { MIN_PARTS, MIN_PER_METHOD, absPct, factorWord, actualLine, changeWord, contextLine, effectWord, hoursWord, partLines, pctWord, rangeWord, summaryLine, whyNot } from "./words.ts";

const backend = (p: string) => readFileSync(new URL(`../../../../../backend/${p}`, import.meta.url), "utf8");

test("thresholds match the backend", () => {
  assert.equal(Number(/^MIN_REAL_RECORDS = (\d+)$/m.exec(backend("src/services/groundtruth_service.py"))?.[1]), MIN_PARTS);
  assert.equal(Number(/^MIN_RESIDUALS = (\d+)$/m.exec(backend("src/costing/groundtruth.py"))?.[1]), MIN_PER_METHOD);
});

test("the part page line reads like the brief", () => {
  assert.equal(actualLine("hours", { actual: 4.1, estimate: 4.4, low: 2.2, high: 6.6, error_pct: 7.32, inside: true }), "Your actual: 4.1 h, ScaleCAD 4.4 h (+7%)");
  assert.equal(actualLine("cost", { actual: 36, estimate: 40, low: 20, high: 60, error_pct: 11.1, inside: true }), "Your actual: $36.00 each, ScaleCAD $40.00 (+11%)");
  assert.equal(rangeWord("hours", { actual: 8, estimate: 4.4, low: 2.2, high: 6.6, error_pct: -45, inside: false }), "Outside ScaleCAD’s range, 2.2 h–6.6 h");
  assert.equal(rangeWord("hours", { actual: 8, estimate: 4.4, low: null, high: null, error_pct: -45, inside: null }), null);
});

test("numbers", () => {
  assert.equal(hoursWord(0.42), "25 min");
  assert.equal(hoursWord(0.0015), "5 s");
  assert.equal(hoursWord(0.0654), "3.9 min");
  assert.equal(hoursWord(12), "12 h");
  assert.equal(hoursWord(1234.4), "1,234 h");
  assert.equal(pctWord(-12.4), "−12%");
  assert.equal(pctWord(0.3), "0%");
  assert.equal(absPct(-13.6), "14%");
  assert.equal(factorWord(0.8796), "−12% (× 0.88)");
});

const stats = (n: number, parts: number, med = 14): Stats => ({ n, parts, median_abs_pct: med, median_pct: med, worst_pct: 38, worst: null, inside: n, with_range: n, enough: parts >= 8 });
const summary = (parts: number, extra: Partial<Summary> = {}): Summary => ({
  parts, actuals: parts, compared: parts, not_compared: 0, test: 0, min_parts: 8, min_per_method: 3, enough: parts >= 8,
  hours: stats(parts, parts), cost: stats(0, 0), per_process: [], ...extra,
});

test("too few parts is said plainly; eight or more is a fair picture", () => {
  assert.equal(summaryLine(summary(3)), "3 parts with actuals: not enough to say how accurate ScaleCAD is for you; 8 or more give a fair picture.");
  assert.equal(summaryLine(summary(1)), "1 part with actuals: not enough to say how accurate ScaleCAD is for you; 8 or more give a fair picture.");
  assert.equal(summaryLine(summary(9)), "Checked against your real numbers on 9 parts: machine hours within 14% (median).");
  assert.equal(summaryLine(summary(0, { actuals: 0, test: 4 })), "Only test rows so far. Real actuals are compared here.");
  assert.equal(summaryLine(summary(0, { actuals: 0 })), "No actuals matched to your parts yet.");
});

const entry = (e: Partial<FactorEntry>): FactorEntry => ({ n: 9, parts: 9, factor: 0.88, before_pct: 13.6, after_pct: 1.2, offer: true, why: "offer", ...e });

test("what a calibration would change, and why not", () => {
  assert.equal(changeWord("cnc_3axis", "hours", 0.88), "Your 3-axis milling runs 12% faster than ScaleCAD’s typical estimate");
  assert.equal(changeWord("fdm", "hours", 1.2), "Your filament printing takes 20% longer than ScaleCAD’s typical estimate");
  assert.equal(changeWord("cnc_turning", "cost", 1.05), "Your turning costs 5% more than ScaleCAD’s estimate");
  assert.equal(effectWord(entry({})), "Median error 14% now, 1% with it, on 9 parts.");
  assert.equal(whyNot(entry({ why: "org_few", offer: false }), "hours", 3), "8 parts with actuals are needed before a calibration is applied; you have 3.");
  assert.match(whyNot(entry({ why: "out_of_range", factor: 6 }), "hours", 9), /6× ScaleCAD’s\. Check the column is per part/);
  assert.equal(whyNot(entry({ why: "few", n: 2 }), "cost", 9), "2 actuals with costs; 3 or more are needed for this method.");
});

test("part lines put real numbers before test ones and say the context", () => {
  const row = (test: boolean): Comparison => ({
    id: String(test), part_key: "k", file_name: "a.step", part_number: null, record_id: "r", process: "cnc_3axis", quantity: 25, machine: "Haas VF-2",
    date: "2026-03-14", reference: "J-118", test, hours: { actual: 4.1, estimate: 4.4, low: 2.2, high: 6.6, error_pct: 7.3, inside: true }, cost: null, note: null, calibrated_record: false,
  });
  const lines = partLines([row(true), row(false)]);
  assert.equal(lines[0].row.test, false);
  assert.equal(contextLine(row(false)), "3-axis milling · 25 parts · on Haas VF-2 · J-118 · 14 Mar 2026");
  assert.match(contextLine(row(true)), /test numbers$/);
});
