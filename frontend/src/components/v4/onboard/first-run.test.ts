import test from "node:test";
import assert from "node:assert/strict";
import {
  ahaModel,
  askCopy,
  catalogGroups,
  draftFrom,
  envText,
  firstSteps,
  homeMode,
  machineBody,
  missingFor,
  nextTip,
  ownedBasis,
  ownedRate,
  parseTips,
  provenanceOf,
  rateOf,
  ranOnMachines,
  resumeCard,
  shopCardDue,
  tipNumber,
  tipPlan,
  tipsDue,
  typicalRate,
  weightNeeded,
  type FirstStepsInput,
} from "./first-run.ts";
import { BEFORE, CATALOG, MACHINES_BLANK, MACHINES_RATED, NOW_BLANK, NOW_RATED, STAGING_BEFORE, STAGING_MACHINES, STAGING_NOW } from "./fixtures.test-data.ts";

const vf2 = CATALOG.find((t) => t.name === "Haas VF-2")!;
const mk4s = CATALOG.find((t) => t.name === "Prusa MK4S")!;
const m2 = CATALOG.find((t) => t.name === "Carbon M2")!;

test("the material question says plainly what skipping does", () => {
  assert.equal(askCopy(null, null, false).state, "Not chosen");
  assert.match(askCopy(null, null, false).note, /prices use plastic, the default/);
  assert.equal(askCopy("aluminum", null, false).state, "Prices use aluminum");
  assert.match(askCopy("aluminum", "aluminum", true).note, /without another check/);
  assert.equal(askCopy("steel", "aluminum", true).state, "Re-pricing in steel");
  assert.equal(askCopy(null, "polymer", true).state, "Priced in plastic");
  assert.match(askCopy(null, "polymer", true).note, /plastic, the default/);
});

test("tips show once: not after they're done, not on a later visit", () => {
  const now = 1_000_000_000;
  assert.equal(tipsDue(parseTips(null), now), true);
  assert.equal(tipsDue(parseTips("not json"), now), true);
  assert.equal(tipsDue({ done: false, shownAt: now - 60_000, shop: "open" }, now), true);
  assert.equal(tipsDue({ done: false, shownAt: now - 2 * 60 * 60 * 1000, shop: "open" }, now), false);
  assert.equal(tipsDue({ done: true, shownAt: now, shop: "open" }, now), false);
  assert.equal(shopCardDue({ done: true, shownAt: now - 1000, shop: "open" }, now), "card");
  assert.equal(shopCardDue({ done: true, shownAt: now - 1000, shop: "later" }, now), "chip");
  assert.equal(shopCardDue({ done: true, shownAt: now - 1000, shop: "done" }, now), null);
  assert.equal(shopCardDue({ done: true, shownAt: now - 3 * 60 * 60 * 1000, shop: "open" }, now), null);
  assert.equal(shopCardDue({ done: false, shownAt: now, shop: "open" }, now), null);
});

test("the tips this part shows are fixed when they start, and numbered by them", () => {
  assert.deepEqual(tipPlan(true, true), ["tip1", "tip2", "tip3"]);
  assert.deepEqual(tipPlan(true, false), ["tip1", "tip3"]);
  assert.deepEqual(tipPlan(false, true), ["tip2", "tip3"]);
  const plan = tipPlan(true, false);
  assert.equal(nextTip(plan, "tip1"), "tip3");
  assert.equal(nextTip(plan, "tip3"), "done");
  assert.deepEqual(tipNumber(plan, "tip3"), { n: 2, of: 2 });
  assert.deepEqual(tipNumber(tipPlan(true, true), "tip2"), { n: 2, of: 3 });
});

