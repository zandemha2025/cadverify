import test from "node:test";
import assert from "node:assert/strict";
import { chooseBody, earlierChoiceFrom, enginePick, followed, isChosen, pairAt, pickWhy, recordedChoice } from "./choice.ts";

type AnyObj = Record<string, unknown>;

// Numbers from the engine for the 60×40×30 mm PLA bracket on a Bambu Lab X1C (qty 100 and 1000).
const inside100 = { process: "fdm", material: "PLA", unit_cost_usd: 15.66, low_usd: 9.4, high_usd: 21.92, lead_low_days: 4.9, lead_high_days: 9.1, machine: "Bambu Lab X1C", machine_count: 1 };
const outside100 = { process: "mjf", material: "PP (Polypropylene)", unit_cost_usd: 12.16, low_usd: 7.3, high_usd: 17.02, lead_low_days: 5.6, lead_high_days: 10.4 };
const inside1000 = { ...inside100, unit_cost_usd: 15.58, low_usd: 9.35, high_usd: 21.81, lead_low_days: 42.7, lead_high_days: 79.3 };
const outside1000 = { ...outside100, unit_cost_usd: 12.07, lead_low_days: 7, lead_high_days: 13 };

function report(extra: AnyObj = {}): never {
  return {
    quantities: [100, 1000],
    estimates: [],
    decision: {
      make_now_process: "fdm",
      make_now_material: "PLA",
      tooling_process: null,
      tooling_dfm_ready: true,
      crossover_qty: null,
      recommendation: {
        "100": { process: "fdm", material: "PLA", unit_cost_usd: 15.66, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 4.9, lead_high_days: 9.1, in_house: true, basis: "in_house_within_range", machine: "Bambu Lab X1C" },
        "1000": { process: "mjf", material: "PP (Polypropylene)", unit_cost_usd: 12.07, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 7, lead_high_days: 13, in_house: false, basis: "outside_sooner" },
      },
      if_redesigned: {},
      note: "",
      options: {
        "100": { in_house: inside100, outside: outside100, pick: "in_house", basis: "in_house_within_range" },
        "1000": { in_house: inside1000, outside: outside1000, pick: "outside", basis: "outside_sooner" },
      },
      rule: "A machine you own that clears every check is recommended unless …",
      ...extra,
    },
  } as never;
}

test("ScaleCAD's pick follows the engine's in-house rule, with both sides kept", () => {
  const r = report();
  assert.deepEqual(enginePick(r, 100), { process: "fdm", material: "PLA", inHouse: true, machine: "Bambu Lab X1C", basis: "in_house_within_range" });
  assert.equal(enginePick(r, 1000)?.inHouse, false);
  assert.equal(pairAt(r, 100)?.outside?.process, "mjf");
  assert.equal(pairAt(r, 5), null);
  assert.equal(pairAt({ decision: { recommendation: {} } } as never, 100), null);
});

test("the reason restates the engine's numbers", () => {
  const r = report();
  const within = pickWhy(pairAt(r, 100)!, 100);
  assert.match(within, /your Bambu Lab X1C/);
  assert.match(within, /\$3\.50 less each \(22%\)/);
  assert.match(within, /\$9\.40–\$21\.92/);
  const sooner = pickWhy(pairAt(r, 1000)!, 1000);
  assert.match(sooner, /cheaper \(\$12\.07 against \$15\.58\) and sooner/);
  assert.match(sooner, /7–13 days against 43–79 days/);
  const cheaper = pickWhy({ in_house: inside100, outside: { ...outside100, unit_cost_usd: 5 }, pick: "outside", basis: "outside_cheaper" } as never, 100);
  assert.match(cheaper, /below the low end of the in-house range/);
  assert.match(pickWhy({ in_house: inside100, outside: null, pick: "in_house", basis: "in_house_only" } as never, 100), /No outside process is priced/);
});

test("your choice is the record's Make in-house / Make outside outcome, and the page follows it", () => {
  const r = report();
  assert.equal(recordedChoice(null), null);
  assert.equal(recordedChoice({ user_disposition: "acquire", disposition_basis: { process: "injection_molding", material: "PP (Molded)", quantity: 1000 } } as never), null);
  assert.equal(recordedChoice({ user_disposition: "outside", disposition_basis: null } as never), null);
  const choice = recordedChoice({ user_disposition: "outside", disposition_basis: { process: "sls", material: "PA12 (Nylon 12)", quantity: 100 }, disposition_updated_at: "2026-10-21T22:00:00Z" } as never);
  assert.deepEqual(choice, { process: "sls", material: "PA12 (Nylon 12)", quantity: 100, kind: "outside", at: "2026-10-21T22:00:00Z" });
  assert.deepEqual(followed(r, 1000, choice), { process: "sls", by: "you" });
  assert.deepEqual(followed(r, 1000, null), { process: "mjf", by: "scalecad" });
  assert.equal(isChosen(choice, "sls"), true);
  assert.equal(isChosen(choice, "fdm"), false);
});

test("Make it this way records in-house only on a machine of yours that clears it", () => {
  const e = { process: "fdm", material: "PLA", quantity: 100 };
  assert.deepEqual(chooseBody(e, true), { disposition: "inhouse", process: "fdm", material: "PLA", quantity: 100 });
  assert.equal(chooseBody({ ...e, process: "mjf", material: "PP (Polypropylene)" }, false).disposition, "outside");
});

test("a choice on an earlier check of the part is offered on the new record", () => {
  const recs = [
    { id: "NEW", user_disposition: null, disposition_basis: null },
    { id: "MID", user_disposition: "acquire", disposition_basis: { process: "injection_molding", material: "PP (Molded)", quantity: 1000 } },
    { id: "OLD", user_disposition: "inhouse", disposition_basis: { process: "fdm", material: "PLA", quantity: 100 }, disposition_updated_at: "2026-10-20T10:00:00Z" },
  ] as never;
  assert.deepEqual(earlierChoiceFrom(recs, "NEW"), { process: "fdm", material: "PLA", quantity: 100, kind: "inhouse", at: "2026-10-20T10:00:00Z", recordId: "OLD" });
  assert.equal(earlierChoiceFrom(recs, "OLD"), null, "the record on screen is not an earlier one");
  assert.equal(earlierChoiceFrom([], null), null);
});
