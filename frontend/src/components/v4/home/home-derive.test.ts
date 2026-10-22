/**
 * Home and Parts derivations: the queue appears only from known signals, the
 * machine verdict precedence, filters, and the URL round trip.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/home/home-derive.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildQueue, homeFacts, recentRows, setupSteps, rateCardName, type HomeInput } from "./home-derive.ts";
import {
  countBy,
  filterFromSearch,
  gapLine,
  matches,
  NO_FILTER,
  partQuery,
  partsFacts,
  priceText,
  searchFromFilter,
  tidyReason,
  VERDICT_FILTERS,
  verdictOf,
} from "./parts-derive.ts";
import type { MakeSummary, PartRow, RecordRow } from "./model.ts";
import { shortWhen, sizeText, wayName } from "./words.ts";

const EMPTY: HomeInput = {
  records: null,
  recordsMore: false,
  parts: null,
  partsTotal: null,
  make: null,
  machines: null,
  changes: null,
  actuals: null,
  posture: null,
  rates: null,
  programs: null,
  withVolume: null,
};

function part(over: Partial<PartRow> = {}): PartRow {
  return {
    part_key: "a".repeat(64),
    filename: "bracket.stl",
    file_type: "stl",
    lifecycle_state: "Costed",
    recommended_route: { process: "cnc_3axis", material: "6061-T6 Aluminum", source: "costed" },
    unit_cost: { usd: 19.05, qty: 10, withheld: false, withheld_reason: null, validated: false },
    findings: { total: 1, critical: 0, advisory: 1, info: 0, scoped_process: "cnc_3axis" },
    provenance_posture: null,
    route_blocker_count: 0,
    cost_decision: { id: "D1" },
    analysis: { id: "A1" },
    updated_at: "2026-10-18T04:16:00Z",
    ...over,
  };
}

function rec(over: Partial<RecordRow> = {}): RecordRow {
  return { id: "R1", mesh_hash: "m".repeat(64), filename: "bracket.stl", label: null, make_now_process: "fdm", created_at: "2026-10-18T05:00:00Z", approval_status: "unreviewed", ...over };
}

const MAKE: MakeSummary = { makeable_in_house: 7, makeable_outside: 0, needs_capability: 2, not_makeable: 1, unknown: 0, geometry_invalid: 0, total: 10, stale_count: 7, stale: true, truncated: false };

test("nothing loaded → no queue items, no facts (unknown is never zero)", () => {
  assert.deepEqual(buildQueue(EMPTY), []);
  assert.deepEqual(homeFacts(EMPTY, null), []);
});

test("a known zero machine count asks for machines; an unknown one doesn't", () => {
  assert.equal(buildQueue({ ...EMPTY, machines: [] })[0].key, "machines");
  assert.equal(buildQueue({ ...EMPTY, machines: null }).length, 0);
});

test("queue order and content come from real signals", () => {
  const q = buildQueue({
    ...EMPTY,
    records: [rec(), rec({ id: "R2", approval_status: "approved" })],
    parts: [part(), part({ part_key: "b".repeat(64), filename: "shell.stl", unit_cost: { usd: null, qty: 10, withheld: true, withheld_reason: "24 faces (100.0%) below 1.5mm min wall for ded. Thinnest: 0.5mm.", validated: false }, route_blocker_count: 1 })],
    make: MAKE,
    machines: [{ name: "Haas VF-2", process: "cnc_3axis", count: 1, hourly_rate_usd: 85 }],
    changes: [],
    actuals: 0,
    rates: { using_governed: false, source: "default_rate_card_v0", provenance: "default" },
    posture: { measured: 0, shop: 0, user: 8, default: 64, total: 72 },
  });
  assert.deepEqual(q.map((i) => i.key), ["stale", "design", "capability", "out", "rates", "review", "actuals"]);
  const design = q.find((i) => i.key === "design")!;
  assert.equal(design.title, "shell.stl needs a design change");
  assert.equal(design.short, "24 faces below 1.5 mm min wall · thinnest 0.5 mm");
  assert.equal(design.act.label, "See why, on the part");
  const review = q.find((i) => i.key === "review")!;
  assert.equal(review.title, "1 records not reviewed");
  assert.equal(review.short, "1 approved");
  assert.equal(q.find((i) => i.key === "rates")!.short, "Default rate card (v0) · 8 of 72 cost inputs yours");
});

test("governed rates and approved records produce no nudges", () => {
  const q = buildQueue({ ...EMPTY, records: [rec({ approval_status: "approved" })], actuals: 2, rates: { using_governed: true, source: "x", provenance: "user" } });
  assert.deepEqual(q, []);
});

test("facts list only loaded counts, with links", () => {
  const f = homeFacts({ ...EMPTY, partsTotal: 9, records: [rec()], recordsMore: true, machines: [{ name: "a", process: "fdm", count: 2, hourly_rate_usd: null }] }, 3);
  assert.deepEqual(f.map((x) => `${x.n} ${x.t}`), ["3 need attention", "9 parts", "1+ records", "2 machines"]);
});

test("recent rows say what was picked and where the record stands, and open the part", () => {
  const now = new Date("2026-10-18T12:00:00");
  const rows = recentRows([rec({ user_disposition_label: "Make in-house", make_now_process: "cnc_3axis" }), rec({ id: "R2", mesh_hash: "n".repeat(64), make_now_process: null, is_stale: true })], now);
  assert.equal(rows[0].sub, "3-axis milling · decided: make in-house");
  assert.equal(rows[1].sub, "No price · out of date");
  assert.equal(rows[0].href, `/app/part/${"m".repeat(64)}`, "one click to the part, not only its record");
});

test("a part checked again shows once, at its latest record; a record without a part opens the record", () => {
  const rows = recentRows([rec({ id: "R3", make_now_process: "mjf" }), rec({ id: "R1" }), rec({ id: "R2", mesh_hash: null as unknown as string })]);
  assert.deepEqual(rows.map((r) => r.id), ["R3", "R2"]);
  assert.equal(rows[1].href, "/app/parts/records/R2");
});

test("setup: new org locks programs and actuals; failures say so", () => {
  const s = setupSteps({ ...EMPTY, records: [], machines: [], rates: { using_governed: false, source: "default_rate_card_v0", provenance: "default" } }, {});
  assert.deepEqual(s.map((x) => x.state), ["needed", "optional", "locked", "locked"]);
  const f = setupSteps({ ...EMPTY, records: [rec()], programs: 0, withVolume: 2 }, { machines: true, actuals: true });
  assert.deepEqual(f.map((x) => x.state), ["done", "failed", "optional", "failed"]);
  assert.equal(setupSteps({ ...EMPTY, records: [rec()] }, {})[3].state, "loading");
  assert.equal(f[2].meta, "2 parts with a yearly volume · 0 programs");
});

test("rate card names", () => {
  assert.equal(rateCardName({ using_governed: false, source: "default_rate_card_v0", provenance: "default" }), "Default rate card (v0)");
  assert.equal(rateCardName({ using_governed: true, source: "governed", provenance: "user" }), "Your rate card");
});

test("verdict: a blocked route wins over the machine bucket", () => {
  const blocked = part({ unit_cost: { usd: null, qty: 10, withheld: true, withheld_reason: "below 1.5mm min wall", validated: false } });
  const v = verdictOf(blocked, { verdict: "makeable_in_house", stale: true, gap: null });
  assert.equal(v.key, "design");
  assert.equal(v.label, "Thicker wall needed");
  assert.equal(v.stale, true);
  assert.equal(priceText(blocked), "—");
});

test("verdict: buckets map to plain labels; no bucket row is 'No machine check', never 'Not checked'", () => {
  assert.equal(verdictOf(part(), { verdict: "makeable_in_house", stale: false, gap: null }).label, "On your machines");
  assert.equal(verdictOf(part(), { verdict: "environment_excluded", stale: false, gap: null }).key, "out");
  assert.equal(verdictOf(part(), null).label, "No machine check");
  assert.equal(VERDICT_FILTERS.find((f) => f.key === "unknown")?.label, "No machine check");
  assert.equal(priceText(part()), "$19.05 at 10");
  assert.equal(partQuery(part()), "?lens=make&qty=10");
  assert.equal(partQuery(part({ unit_cost: null })), "");
  const big = verdictOf(part(), { verdict: "makeable_not_on_owned", stale: false, gap: { gap: [{ gate: "envelope", axis: "minimum_width_mm", need: 268.81, have: 254.0000001, human: "x" }] } });
  assert.equal(big.label, "Bigger machine");
  assert.equal(big.where, "Needs 269 mm; your machines take 254 mm");
  assert.equal(gapLine({ gate: "material", axis: "material", need: "PEEK", have: ["steel"], human: "not qualified for PEEK" }), "Your machines aren't set up for PEEK");
});

test("filters, search over name and part id, counts", () => {
  const a = part();
  const b = part({ part_key: "ffee" + "0".repeat(60), filename: "Shell.STL", findings: null, lifecycle_state: "Drafted", unit_cost: null });
  const va = verdictOf(a, { verdict: "makeable_in_house", stale: true, gap: null });
  const vb = verdictOf(b, null);
  assert.equal(matches(b, vb, { ...NO_FILTER, q: "shell" }), true);
  assert.equal(matches(b, vb, { ...NO_FILTER, q: "ffee" }), true);
  assert.equal(matches(a, va, { ...NO_FILTER, q: "shell" }), false);
  assert.equal(matches(b, vb, { ...NO_FILTER, finds: "with" }), false);
  assert.equal(matches(b, vb, { ...NO_FILTER, finds: "none" }), false, "unknown findings are neither with nor without");
  assert.equal(matches(b, vb, { ...NO_FILTER, stage: "drafted" }), true);
  assert.equal(matches(a, va, { ...NO_FILTER, machines: "stale" }), true);
  const c = countBy([va, vb]);
  assert.equal(c.in, 1);
  assert.equal(c.unknown, 1);
  assert.equal(c.stale, 1);
  assert.deepEqual(partsFacts(2, 1, c).map((f) => `${f.n} ${f.t}`), ["2 parts", "1 costed", "1 on your machines as drawn"]);
});

test("filter round-trips through the URL and rejects junk", () => {
  const f = { q: "disk", stage: "costed" as const, finds: "with" as const, machines: "design" as const };
  const s = searchFromFilter(f);
  assert.equal(s, "?q=disk&stage=costed&findings=with&machines=design");
  assert.deepEqual(filterFromSearch(new URLSearchParams(s)), f);
  assert.deepEqual(filterFromSearch(new URLSearchParams("?machines=hack&stage=x")), NO_FILTER);
  assert.equal(searchFromFilter(NO_FILTER), "");
});

test("words", () => {
  assert.equal(wayName("cnc_turning"), "Turning");
  assert.equal(wayName("new_process"), "New process");
  assert.equal(tidyReason("24 faces (100.0%) below 1.5mm min wall for ded. Thinnest: 0.5mm."), "24 faces below 1.5 mm min wall · thinnest 0.5 mm");
  assert.equal(sizeText([20, 15.2, 6.04]), "20 × 15 × 6 mm");
  assert.equal(shortWhen("2026-10-17T05:00:00", new Date("2026-10-18T12:00:00")), "Oct 17");
});

test("peek figures: price, range and machine; withheld stays withheld", async () => {
  const { peekFigs, verdictOf: vo } = await import("./parts-derive.ts");
  const row = part();
  const v = vo(row, { verdict: "makeable_in_house", stale: false, gap: null });
  const d = { result: { estimates: [{ process: "cnc_3axis", quantity: 10, unit_cost_usd: 19.05, confidence: { low_usd: 9.53, high_usd: 28.58, half_width_pct: 50, validated: false } }], verification: { per_route: { cnc_3axis: { verdict: "makeable_in_house", best_machine: "Haas VF-2" } } } } };
  const f = peekFigs(row, v, d);
  assert.deepEqual(f.map((x) => `${x.k}=${x.v}|${x.s}`), ["Each, at 10=$19.05|Haas VF-2, yours", "Range=$9.53–$28.58|±50%, no real costs yet", "Machines=On your machines|3-axis milling · 6061-T6 Aluminum"]);
  const w = part({ unit_cost: { usd: null, qty: 10, withheld: true, withheld_reason: "thin", validated: false } });
  assert.equal(peekFigs(w, vo(w, null), null)[0].v, "Withheld");
  assert.equal(peekFigs(w, vo(w, null), null).length, 2, "no range for a withheld price");
});

test("ce-19: the list's price is at the part page's quantity, and says when that's the yearly one", () => {
  const uc = { usd: 36.69, qty: 100, currency: "USD", withheld: false, withheld_reason: null, validated: false };
  assert.equal(priceText({ unit_cost: { ...uc, qty_basis: "default", declared_qty: 800 } } as never), "$36.69 at 100");
  assert.equal(priceText({ unit_cost: { ...uc, usd: 25.32, qty: 1000, qty_basis: "declared", declared_qty: 1000 } } as never), "$25.32 at 1,000 a year");
});