test("catalog search groups machining then printers and matches brand, model or kind", () => {
  const all = catalogGroups(CATALOG, "");
  assert.deepEqual(all.groups.map((g) => g.label), ["Machining", "Printers"]);
  assert.equal(all.matched, 3);
  const haas = catalogGroups(CATALOG, "haas");
  assert.equal(haas.matched, 1);
  assert.equal(haas.groups[0].items[0].t.name, "Haas VF-2");
  assert.equal(catalogGroups(CATALOG, "filament").matched, 1);
  assert.equal(catalogGroups(CATALOG, "nothing like it").matched, 0);
  assert.equal(envText(vf2.capabilities), "762 × 406 × 508 mm");
  assert.equal(envText({ swing_dia: 254, between_centers: 533 }), "Ø254 × 533 mm");
});

test("an unedited Haas VF-2 needs nothing typed for a yes, and its values are the maker's", () => {
  const d = draftFrom(vf2, 0);
  assert.deepEqual(missingFor(vf2, d), []);
  assert.equal(d.kg, "1361");
  assert.equal(provenanceOf(vf2, d, "max_workpiece_kg")?.source, "maker_spec");
  assert.equal(provenanceOf(vf2, d, "materials")?.source, "maker_described");
  // An edit makes the value the shop's own.
  assert.equal(provenanceOf(vf2, { ...d, kg: "200" }, "max_workpiece_kg"), null);
  assert.equal(provenanceOf(vf2, { ...d, materials: ["aluminum", "steel", "stainless"] }, "materials"), null);
  assert.equal(provenanceOf(vf2, { ...d, materials: ["steel", "aluminum"] }, "materials")?.source, "maker_described");
  // Cleared weight: needed for a yes on a mill.
  assert.deepEqual(missingFor(vf2, { ...d, kg: "" }), ["kg"]);
  assert.deepEqual(missingFor(vf2, { ...d, materials: [] }), ["materials"]);
});

test("printers: the work area decides weight; materials still needed", () => {
  assert.equal(weightNeeded(vf2), true);
  assert.equal(weightNeeded(mk4s), false);
  assert.deepEqual(missingFor(mk4s, draftFrom(mk4s, 1)), []);
  const m2d = draftFrom(m2, 2);
  assert.deepEqual(missingFor(m2, m2d), ["materials"]);
  assert.deepEqual(missingFor(m2, { ...m2d, matsText: "Rigid polyurethane, EPU 40" }), []);
});

test("the saved body is the template as served, plus what the shop changed", () => {
  const d = draftFrom(vf2, 0);
  const body = machineBody(vf2, d);
  assert.equal(body.name, "Haas VF-2");
  assert.equal(body.process, "cnc_3axis");
  assert.equal(body.max_workpiece_kg, 1361);
  assert.deepEqual(body.materials, ["aluminum", "steel"]);
  assert.equal(body.hourly_rate_usd, null, "blank keeps the typical rate");
  assert.deepEqual((body.capabilities as Record<string, unknown>).maker_spec, (vf2.capabilities as Record<string, unknown>).maker_spec);
  const rated = machineBody(vf2, { ...d, rate: "$85", count: 2 });
  assert.equal(rated.hourly_rate_usd, 85);
  assert.equal(rated.count, 2);
});

test("rates come from the engine's own drivers", () => {
  const e = BEFORE.estimates.find((x) => x.process === "cnc_3axis" && x.quantity === 10)!;
  assert.equal(Math.round(rateOf(e)!), 75);
  assert.equal(Math.round(typicalRate(BEFORE, "cnc_3axis")!), 75);
  assert.equal(ownedRate(85, 0.35), 55.25);
});

