import assert from "node:assert/strict";
import test from "node:test";

import { diffCard, initials, noteLines, personName, pipeline } from "./changes-derive.ts";
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
