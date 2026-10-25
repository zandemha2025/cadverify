/** Organization setup checklist. Run with node --test. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { primaryStep, setupChecklist, setupFacts, type SetupInput } from "./setup-derive.ts";

const BASE: SetupInput = { records: null, parts: null, machines: null, rates: null, posture: null, programs: null, actuals: null, members: null, me: "a@x.com", failed: {} };
const RATES = { using_governed: false, source: "default_rate_card_v0", provenance: "default" };

test("current org: done, partly and optional steps from real counts", () => {
  const s = setupChecklist({
    ...BASE,
    records: 20,
    parts: 9,
    machines: [
      { name: "Haas VF-2", process: "cnc_3axis", count: 1, hourly_rate_usd: 85 },
      { name: "Haas ST-20", process: "cnc_turning", count: 1, hourly_rate_usd: 80 },
    ],
    rates: RATES,
    posture: { measured: 0, shop: 0, user: 8, default: 57, total: 65 },
    programs: { programs: 0, inProgram: 0 },
    actuals: 0,
    members: [{ email: "a@x.com", org_role: "admin", is_active: true }],
  });
  assert.deepEqual(s.map((x) => x.chip), ["Done", "Done", "Partly", "Optional", "Optional", "Optional"]);
  assert.equal(s[0].detail, "20 records · 9 parts");
  assert.equal(s[1].detail, "2 machines · Haas VF-2, Haas ST-20");
  assert.equal(s[2].detail, "Default rate card (v0) · 8 of 65 cost inputs yours");
  assert.equal(s[2].sub, "Machine hourly rates are yours. Labor, setup and programming are typical.");
  assert.equal(s[3].detail, "0 programs · 9 parts not in a program");
  assert.equal(s[4].detail, "0 logged · recalibration needs 8 · measured range needs 3 held out per method");
  assert.equal(s[5].detail, "1 member · you're the only admin");
  assert.equal(primaryStep(s), "rates");
  assert.deepEqual(setupFacts(s), { done: 2, partly: 1, label: "2 of 6 steps done" });
});

test("new org: to do, typical, locked", () => {
  const s = setupChecklist({ ...BASE, records: 0, parts: 0, machines: [], rates: RATES, posture: null, members: [{ email: "a@x.com", org_role: "admin", is_active: true }] });
  assert.deepEqual(s.map((x) => x.chip), ["To do", "To do", "Typical", "Locked", "Locked", "Optional"]);
  assert.equal(s[0].go?.href, "/app?welcome=1");
  assert.equal(primaryStep(s), "check");
});

test("failed sources are Unknown, never To do", () => {
  const s = setupChecklist({ ...BASE, rates: RATES, failed: { records: true, machines: true } });
  assert.deepEqual(s.slice(0, 5).map((x) => `${x.chip}:${x.tone}`), ["Unknown:bad", "Unknown:bad", "Typical:unk", "Unknown:bad", "Unknown:bad"]);
  assert.equal(s[0].detail, "Records not loaded");
});