test("before/now on staging: an unedited Haas VF-2, rate blank, priced as a machine you own", () => {
  assert.equal(ranOnMachines(STAGING_BEFORE), false);
  assert.equal(ranOnMachines(STAGING_NOW), true);
  const m = ahaModel({ before: STAGING_BEFORE, now: STAGING_NOW, machines: STAGING_MACHINES, validation: null, q: 100, showBefore: false });
  assert.equal(m.best?.name, "Haas VF-2");
  assert.deepEqual(m.lead, { a: "You can make it on your ", b: "Haas VF-2", tone: "ok" });
  assert.equal(m.sub, "$20.97 each at 100, in-house in 6061-T6 Aluminum. The cheapest way as drawn.");
  assert.equal(m.rows[0].a, "Haas VF-2");
  assert.equal(m.rows[0].as, "in-house · fits, 1,361 kg max");
  const each = m.rows.find((r) => r.k === "3-axis milling, each")!;
  assert.deepEqual([each.b, each.a], ["$21.64", "$20.97"]);
  const mt = m.rows.find((r) => r.k === "Machine time")!;
  assert.deepEqual([mt.b, mt.bs, mt.a, mt.as], ["$1.81", "typical $75/h", "$1.18", "typical $75/h, owned"]);
  assert.match(m.foot, /^Only the machine line moved, by \$0\.67: a machine you own is priced without its paid-off capital share, 35% of the typical \$75\/h \(\$48\.75\/h in-house\)\. Add your rate to price it at yours\./);
  assert.equal(m.machines[0].verdict, "Can make");
  assert.equal(m.ticket?.big, "$20.97 each");
  assert.match(m.labor ?? "", /^\$17\.50 of the \$20\.97 at 100 is labor at a typical \$35\/h/);
});

test("before/now when the price didn't move: says where it's made changed, not the price", () => {
  const m = ahaModel({ before: BEFORE, now: NOW_BLANK, machines: MACHINES_BLANK, validation: null, q: 10, showBefore: false });
  assert.equal(m.best?.name, "Haas VF-2");
  assert.match(m.sub, /^\$31\.88 each at 10, in-house in 6061-T6 Aluminum\. Outside, metal deposition is \$30\.00\.$/);
  assert.match(m.rows[0].as, /in-house · fits, 200 kg max/);
  assert.match(m.foot, /^Where it’s made changed, not the price\./);
  assert.equal(m.machines.find((x) => x.name === "Haas ST-20")?.tone, "bad");
});

test("before/now with your rate: only the machine line moves, by the engine's amount", () => {
  const m = ahaModel({ before: BEFORE, now: NOW_RATED, machines: MACHINES_RATED, validation: null, q: 10, showBefore: false });
  const each = m.rows.find((r) => r.k === "3-axis milling, each")!;
  assert.equal(each.a, "$31.38");
  const mt = m.rows.find((r) => r.k === "Machine time")!;
  assert.equal(mt.a, "$1.34");
  assert.match(mt.as, /your \$85\/h, owned/);
  assert.match(m.foot, /^Only the machine line moved, by \$0\.50/);
  const before = ahaModel({ before: BEFORE, now: NOW_RATED, machines: MACHINES_RATED, validation: null, q: 10, showBefore: true });
  assert.deepEqual(before.lead, { a: "In-house ", b: "not checked", tone: "plain" });
  assert.match(before.sub, /3-axis milling at a typical shop: \$31\.88 each at 10/);
});

test("a machine added later: before is the earlier answer on your machines, not \"outside\"", () => {
  const m = ahaModel({ before: STAGING_NOW, now: STAGING_NOW, machines: STAGING_MACHINES, validation: null, q: 100, showBefore: false });
  assert.equal(m.beforeOn, true);
  assert.deepEqual([m.rows[0].b, m.rows[0].bs], ["Haas VF-2", "in-house"]);
  const mt = m.rows.find((r) => r.k === "Machine time")!;
  assert.equal(mt.bs, "typical $75/h, owned");
  assert.match(m.foot, /^Same machine and price as before\./);
  const b = ahaModel({ before: STAGING_NOW, now: STAGING_NOW, machines: STAGING_MACHINES, validation: null, q: 100, showBefore: true });
  assert.deepEqual(b.lead, { a: "Made on your ", b: "Haas VF-2", tone: "ok" });
});

test("no machine that fits: says none, never a yes", () => {
  const steelOnly = MACHINES_BLANK.map((m) => ({ ...m, materials: ["steel"] }));
  const m = ahaModel({ before: BEFORE, now: { ...NOW_BLANK, verification: { verdict: "makeable_not_on_owned", per_route: {} } }, machines: steelOnly, validation: null, q: 10, showBefore: false });
  assert.equal(m.best, null);
  assert.equal(m.lead.tone, "no");
});

