/**
 * Record derivations: cheapest vs your machines' way, outcome locks (mirroring
 * the server's rules), cost inputs and sources, the Compare table's "cheapest
 * workable material per way", and the list's summary lines and filters.
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --test src/components/v4/records/facts.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { CostEstimate, CostReport, CostDecisionSummary } from "@/lib/api";
import {
  answerLine,
  cheapestAt,
  cheapestWorkableAt,
  chartPaths,
  costLines,
  driverLabel,
  defaultQty,
  groupByPart,
  inHouseAt,
  keepRecord,
  outcomeLocks,
  rangeOf,
  recordFacts,
  routeOptions,
  sharedQuantities,
  statusOf,
  summaryLines,
  toolingChart,
  wayCell,
  wayTable,
  waysCount,
} from "./facts.ts";
import { conditionsTag, conditionsText, rowTime, stampUtc } from "./words.ts";

function est(p: Partial<CostEstimate> & { process: string; material: string; quantity: number; unit_cost_usd: number }): CostEstimate {
  return {
    fixed_cost_usd: 0,
    variable_cost_usd: 0,
    est_error_band_pct: 50,
    dfm_ready: true,
    dfm_verdict: "issues",
    dfm_score: 0.9,
    dfm_blockers: [],
    line_items: {},
    drivers: [],
    lead_time: { low_days: 7, high_days: 13, mid_days: 10, components: {}, capacity: {} },
    ...p,
  } as CostEstimate;
}

function report(over: Partial<CostReport> = {}): CostReport {
  return {
    filename: "bored-block-mm.iges",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 2.72, surface_area_cm2: 14.3, bbox_mm: [20, 15, 10], watertight: true, face_count: 100 },
    material_class: "stainless",
    quantities: [1, 10],
    estimates: [
      est({ process: "binder_jetting", material: "SS316L", quantity: 10, unit_cost_usd: 15, est_error_band_pct: 55 }),
      est({ process: "binder_jetting", material: "SS316L", quantity: 1, unit_cost_usd: 150, est_error_band_pct: 55 }),
      est({
        process: "cnc_3axis",
        material: "API 13Cr",
        quantity: 10,
        unit_cost_usd: 31.54,
        confidence: { low_usd: 15.77, high_usd: 47.31, point_usd: 31.54, level: 0.8, method: "assumption-band", validated: false, n_samples: 0, half_width_pct: 50, basis: "", label: "" },
        drivers: [
          { name: "material_cost", value: 0.12, unit: "$", provenance: "DEFAULT", source: "billet", error_band_pct: 5 },
          { name: "machine_cost", value: 1.43, unit: "$", provenance: "USER", source: "Haas VF-2 at $85/hr", error_band_pct: 20 },
          { name: "cycle_time", value: 0.03, unit: "hr", provenance: "DEFAULT", source: "rough", error_band_pct: 50 },
        ],
      }),
      est({ process: "cnc_3axis", material: "17-4PH", quantity: 10, unit_cost_usd: 33 }),
      est({ process: "cnc_3axis", material: "API 13Cr", quantity: 1, unit_cost_usd: 133.92 }),
      est({ process: "forging", material: "API 13Cr", quantity: 10, unit_cost_usd: 1227, dfm_ready: false, dfm_verdict: "fail" }),
      est({ process: "forging", material: "API 13Cr", quantity: 1, unit_cost_usd: 12121, dfm_ready: false, dfm_verdict: "fail" }),
      est({ process: "die_casting", material: "A380", quantity: 10, unit_cost_usd: 900, environment_excluded: true }),
    ],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: {
      make_now_process: "wire_edm",
      make_now_material: "API 13Cr",
      tooling_process: "forging",
      tooling_dfm_ready: false,
      crossover_qty: null,
      recommendation: {
        "1": { process: "binder_jetting", material: "SS316L", unit_cost_usd: 150, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 10.5, lead_high_days: 19.5 },
        "10": { process: "binder_jetting", material: "SS316L", unit_cost_usd: 15, dfm_ready: true, dfm_verdict: "issues", lead_low_days: 10.5, lead_high_days: 19.5 },
      },
      if_redesigned: {},
      note: "",
    },
    verification: {
      verdict: "makeable_in_house",
      best_machine: "Haas VF-2",
      per_route: {
        cnc_3axis: { verdict: "makeable_in_house", best_machine: "Haas VF-2", machines_evaluated: 1, failures: [] },
        binder_jetting: { verdict: "makeable_outsource_only", best_machine: null, machines_evaluated: 0, failures: [] },
      },
      env_exclusions: [{ gate: "environment", axis: "A380", need: "", have: null, human: "A380 excluded" }],
      inventory_declared: true,
      environment_declared: true,
    },
    ...over,
  } as CostReport;
}

test("cheapest is the engine's recommendation; your way is your machine's cheapest surviving material", () => {
  const r = report();
  assert.equal(cheapestAt(r, 10)?.usd, 15);
  assert.equal(cheapestAt(r, 10)?.est?.material, "SS316L");
  assert.equal(cheapestAt(r, 100), null);
  const mine = inHouseAt(r, 10);
  assert.equal(mine.length, 1);
  assert.equal(mine[0].material, "API 13Cr");
  assert.equal(mine[0].machine, "Haas VF-2");
  assert.equal(inHouseAt(report({ verification: null }), 10).length, 0);
});

test("facts and the answer line read the verification block, never invent a verdict", () => {
  const f = recordFacts(report());
  assert.equal(f.material, "Stainless");
  assert.equal(f.envDeclared, true);
  assert.equal(f.verdictLabel, "In-house");
  assert.deepEqual(f.ruledOut, ["A380"]);
  assert.equal(answerLine(report(), 10), "On your Haas VF-2 · $31.54 at 10 · outside $15.00");
  const none = recordFacts(report({ verification: null }));
  assert.equal(none.envDeclared, null);
  assert.equal(none.verdictLabel, "Not checked");
  assert.match(answerLine(report({ verification: null }), 10), /^Priced before machines were added · cheapest \$15\.00 by metal binder jetting$/);
});

test("default quantity: recorded outcome, else 10, else the first", () => {
  assert.equal(defaultQty({ result: report(), disposition_basis: { process: "x", material: "y", quantity: 1 } }), 1);
  assert.equal(defaultQty({ result: report(), disposition_basis: null }), 10);
  assert.equal(defaultQty({ result: report({ quantities: [50, 5000] }), disposition_basis: null }), 50);
});

test("route options put your machine first and add the cheapest when it differs", () => {
  const opts = routeOptions(report(), 10);
  assert.deepEqual(opts.map((o) => [o.process, o.mine]), [["cnc_3axis", true], ["binder_jetting", false]]);
  assert.equal(opts[0].label, "Your Haas VF-2: 3-axis milling · $31.54");
  assert.equal(routeOptions(report(), 100).length, 0);
});

test("outcome locks mirror the server: in-house needs your route, outside needs DFM, ruled-out routes take nothing", () => {
  const r = report();
  const [mine, cheapest] = routeOptions(r, 10);
  const onMine = outcomeLocks(r, mine, 10, true);
  assert.equal(onMine.inhouse, null);
  assert.equal(onMine.outside, null);
  const onCheapest = outcomeLocks(r, cheapest, 10, true);
  assert.match(onCheapest.inhouse ?? "", /Pick your machine's route above/);
  assert.equal(onCheapest.redesign, null);
  const forging = { value: "forging~API 13Cr", label: "", process: "forging", material: "API 13Cr", mine: false, est: r.estimates.find((e) => e.process === "forging" && e.quantity === 10)! };
  const f = outcomeLocks(r, forging, 10, false);
  assert.match(f.outside ?? "", /can't make the part as drawn/);
  assert.equal(f.redesign, null);
  assert.equal(f.acquire, null);
  const die = { ...forging, process: "die_casting", est: r.estimates.find((e) => e.process === "die_casting")! };
  assert.ok(Object.values(outcomeLocks(r, die, 10, false)).every((v) => v && /rule out/.test(v)));
  assert.ok(Object.values(outcomeLocks(r, null, 100, false)).every((v) => v && /No computed price at 100/.test(v)));
});

test("cost inputs keep only dollar drivers and say where each came from", () => {
  const e = routeOptions(report(), 10)[0].est;
  const lines = costLines(e);
  assert.deepEqual(lines.map((l) => [l.label, l.usd, l.srcLabel]), [["Material, API 13Cr", 0.12, "Typical"], ["Machine time", 1.43, "Yours"]]);
  assert.deepEqual(rangeOf(e), { text: "$15.77–$47.31", pct: 50, validated: false, n: 0 });
  const plain = rangeOf(cheapestAt(report(), 10)?.est);
  assert.equal(plain?.text, "$6.75–$23.25");
});

test("a spec's cost input reads as the spec is named (buyer-07)", () => {
  const e = { ...routeOptions(report(), 10)[0].est, drivers: [
    { name: "spec_fai_as9102_cost", value: 0.84, unit: "$", provenance: "DEFAULT", source: "6 h per order" },
    { name: "spec_anodize_ii_cost", value: 1.96, unit: "$", provenance: "DEFAULT", source: "" },
    { name: "spec_new_thing_cost", value: 1, unit: "$", provenance: "DEFAULT", source: "" },
  ] } as CostEstimate;
  assert.deepEqual(costLines(e).map((l) => l.label), ["First article inspection (AS9102)", "Anodize (Type II)", "New thing"]);
  assert.equal(driverLabel("spec_fai_as9102_cost"), "First article inspection (AS9102)");
});

test("compare: cheapest workable material per way, redesign-only and ruled-out cells", () => {
  const r = report();
  assert.deepEqual(wayCell(r, "cnc_3axis", 10), { usd: 31.54, band: 50, state: "ok", material: "API 13Cr" });
  assert.equal(wayCell(r, "forging", 10)?.state, "redesign");
  assert.equal(wayCell(r, "die_casting", 10)?.state, "out");
  assert.equal(wayCell(r, "sla", 10), null);
  const b = report({ estimates: r.estimates.map((e) => (e.process === "cnc_3axis" && e.material === "API 13Cr" && e.quantity === 10 ? { ...e, unit_cost_usd: 34.69 } : e)) });
  const rows = wayTable(r, b, 10);
  assert.equal(rows[0].process, "binder_jetting");
  assert.ok(rows[0].pick);
  const cnc = rows.find((x) => x.process === "cnc_3axis")!;
  assert.equal(cnc.pct, 5); // B's cheapest workable cnc material is 17-4PH at $33
  assert.equal(rows.find((x) => x.process === "die_casting")!.pct, null);
  assert.deepEqual(sharedQuantities(r, report({ quantities: [10, 100] })), [10]);
  assert.deepEqual(waysCount(r, 10), { ok: 2, redesign: 1 });
});

test("tooling chart only when both curves are priced; paths stay inside the box", () => {
  const c = toolingChart(report());
  assert.ok(c);
  assert.deepEqual(c!.qs, [1, 10]);
  assert.deepEqual(c!.tool, [12121, 1227]);
  assert.equal(c!.toolNeedsRedesign, true);
  const p = chartPaths(c!, 1);
  assert.match(p.make, /^M8\.0 \d+\.\d L592\.0 \d+\.\d$/);
  assert.equal(p.marker, "M592.0 4V186");
  assert.equal(toolingChart(report({ decision: { ...report().decision!, tooling_process: null } })), null);
});

test("list rows: summary lines, status, filters and grouping by part", () => {
  const s = {
    id: "01M56P3X598SYXRY84VKKZAEQ1",
    mesh_hash: "aaa",
    filename: "bored-block-mm.iges",
    file_type: "iges",
    label: null,
    make_now_process: "wire_edm",
    crossover_qty: 4018.4,
    quantities: [10, 1, 10000],
    created_at: "2026-10-18T05:00:33Z",
    is_public: false,
    share_url: null,
  } as CostDecisionSummary;
  assert.deepEqual(summaryLines(s), { what: "ScaleCAD’s pick: Wire EDM", answer: "priced at 1 to 10,000 · tooling pays off near 4,018 · #AEQ1".replace("#AEQ1", "#KZAEQ1") });
  const decided = { ...s, user_disposition: "inhouse" as const, user_disposition_label: "Make in-house", disposition_basis: { process: "cnc_3axis", material: "API 13Cr", quantity: 10 } };
  assert.equal(summaryLines(decided).what, "Make in-house · 3-axis milling at 10");
  assert.deepEqual(statusOf(decided), { label: "Decided", tone: "ok" });
  assert.deepEqual(statusOf({ ...decided, approval_status: "approved" }), { label: "Approved", tone: "ok" });
  assert.deepEqual(statusOf({ ...decided, is_stale: true }), { label: "Out of date", tone: "warn" });
  assert.equal(keepRecord(s, "decided"), false);
  assert.equal(keepRecord(decided, "decided"), true);
  assert.equal(keepRecord({ ...s, approval_status: "approved" }, "review"), false);
  const g = groupByPart([s, { ...s, id: "b", mesh_hash: "bbb", filename: "x.stl" }, { ...s, id: "c" }]);
  assert.deepEqual(g.map((x) => [x.filename, x.rows.length]), [["bored-block-mm.iges", 2], ["x.stl", 1]]);
});

test("words: conditions, UTC stamps and row times", () => {
  const env = { medium: "sour gas (H2S)", standard: "NACE MR0175", min_temp_c: -20, max_temp_c: 120, pressure_bar: 350, sour_service: true };
  assert.equal(conditionsText(env), "Sour gas (H2S), −20 to 120 °C, 350 bar, NACE MR0175");
  assert.equal(conditionsTag(env), "sour gas");
  assert.equal(conditionsText({}), null);
  assert.equal(stampUtc("2026-10-18T05:00:33Z"), "Oct 18, 2026, 05:00 UTC");
  assert.equal(rowTime("2026-10-18T05:00:33Z", new Date("2026-10-18T09:00:00Z")), "05:00");
  assert.equal(rowTime("2026-10-17T05:00:33Z", new Date("2026-10-18T09:00:00Z")), "Oct 17");
});

test("compare's cheapest is the cheapest way that works as drawn, the same one the table marks", () => {
  // The engine recommends a route without tooling at 1,000; molding is cheaper and workable after the draft fix.
  const revB = report({
    quantities: [1000],
    estimates: [
      est({ process: "fdm", material: "PLA", quantity: 1000, unit_cost_usd: 18.34 }),
      est({ process: "injection_molding", material: "ABS", quantity: 1000, unit_cost_usd: 17.03 }),
      est({ process: "sls", material: "PA12", quantity: 1000, unit_cost_usd: 12, dfm_ready: false, dfm_verdict: "fail" }),
      est({ process: "die_casting", material: "A380", quantity: 1000, unit_cost_usd: 5, environment_excluded: true }),
    ],
    decision: { ...report().decision!, recommendation: { "1000": { process: "fdm", material: "PLA", unit_cost_usd: 18.34, dfm_ready: true, dfm_verdict: "pass", lead_low_days: 5, lead_high_days: 9 } } },
  });
  assert.equal(cheapestAt(revB, 1000)?.process, "fdm");
  const best = cheapestWorkableAt(revB, 1000);
  assert.equal(best?.process, "injection_molding");
  assert.equal(best?.usd, 17.03);
  assert.equal(best?.leadLo, 7);
  const rows = wayTable(revB, revB, 1000);
  assert.deepEqual(rows.filter((r) => r.pick).map((r) => r.process), ["injection_molding"]);
  assert.equal(cheapestWorkableAt(revB, 10), null);
});

test("a record's cost lines add up to its price, with a Rounding line (ce-01)", () => {
  const e = {
    ...routeOptions(report(), 10)[0].est,
    unit_cost_usd: 23.82,
    // The stepped shaft at 100 as she rebuilt it: three lines round up, $23.84 against $23.82.
    line_items: { nre: 0.35, labor: 10.5, machine: 9.73, material: 1.5665, inspection: 1.015, consumables: 0.4865, amortized_fixed: 0.175 },
  } as CostEstimate;
  const lines = costLines(e);
  assert.deepEqual(lines.map((l) => l.usd), [0.35, 10.5, 9.73, 1.57, 1.02, 0.49, 0.18, -0.02]);
  assert.equal(lines.at(-1)!.label, "Rounding");
  assert.equal(Math.round(lines.reduce((s, l) => s + l.usd, 0) * 100), 2382);
});
