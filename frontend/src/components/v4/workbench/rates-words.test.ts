/**
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/workbench/rates-words.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { CostReport } from "@/lib/api";
import { ratesName, summaryWithRates } from "./rates-words.ts";

const SUMMARY = "ScaleCAD — pocket-block.step\nMake by 3-axis milling / Mild Steel at quantity 100\n  qty 100: 3-axis milling — $36.69/unit";

test("ce-20: the email summary of a record priced at v0 after v1 was published carries the caveat", () => {
  const out = summaryWithRates(SUMMARY, { priced: 0, current: 1, out_of_date: true, text: "Priced at rates v0; your rates are v1." });
  assert.equal(out.split("\n")[1], "Out of date: priced at rates v0; your rates are v1. Re-cost before quoting.");
  assert.equal(out.split("\n")[0], "ScaleCAD — pocket-block.step");
  assert.equal(out.split("\n").length, 4);
});

test("a current record names the rates it was priced at", () => {
  const out = summaryWithRates(SUMMARY, { priced: 1, current: 1, out_of_date: false, text: "Priced at your rates v1." });
  assert.equal(out.split("\n")[1], "Priced at your rates v1.");
  assert.equal(summaryWithRates("", { priced: 1, current: 1, out_of_date: false, text: "x" }), "");
  assert.equal(summaryWithRates(SUMMARY, null), SUMMARY);
});

test("ratesName: a shop profile, the org's card, or typical", () => {
  assert.equal(ratesName({ rate_card: { version: 1, changed: { labor_rate: 58 }, source: "" } } as unknown as CostReport, null), "your rates v1");
  assert.equal(ratesName({} as CostReport, null), "typical rates");
  assert.equal(ratesName({} as CostReport, "Acme"), "Acme");
});
