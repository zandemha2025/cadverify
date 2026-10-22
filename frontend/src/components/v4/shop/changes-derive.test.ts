import assert from "node:assert/strict";
import test from "node:test";

import { ASSET_NAMES, diffCard, initials, noteLines, personName, pipeline } from "./changes-derive.ts";
import type { Assumption } from "./shop-api.ts";

const v0: Assumption[] = [
  { name: "labor_rate", value: 35, unit: "$/hr", provenance: "DEFAULT", source: "" },
  { name: "margin", value: 0, unit: "frac", provenance: "DEFAULT", source: "" },
  { name: "overhead", value: 0.1, unit: "frac", provenance: "USER", source: "a quote override, not the card" },
];

test("a draft is compared with the default v0 values a check recorded", () => {
  const draft = { global: { labor_rate: 42, margin: 0, overhead: 0, ship_days: 4 } };
  assert.deepEqual(diffCard(draft, { assumptions: v0 }), [{ key: "labor_rate", name: "Labor, loaded shop floor", from: "$35.00/h", to: "$42.00/h" }]);
});

test("a draft is compared with the governed card in effect, material prices included", () => {
  const base = { global: { labor_rate: 40, ship_days: 3 }, material_prices: { "@polymer": 7 } };
  const draft = { global: { labor_rate: 40, ship_days: 5 }, material_prices: { "@polymer": 7, "6061-T6 Aluminum": 9 } };
  assert.deepEqual(diffCard(draft, { payload: base }).map((r) => [r.key, r.from, r.to]), [
    ["ship_days", "3 days", "5 days"],
    ["material_prices", "1", "2"],
  ]);
  assert.deepEqual(diffCard(null, { payload: null, assumptions: null }), []);
});

test("pipeline stages follow the request status", () => {
  assert.deepEqual(pipeline("proposed", 1).map((s) => `${s.label}:${s.state}`), ["Proposed:done", "In review:cur", "Approve:todo", "Publish v1:todo"]);
  assert.deepEqual(pipeline("approved", 1).map((s) => s.label), ["Proposed", "Reviewed", "Approved", "Published v1"]);
  assert.deepEqual(pipeline("rejected", null).map((s) => s.state), ["done", "bad"]);
});

test("people: you, a member's email, or a former member", () => {
  const emails = new Map([[7, "ana.ruiz@acme.com"]]);
  assert.equal(personName(3, 3, emails), "you");
  assert.equal(personName(7, 3, emails), "ana.ruiz@acme.com");
  assert.equal(personName(9, 3, emails), "a former member");
  assert.equal(initials("ana.ruiz@acme.com"), "AR");
  assert.equal(initials("you"), "You");
  assert.deepEqual(noteLines("Labor $35 → $42\n\nToo high for Q4 "), ["Labor $35 → $42", "Too high for Q4"]);
});

test("ce-13: a draft's changes beyond labor are listed for review", async () => {
  const { changeRows, approvalRule } = await import("./changes-derive.ts");
  const rows = changeRows([
    { path: "global.labor_rate", from: 35, to: 58 },
    { path: "global.overhead", from: 0, to: 0.15 },
    { path: "process.cnc_3axis.machine_rate", from: 75, to: 82 },
    { path: "material_prices.Mild Steel", from: null, to: 2.4 },
  ]);
  assert.deepEqual(rows.map((r) => [r.name, r.from, r.to]), [
    ["Labor, loaded shop floor", "$35.00/h", "$58.00/h"],
    ["Overhead", "0%", "15%"],
    ["3-axis milling machine rate", "$75.00/h", "$82.00/h"],
    ["Mild Steel price", "typical", "$2.40/kg"],
  ]);
  // the proposer waits for another admin when there is one; a sole admin self-approves
  assert.equal(approvalRule({ mine: true, admin: true, admins: 2 }), "other-admin");
  assert.equal(approvalRule({ mine: true, admin: true, admins: 1 }), "self");
  assert.equal(approvalRule({ mine: false, admin: true, admins: 2 }), "approve");
  assert.equal(approvalRule({ mine: false, admin: false, admins: 2 }), "not-admin");
});

test("ce-13 / ce-17: a draft takes overhead and margin as percents, machine rates and material prices", async () => {
  const { applyDraft, draftFormFrom, parsePercent } = await import("./rates-derive.ts");
  const payload = { global: { labor_rate: 35, overhead: 0, margin: 0 }, process: { cnc_3axis: { machine_rate: 75 }, cnc_turning: { machine_rate: 65 } }, material_prices: {} };
  const form = draftFormFrom(payload);
  assert.equal(form.labor, "35");
  assert.equal(form.overhead, "0");
  assert.equal(form.machines.cnc_3axis, "75");
  // 15 is 15%, never 1,500%
  assert.equal(parsePercent("15"), 0.15);
  assert.equal(parsePercent("15%"), 0.15);
  assert.equal(parsePercent("1500"), null);
  const out = applyDraft({ ...payload, process: { ...payload.process, cnc_3axis: { machine_rate: 75, post_hr_part: 0.5 } } }, { ...form, labor: "58", overhead: "15", margin: "10", machines: { ...form.machines, cnc_3axis: "82" }, hands: { cnc_3axis: "0.1" }, materials: [{ name: "Mild Steel", price: "2.40" }] }, (p) => (p === "cnc_3axis" ? "3-axis milling" : p));
  assert.equal(out.ok, true);
  if (!out.ok) return;
  const g = out.payload.global as Record<string, number>;
  assert.equal(g.labor_rate, 58);
  assert.equal(g.overhead, 0.15);
  assert.equal(g.margin, 0.1);
  assert.equal((out.payload.process as Record<string, Record<string, number>>).cnc_3axis.machine_rate, 82);
  assert.equal((out.payload.process as Record<string, Record<string, number>>).cnc_turning.machine_rate, 65);
  assert.deepEqual(out.payload.material_prices, { "Mild Steel": 2.4 });
  assert.equal((out.payload.process as Record<string, Record<string, number>>).cnc_3axis.post_hr_part, 0.1);
  assert.deepEqual(out.changes, ["Labor $35.00/h → $58.00/h", "Overhead 0% → 15%", "Margin 0% → 10%", "3-axis milling machine $75.00/h → $82.00/h", "3-axis milling hand work 0.5 h → 0.1 h a part", "Mild Steel typical → $2.40/kg"]);
  const bad = applyDraft(payload, { ...form, overhead: "1500" }, (p) => p);
  assert.equal(bad.ok, false);
  if (!bad.ok) assert.match(bad.errors.overhead, /percent, 0 to 300/);
});

test("every asset that goes through review has a name, material catalogs included (C2)", () => {
  assert.deepEqual(ASSET_NAMES, { rate_card: "Rate card", shop_profile: "Supplier rate profile", material_catalog: "Material catalog" });
});