test("Home's first-run mode", () => {
  assert.equal(homeMode({ records: null, parts: null, dismissed: false }), "loading");
  assert.equal(homeMode({ records: 0, parts: 0, dismissed: false }), "first");
  assert.equal(homeMode({ records: 2, parts: 1, dismissed: false }), "back");
  assert.equal(homeMode({ records: 2, parts: 1, dismissed: true }), "normal");
  assert.equal(homeMode({ records: 30, parts: 9, dismissed: false }), "normal");
});

const hrefs = { check: "/c", shop: "/s", rates: "/r", programs: "/p", actuals: "/a", team: "/t", addMachines: "/add" };

test("setup steps before the first part: check is next, and machines can be added first (me-19)", () => {
  const i: FirstStepsInput = { records: 0, parts: 0, part: null, machines: [], rates: { using_governed: false, source: "default_rate_card_v0" }, yours: null, labor: null, programs: null, actuals: null, members: 1, failed: {}, hrefs };
  const s = firstSteps(i);
  assert.deepEqual(s.map((x) => x.chip), ["To do", "To do", "Typical", "Locked", "Locked", "Optional"]);
  assert.equal(s[0].next, true);
  assert.equal(s[2].detail, "Default rate card v0 · every input typical");
});

test("setup steps after a skipped shop: add machines is next, with the part named", () => {
  const i: FirstStepsInput = {
    records: 1,
    parts: 1,
    part: { file: "bored-block-mm.iges", material: "aluminum", onMachines: false, href: "/p/x" },
    machines: [],
    rates: { using_governed: false, source: "default_rate_card_v0" },
    yours: null,
    labor: 35,
    programs: { programs: 0, notIn: 1 },
    actuals: 0,
    members: 1,
    failed: {},
    hrefs,
  };
  const s = firstSteps(i);
  assert.equal(s[0].detail, "bored-block-mm.iges · aluminum · 1 record");
  assert.equal(s[1].chip, "To do");
  assert.equal(s[1].next, true);
  assert.match(s[1].detail, /priced at typical shops only/);
  assert.equal(s[3].detail, "0 programs · 1 part not in a program");
  const rated = firstSteps({ ...i, machines: [{ name: "Haas VF-2", count: 1, hourly_rate_usd: 85 }] });
  assert.equal(rated[1].chip, "Done");
  assert.equal(rated[2].chip, "Partly");
  assert.equal(rated[2].next, true);
  assert.match(rated[2].detail, /labor \(\$35\/h\)/);
});

test("pick up where you left off says a check predates the machines only when it does (me-07)", () => {
  const h = { addMachines: "/add", rates: "/r", recheck: "/re" };
  // The record hasn't loaded yet: nothing, rather than a card that flips two seconds later.
  assert.equal(resumeCard({ file: "pocket-block.step", partHref: "/p", cost: null, machines: 4, onMachines: false, hrefs: h }), null);
  const before = resumeCard({ file: "bracket.step", partHref: "/p", cost: BEFORE, machines: 4, onMachines: false, addedAfter: true, hrefs: h });
  assert.equal(before?.title, "bracket.step was checked before your machines were added");
  // Machines were there before the check, and the check still didn't use them: said as it is.
  const notOn = resumeCard({ file: "bracket.step", partHref: "/p", cost: BEFORE, machines: 4, onMachines: false, addedAfter: false, hrefs: h });
  assert.equal(notOn?.title, "bracket.step wasn’t checked against your machines");
  // Checked on your machines: never the re-check card.
  assert.notEqual(resumeCard({ file: "bracket.step", partHref: "/p", cost: NOW_RATED, machines: 4, onMachines: true, addedAfter: false, hrefs: h })?.k, "Next: re-check on your machines");
});

test("Add your machines is never locked before the first check: Your shop takes them any time (me-19)", () => {
  const s = firstSteps({ records: 0, parts: 0, part: null, machines: [], rates: null, yours: null, labor: null, programs: null, actuals: null, members: null, failed: {}, hrefs: { check: "/c", shop: "/s", rates: "/r", programs: "/p", actuals: "/a", team: "/t", addMachines: "/s?add=1" } });
  const m = s.find((x) => x.key === "machines")!;
  assert.equal(m.chip, "To do");
  assert.deepEqual(m.go, { label: "Add machines", href: "/s?add=1" });
});

