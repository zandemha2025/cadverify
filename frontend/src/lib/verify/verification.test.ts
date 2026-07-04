/**
 * Unit tests for the makeability VERIFICATION render-model (verification.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest.
 *
 * Proves the honesty contract of the verdict walk's makeability surface:
 *   (a) every verdict lattice value maps to a banner (incl. the negative/unknown
 *       first-class outcomes) — never a fabricated pass;
 *   (b) a gate failure renders as a CONCRETE need-vs-have delta when quantified,
 *       else the engine's own cited `human` string — never an invented number;
 *   (c) env exclusions carry the material + its cited standard through verbatim;
 *   (d) the machine-marginal rate is surfaced ONLY when a route actually carries
 *       one (a passing owned machine), null otherwise.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  verdictBannerModel,
  fitMark,
  gapText,
  perRouteRows,
  envStrikes,
  marginalRate,
  acquisitionGap,
  type VerificationBlock,
  type MakeabilityLattice,
} from "./verification.ts";

const LATTICE: MakeabilityLattice[] = [
  "makeable_in_house",
  "makeable_with_secondary_op",
  "makeable_not_on_owned",
  "makeable_outsource_only",
  "environment_excluded",
  "not_makeable",
  "unknown",
];

test("every verdict lattice value maps to a banner with a non-empty title", () => {
  for (const v of LATTICE) {
    const m = verdictBannerModel(v);
    assert.ok(m.title.length > 0, v);
    assert.ok(m.kicker.length > 0, v);
    assert.ok(["pass", "cond", "fail", "neutral"].includes(m.tone), v);
  }
  // in_house is a pass; not_makeable is a fail; unknown is neutral (never faked green)
  assert.equal(verdictBannerModel("makeable_in_house").tone, "pass");
  assert.equal(verdictBannerModel("not_makeable").tone, "fail");
  assert.equal(verdictBannerModel("environment_excluded").tone, "fail");
  assert.equal(verdictBannerModel("unknown").tone, "neutral");
});

test("fitMark: ✓ for a pass, ✗ for a real fail, ? for an undeclared/unknown gate", () => {
  assert.equal(fitMark("makeable_in_house").glyph, "✓");
  assert.equal(fitMark("makeable_with_secondary_op").glyph, "✓");
  assert.equal(fitMark("makeable_not_on_owned").glyph, "✗");
  assert.equal(fitMark("makeable_not_on_owned").tone, "fail");
  assert.equal(fitMark("unknown").glyph, "?");
  assert.equal(fitMark("unknown").tone, "neutral");
});

test("gapText: concrete need-vs-have when quantified, else the engine's cited human", () => {
  assert.equal(
    gapText({ gate: "envelope", axis: "z", need: 40, have: 20, human: "z too small" }),
    "need 40, have 20"
  );
  // an unknown gate (have null) is NOT a fabricated number — falls to human/needs
  assert.equal(
    gapText({ gate: "mass", axis: "mass", need: null, have: null, human: "part mass unknown" }),
    "part mass unknown"
  );
  // undeclared capability: have null, need present → states the need honestly
  assert.equal(
    gapText({ gate: "envelope", axis: "x", need: 30, have: null, human: "" }),
    "needs 30 — undeclared"
  );
});

test("perRouteRows sorts in_house first and maps the fit glyph/best machine", () => {
  const block: VerificationBlock = {
    verdict: "makeable_not_on_owned",
    per_route: {
      wire_edm: { verdict: "makeable_outsource_only", machines_evaluated: 0, best_machine: null, failures: [] },
      cnc_3axis: {
        verdict: "makeable_in_house",
        machines_evaluated: 1,
        best_machine: "Haas VF-2 #3",
        failures: [],
      },
      cnc_5axis: {
        verdict: "makeable_not_on_owned",
        machines_evaluated: 1,
        best_machine: null,
        failures: [{ gate: "envelope", axis: "z", need: 40, have: 20, human: "z" }],
      },
    },
  };
  const rows = perRouteRows(block);
  assert.equal(rows[0].process, "cnc_3axis"); // in_house sorts first
  assert.equal(rows[0].glyph, "✓");
  assert.equal(rows[0].bestMachine, "Haas VF-2 #3");
  // the not_on_owned route carries its concrete gate failure through
  const five = rows.find((r) => r.process === "cnc_5axis");
  assert.ok(five);
  assert.equal(five.glyph, "✗");
  assert.equal(gapText(five.failures[0]), "need 40, have 20");
  assert.deepEqual(perRouteRows(null), []);
});

test("envStrikes maps each exclusion to its material + cited standard, verbatim", () => {
  const block: VerificationBlock = {
    verdict: "makeable_in_house",
    env_exclusions: [
      { gate: "environment", axis: "Mild Steel", need: null, have: null, human: "Mild Steel excluded by NACE MR0175 under sour service" },
    ],
  };
  const strikes = envStrikes(block);
  assert.equal(strikes.length, 1);
  assert.equal(strikes[0].material, "Mild Steel");
  assert.ok(strikes[0].reason.includes("NACE MR0175"));
  assert.deepEqual(envStrikes({ verdict: "unknown" }), []);
});

test("marginalRate: surfaced only when a route carries a real machine rate", () => {
  const block: VerificationBlock = {
    verdict: "makeable_in_house",
    per_route: {
      cnc_3axis: {
        verdict: "makeable_in_house",
        machines_evaluated: 1,
        best_machine: "Haas VF-2 #3",
        failures: [],
        machine_rate_usd: 75,
      },
      cnc_turning: {
        verdict: "makeable_outsource_only",
        machines_evaluated: 0,
        best_machine: null,
        failures: [],
      },
    },
  };
  const mr = marginalRate(block, "cnc_3axis");
  assert.ok(mr);
  assert.equal(mr.rateUsd, 75);
  assert.equal(mr.machine, "Haas VF-2 #3");
  // no rate on this route → null, never a fabricated marginal
  assert.equal(marginalRate(block, "cnc_turning"), null);
  assert.equal(marginalRate(block, "unowned_process"), null);
  assert.equal(marginalRate(null, "cnc_3axis"), null);
});

test("acquisitionGap passes the concrete gap deltas through, empty when absent", () => {
  const block: VerificationBlock = {
    verdict: "makeable_not_on_owned",
    gap: [{ gate: "envelope", axis: "z", need: 40, have: 20, human: "z too small" }],
  };
  const g = acquisitionGap(block);
  assert.equal(g.length, 1);
  assert.equal(g[0].have, 20);
  assert.deepEqual(acquisitionGap({ verdict: "unknown" }), []);
});
