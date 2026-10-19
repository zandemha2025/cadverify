import test from "node:test";
import assert from "node:assert/strict";
import { buildMethods } from "../part/model.ts";
import { buildProblems } from "./problems.ts";
import { placesOf, rankProblems, unlockQty, unlockRows } from "./rank.ts";
import { enclosureCostOnly, shellCost, shellValidation } from "./fixtures.test-data.ts";

function shell() {
  const validation = shellValidation();
  const cost = shellCost();
  return { set: buildProblems({ validation, cost }), methods: buildMethods({ validation, cost, machines: [] }), cost };
}

test("ranked at 10: new lowest prices first (cheapest first), then warnings cleared, then no design change", () => {
  const { set, methods } = shell();
  const r = rankProblems(set, methods, 10);
  assert.deepEqual(
    r.map((u) => [u.problem.id, u.tier, u.value]),
    [
      ["drain", 0, "$7.50 each"],
      ["thin", 0, "$36.18 each"],
      ["draft", 0, "$601.82 each"],
      ["overhang", 2, "3 warnings"],
      ["corners", 2, "3 warnings"],
      ["undercut", 2, "2 warnings"],
      ["bodies", 2, "1 warning"],
      ["flat", 3, "Setup"],
      ["round", 3, "No change"],
    ],
  );
  const drain = r[0];
  assert.deepEqual(drain.added.map((m) => m.code).sort(), ["dlp", "mjf", "sla"]);
  assert.equal(drain.sub, "Nylon powder printing (MJF) becomes possible; also DLP $8.28, SLA $9.09");
  assert.equal(r[1].sub, "3-axis milling becomes possible; also 5-axis milling $46.78");
  assert.equal(r[3].sub, "Clears it for Resin printing (SLA), resin printing (DLP) and filament printing");
  // Filament and nylon powder (SLS) need both the wall and drain holes.
  assert.deepEqual(drain.partial.map((x) => x.m.code).sort(), ["fdm", "sls"]);
  assert.equal(r.find((u) => u.problem.id === "round")!.sub, "The lathe needs a round part");
});

test("the quantity toggle changes the ranking: at 10,000 molding's draft is the cheapest new price", () => {
  const { set, methods } = shell();
  const r = rankProblems(set, methods, 10000);
  assert.deepEqual(r.slice(0, 3).map((u) => [u.problem.id, u.value]), [["draft", "$2.42 each"], ["drain", "$4.21 each"], ["thin", "$12.80 each"]]);
});

test("a method that's cheaper than today's best is a new lowest price; a dearer one only adds a method", () => {
  const cost = enclosureCostOnly();
  const set = buildProblems({ validation: null, cost });
  const methods = buildMethods({ validation: null, cost, machines: [] });
  const at10 = rankProblems(set, methods, 10)[0];
  assert.equal(at10.tier, 1);
  assert.equal(at10.value, "+1 method");
  assert.equal(at10.sub, "Injection molding · Injection molding $1,501.85 each at 10, against filament printing $24.03");
  const at1000 = rankProblems(set, methods, 1000)[0];
  assert.equal(at1000.tier, 0);
  assert.equal(at1000.value, "−$6.60 each");
  assert.equal(at1000.sub, "Injection molding $16.85 against filament printing $23.45 · if redesigned");
});

test("places are numbered by their best-ranked problem; the whole part comes last", () => {
  const { set, methods } = shell();
  const places = placesOf(rankProblems(set, methods, 10));
  assert.deepEqual(places.map((p) => [p.n, p.name]), [["1", "Sealed cavity"], ["2", "Walls"], ["3", "Side walls"], ["4", "Faces pointing down"], ["5", "Undercut faces"], ["·", "Whole part"]]);
  assert.deepEqual(places.at(-1)!.ids, ["corners", "bodies", "flat", "round"]);
});

test("K1's unlocks: at the engine's own if-redesigned quantity when the fix unlocks tooling", () => {
  const { set, methods, cost } = shell();
  const draft = set.problems.find((p) => p.id === "draft")!;
  const thin = set.problems.find((p) => p.id === "thin")!;
  assert.equal(unlockQty(draft, set, methods, cost, 10, cost.quantities), 10000);
  assert.equal(unlockQty(thin, set, methods, cost, 10, cost.quantities), 10);
  const u = rankProblems(set, methods, 10).find((x) => x.problem.id === "thin")!;
  const { rows, foot } = unlockRows(u, { cost, methodsTotal: 12, picked: "cnc_3axis", repairable: false });
  assert.deepEqual(rows.map((x) => [x.k, x.v]), [["3-axis milling", "$36.18"], ["5-axis milling", "$46.78"], ["Filament printing, Nylon powder printing (SLS), Lathe and 1 more", "Still blocked"]]);
  assert.match(rows[2].s, /^Also need: sealed cavity, no drain holes, not a turned part and side walls need draft$/);
  assert.match(foot, /Thicker walls add material, so re-check after the change\.$/);
});