test("a labor rate that is already yours is never asked for again (me-07)", () => {
  const h = { addMachines: "/add", rates: "/r", recheck: "/re" };
  const yours = { ...NOW_RATED, assumptions: (NOW_RATED.assumptions ?? []).map((a) => (a.name === "labor_rate" ? { ...a, provenance: "SHOP" } : a)) } as typeof NOW_RATED;
  const c = resumeCard({ file: "bracket.step", partHref: "/p", cost: yours, machines: 4, onMachines: true, addedAfter: false, hrefs: h })!;
  assert.equal(c.k, "Last checked");
  assert.notEqual(c.go.label, "Set labor rate");
  assert.match(c.text, /^At your rates: \$17\.50 of that is labor at your \$35\/h\.$/);
});

test("pick up where you left off: machines next, then the labor rate", () => {
  const add = resumeCard({ file: "bored-block-mm.iges", partHref: "/p", cost: BEFORE, machines: 0, onMachines: false, hrefs: { addMachines: "/add", rates: "/r", recheck: "/re" } });
  assert.equal(add?.k, "Next: add your machines");
  assert.match(add!.text, /cheapest at 10 is \$30\.00 by metal deposition, outside/);
  assert.doesNotMatch(add!.meta, /uses 1 check/);
  const lab = resumeCard({ file: "bored-block-mm.iges", partHref: "/p", cost: NOW_RATED, machines: 2, onMachines: true, hrefs: { addMachines: "/add", rates: "/r", recheck: "/re" } });
  assert.equal(lab?.title, "bored-block-mm.iges: on your Haas VF-2, $31.38 each at 10");
  assert.match(lab!.text, /^\$17\.50 of that is labor at a typical \$35\/h/);
});

test("the owned machine line reads in the current and the older wording", () => {
  const est = (source: string) => ({ drivers: [{ name: "machine_cost", value: 1, unit: "$", provenance: "USER", source }] }) as never;
  const now = ownedBasis(est("0.0242 hr × $75/hr (machine 'Haas VF-2', at its declared rate) × (1-0.35) on a machine you own: running cost only, the machine is already paid for (typical value, not confirmed by a shop)"));
  assert.deepEqual(now, { rate: 75, cap: 0.35, yours: true });
  const before = ownedBasis(est("0.0242 hr × $75/hr × (1-0.35 capital sunk) OWNED-IN-HOUSE marginal [assumption, not shop-validated]"));
  assert.deepEqual(before, { rate: 75, cap: 0.35, yours: true });
  assert.equal(ownedBasis(est("0.0242 hr × $75/hr × region-labor ×1")), null);
});

test("the own-part card says the phone check comes first and keeps the catalog allowance apart from checks", async () => {
  const { allowanceLines } = await import("./first-run.ts");
  const fresh = allowanceLines({ checksLeft: 15, plan: "trial", phoneFirst: true, catalog: { cap: 50, left: 50, started: false } });
  assert.equal(fresh.uses, "Uses 1 of 15 free checks · phone check first");
  assert.match(fresh.drop, /^Drop a part here\. Verify your phone first \(we text you a code once\)/);
  assert.equal(fresh.batch, "Many parts at once: up to 50 free, separate from your 15 free checks");
  const later = allowanceLines({ checksLeft: 1, plan: "trial", phoneFirst: false, catalog: { cap: 50, left: 38, started: true } });
  assert.equal(later.uses, "Uses 1 of 1 free check");
  assert.equal(later.drop, "Drop a part here. It checks right away and opens on its own page.");
  assert.equal(later.batch, "Many parts at once: 38 of 50 free catalog parts left, separate from your 1 free check");
  assert.equal(allowanceLines({ checksLeft: null, plan: "pilot", phoneFirst: false, catalog: null }).batch, null);
});
