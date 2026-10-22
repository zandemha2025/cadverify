import { test } from "node:test";
import assert from "node:assert/strict";

const { recheckReason, recheckSummary } = await import("./recheck-words.ts");
const { plainError, ranOutOfTime } = await import("./plain-errors.ts");

function cost(rec: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  return { material_class: "aluminum", quantities: [1, 250], estimates: [], decision: { recommendation: rec }, ...extra } as never;
}

const before = cost({
  "250": { process: "waam", material: "AlSi10Mg", unit_cost_usd: 3.68, lead_low_days: 12.6, lead_high_days: 23.4, in_house: false },
});
const after = cost(
  { "250": { process: "cnc_3axis", material: "6061-T6 Aluminum", unit_cost_usd: 18.73, lead_low_days: 8.4, lead_high_days: 10.6, in_house: true, machine: "KCM Mill 3" } },
  { specs: { declared: { inspection: ["fai_as9102"], certifications: ["as9100"] } } },
);

test("a re-check with saved specs says why, which record, and what moved at the page's quantity (buyer-04)", () => {
  assert.equal(recheckReason(before, after), "with the saved specs");
  const s = recheckSummary(before, after, 250, "01M5J6TXH8PN1SG96PSK7E853J");
  assert.match(s, /^Re-checked with the saved specs · new record #7E853J · /);
  assert.match(s, /at 250: ScaleCAD's pick was wire-arc printing outside at \$3\.68, now 3-axis milling on your KCM Mill 3 at \$18\.73 each; 13–23 → 8–11 days/);
  assert.match(s, /priced with the specs: First article, AS9102; Supplier must hold AS9100/);
  assert.match(s, / · no check used$/);
});

test("the same pick at a new price reads as a price change", () => {
  const b = cost({ "250": { process: "cnc_3axis", material: "6061", unit_cost_usd: 17.89, lead_low_days: 1, lead_high_days: 3, in_house: true, machine: "KCM Mill 3" } });
  const a = cost({ "250": { process: "cnc_3axis", material: "6061", unit_cost_usd: 18.73, lead_low_days: 1, lead_high_days: 3, in_house: true, machine: "KCM Mill 3" } });
  assert.equal(recheckReason(b, a), "with your machines and conditions");
  assert.match(recheckSummary(b, a, 250, null), /at 250: ScaleCAD's pick 3-axis milling on your KCM Mill 3, \$17\.89 → \$18\.73 each · no check used$/);
});

test("refusals are said in plain words, the server's own words kept for Details (buyer-04, buyer-05)", () => {
  const gmsh = "Could not tessellate this part: gmsh could not mesh the geometry [rung 2 exceeded 15s cap] (all 3 mesh strategies failed).";
  const r = plainError("recheck", 400, gmsh);
  assert.doesNotMatch(r.text, /gmsh|rung|tessellat|cap\]/);
  assert.match(r.text, /^Not re-checked: .*record on this page is unchanged\. Try again in a minute\.$/);
  assert.equal(r.detail, gmsh);
  assert.equal(r.retry, true);
  const v = plainError("view", 400, gmsh);
  assert.doesNotMatch(v.text, /gmsh|rung/);
  const busy = plainError("view", 429, "this organization has reached its concurrent-analysis limit of 3", "org_at_capacity");
  assert.doesNotMatch(busy.text, /concurrent-analysis/);
  assert.match(busy.text, /already running 3 jobs for your organization \(checks, re-checks and 3D views\)/);
  const slow = plainError("recheck", 504, "Cost analysis exceeded 60s timeout.", "ANALYSIS_TIMEOUT");
  assert.match(slow.text, /took longer than a check is allowed \(60 seconds\)/);
  assert.deepEqual(plainError("recheck", 400, "Unknown material_class 'x'."), { text: "Unknown material_class 'x'.", detail: null, retry: false });
});

test("an outside pick that is your process at a shop says so", () => {
  const b = cost({ "250": { process: "cnc_3axis", material: "6061", unit_cost_usd: 17.89, lead_low_days: 1, lead_high_days: 3, in_house: true, machine: "KCM Mill 3" } });
  const a = cost({ "250": { process: "cnc_3axis", material: "6061", unit_cost_usd: 19.14, lead_low_days: 8, lead_high_days: 16, in_house: false, same_process_outside: true } });
  assert.match(recheckSummary(b, a, 250, null), /was 3-axis milling on your KCM Mill 3 at \$17\.89, now 3-axis milling at a job shop at \$19\.14 each; 1–3 → 8–16 days/);
});

test("a re-check that matches an earlier record names that record, not a new one", () => {
  assert.match(recheckSummary(before, after, 250, "01M5J6TXH8PN1SG96PSK32FFC0", true), /^Re-checked with the saved specs · same answer as record #32FFC0, shown now · /);
});

test("a price that ran out of time is said plainly and retried with more time (me-12)", () => {
  const gmsh = "Could not tessellate this part: gmsh could not mesh the geometry [rung 2 exceeded 15s cap] (all 3 mesh strategies failed).";
  const c = plainError("cost", 0, gmsh);
  assert.match(c.text, /^The process checks are ready\. Prices didn't finish: .* Retry cost: it gets more time\.$/);
  assert.doesNotMatch(c.text, /gmsh|rung|cap/);
  assert.equal(ranOutOfTime(gmsh), true);
  assert.equal(ranOutOfTime("Cost analysis exceeded 60s timeout."), true);
  assert.equal(ranOutOfTime("Could not tessellate this part: gmsh cannot mesh a periodic surface in the geometry (all 3 mesh strategies failed)."), false);
  assert.equal(ranOutOfTime(null), false);
});
