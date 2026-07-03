import { test } from "node:test";
import assert from "node:assert/strict";
import {
  crossoverFragility,
  assessPart,
  partInQueue,
  buildExceptionQueues,
  portfolioPulse,
  bestRedesignSaving,
  rankRedesignSavings,
  formatPct,
  formatUsd0,
  EXCEPTION_QUEUES,
  DEFAULT_HEAVY_THRESHOLD,
  FRAGILITY_FACTOR,
  type PartSignal,
} from "./portfolio.ts";
import { deriveCatalogMetrics } from "./catalog.ts";
import type {
  CostReport,
  CostEstimate,
  CostDriver,
  CostDecision,
  Provenance,
} from "./api.ts";

/* ------------------------------------------------------------------ */
/*  Minimal real-shaped fixtures (mirrors catalog.test.ts)             */
/* ------------------------------------------------------------------ */

function driver(name: string, provenance: Provenance): CostDriver {
  return { name, value: 1, unit: "$", provenance, source: `${name} src`, error_band_pct: null };
}

function estimate(over: Partial<CostEstimate> = {}): CostEstimate {
  return {
    process: "cnc_3axis",
    material: "aluminum",
    quantity: 50,
    unit_cost_usd: 42.5,
    fixed_cost_usd: 100,
    variable_cost_usd: 40,
    est_error_band_pct: 20,
    dfm_ready: true,
    dfm_verdict: "pass",
    dfm_score: 90,
    dfm_blockers: [],
    line_items: {},
    drivers: [driver("machine_cost", "DEFAULT"), driver("material_cost", "MEASURED")],
    lead_time: { low_days: 5, high_days: 9, mid_days: 7, components: {}, capacity: {} },
    ...over,
  };
}

function decision(over: Partial<CostDecision> = {}): CostDecision {
  return {
    make_now_process: "cnc_3axis",
    make_now_material: "aluminum",
    tooling_process: null,
    tooling_dfm_ready: false,
    crossover_qty: null,
    recommendation: {},
    if_redesigned: {},
    note: "",
    ...over,
  };
}

function report(over: Partial<CostReport> = {}): CostReport {
  return {
    filename: "bracket.step",
    status: "OK",
    reason: null,
    geometry: {
      volume_cm3: 12,
      surface_area_cm2: 80,
      bbox_mm: [40, 30, 20],
      watertight: true,
      face_count: 240,
    },
    material_class: "aluminum",
    quantities: [50, 5000],
    estimates: [estimate()],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: decision(),
    ...over,
  };
}

/** Build a PartSignal off a real report — exercises the REAL derivation path. */
function signal(id: string, over: Partial<CostReport> = {}): PartSignal {
  const r = report(over);
  return {
    id,
    label: id,
    metrics: deriveCatalogMetrics(r),
    crossoverQty: r.decision?.crossover_qty ?? null,
    costedQuantities: Array.from(new Set(r.estimates.map((e) => e.quantity)))
      .filter((q) => q > 0)
      .sort((a, b) => a - b),
  };
}

/* ------------------------------------------------------------------ */
/*  crossoverFragility()                                               */
/* ------------------------------------------------------------------ */

test("crossoverFragility: null when no crossover or no costed quantity", () => {
  assert.equal(crossoverFragility(null, [50, 5000]), null);
  assert.equal(crossoverFragility(0, [50, 5000]), null);
  assert.equal(crossoverFragility(-10, [50, 5000]), null);
  assert.equal(crossoverFragility(100, []), null);
  assert.equal(crossoverFragility(100, [0, -5]), null); // no positive qty
});

test("crossoverFragility: fragile when crossover within FRAGILITY_FACTOR× of an order", () => {
  // crossover 120 vs order 50 → ratio 2.4 ≤ 4 → fragile, nearest is 50
  const f = crossoverFragility(120, [50, 5000]);
  assert.ok(f);
  assert.equal(f.crossoverQty, 120);
  assert.equal(f.nearestQty, 50);
  assert.ok(f.ratio > 2.39 && f.ratio < 2.41);
});

test("crossoverFragility: robust when crossover far from every costed order", () => {
  // crossover 500,000 vs orders 50 & 5000 → nearest ratio 100 > 4 → not fragile
  assert.equal(crossoverFragility(500000, [50, 5000]), null);
});

test("crossoverFragility: boundary — exactly FRAGILITY_FACTOR× is still fragile", () => {
  const f = crossoverFragility(50 * FRAGILITY_FACTOR, [50]);
  assert.ok(f);
  assert.equal(f.ratio, FRAGILITY_FACTOR);
  // one unit past the factor is robust
  assert.equal(crossoverFragility(50 * FRAGILITY_FACTOR + 1, [50]), null);
});

/* ------------------------------------------------------------------ */
/*  assessPart()                                                       */
/* ------------------------------------------------------------------ */

test("assessPart: DFM-blocked route → dfmRequired, blocker reason surfaced, flagged", () => {
  const s = signal("p1", {
    estimates: [
      estimate({
        dfm_ready: false,
        dfm_verdict: "fail",
        dfm_blockers: ["Wall 0.4mm below 0.8mm minimum", "Undercut on face 12"],
      }),
    ],
  });
  const a = assessPart(s);
  assert.equal(a.dfmRequired, true);
  assert.equal(a.blockerReason, "Wall 0.4mm below 0.8mm minimum");
  assert.equal(a.routeBlockerCount, 2);
  assert.equal(a.flagged, true);
});

test("assessPart: majority-DEFAULT drivers → defaultHeavy at/above threshold", () => {
  // 2 of 3 default = 0.667 ≥ 0.5 → default-heavy
  const s = signal("p2", {
    estimates: [
      estimate({
        drivers: [
          driver("machine_cost", "DEFAULT"),
          driver("labor_cost", "DEFAULT"),
          driver("material_cost", "MEASURED"),
        ],
      }),
    ],
  });
  const a = assessPart(s);
  assert.equal(a.defaultHeavy, true);
  assert.ok(Math.abs(a.guessPct - 2 / 3) < 1e-9);
  assert.equal(a.groundedDrivers, 1);
  assert.equal(a.totalDrivers, 3);
  assert.equal(a.flagged, true);
});

test("assessPart: minority-DEFAULT drivers → NOT defaultHeavy", () => {
  // 1 of 3 default = 0.333 < 0.5 → not default-heavy
  const s = signal("p3", {
    estimates: [
      estimate({
        drivers: [
          driver("machine_cost", "SHOP"),
          driver("labor_cost", "USER"),
          driver("material_cost", "DEFAULT"),
        ],
      }),
    ],
  });
  const a = assessPart(s);
  assert.equal(a.defaultHeavy, false);
  assert.equal(a.flagged, false); // grounded, not blocked, no crossover
});

test("assessPart: exactly at DEFAULT_HEAVY_THRESHOLD is included", () => {
  // 1 of 2 default = 0.5 === threshold → default-heavy
  const s = signal("p4", {
    estimates: [
      estimate({
        drivers: [driver("machine_cost", "DEFAULT"), driver("material_cost", "SHOP")],
      }),
    ],
  });
  const a = assessPart(s);
  assert.equal(a.guessPct, DEFAULT_HEAVY_THRESHOLD);
  assert.equal(a.defaultHeavy, true);
});

test("assessPart: fragile crossover → crossoverFragile with detail", () => {
  const s = signal("p5", {
    decision: decision({ crossover_qty: 120 }),
    estimates: [estimate({ quantity: 50 }), estimate({ quantity: 5000, unit_cost_usd: 20 })],
  });
  const a = assessPart(s);
  assert.equal(a.crossoverFragile, true);
  assert.equal(a.fragility?.nearestQty, 50);
  assert.equal(a.flagged, true);
});

test("assessPart: a part can fall into MULTIPLE queues (honest overlap)", () => {
  const s = signal("p6", {
    decision: decision({ crossover_qty: 120 }),
    estimates: [
      estimate({
        quantity: 50,
        dfm_ready: false,
        dfm_blockers: ["thin wall"],
        drivers: [driver("machine_cost", "DEFAULT"), driver("labor_cost", "DEFAULT")],
      }),
      estimate({ quantity: 5000, unit_cost_usd: 20, dfm_ready: false, dfm_blockers: ["thin wall"] }),
    ],
  });
  const a = assessPart(s);
  assert.equal(a.dfmRequired, true);
  assert.equal(a.defaultHeavy, true);
  assert.equal(a.crossoverFragile, true);
  for (const q of EXCEPTION_QUEUES) assert.equal(partInQueue(a, q.id), true);
});

test("assessPart: clean part → no flags, not in any queue", () => {
  const s = signal("clean", {
    estimates: [
      estimate({ drivers: [driver("machine_cost", "SHOP"), driver("material_cost", "MEASURED")] }),
    ],
  });
  const a = assessPart(s);
  assert.equal(a.flagged, false);
  for (const q of EXCEPTION_QUEUES) assert.equal(partInQueue(a, q.id), false);
});

/* ------------------------------------------------------------------ */
/*  buildExceptionQueues()                                            */
/* ------------------------------------------------------------------ */

test("buildExceptionQueues: ranked worst-first, counts + cohorts are real", () => {
  // Each fixture is isolated to exactly ONE queue (grounded drivers where the
  // signal under test isn't posture, so the overlap doesn't muddy the cohorts).
  const grounded = [driver("a", "SHOP"), driver("b", "MEASURED")];
  const blocked = assessPart(
    signal("blk", {
      estimates: [estimate({ dfm_ready: false, dfm_blockers: ["x"], drivers: grounded })],
    })
  );
  const guessy = assessPart(
    signal("gss", {
      estimates: [estimate({ drivers: [driver("a", "DEFAULT"), driver("b", "DEFAULT")] })],
    })
  );
  const fragile = assessPart(
    signal("frg", {
      decision: decision({ crossover_qty: 120 }),
      estimates: [
        estimate({ quantity: 50, drivers: grounded }),
        estimate({ quantity: 5000, unit_cost_usd: 20, drivers: grounded }),
      ],
    })
  );
  const clean = assessPart(
    signal("cln", {
      estimates: [estimate({ drivers: [driver("a", "SHOP"), driver("b", "MEASURED")] })],
    })
  );

  const queues = buildExceptionQueues([blocked, guessy, fragile, clean]);
  assert.deepEqual(
    queues.map((q) => q.id),
    ["dfm-required", "default-heavy", "crossover-fragile"]
  );
  const byId = Object.fromEntries(queues.map((q) => [q.id, q]));
  assert.deepEqual(byId["dfm-required"].memberIds, ["blk"]);
  assert.deepEqual(byId["default-heavy"].memberIds, ["gss"]);
  assert.deepEqual(byId["crossover-fragile"].memberIds, ["frg"]);
  assert.equal(byId["dfm-required"].count, 1);
});

test("buildExceptionQueues: preserves input order within a cohort (newest-first)", () => {
  const a = assessPart(signal("a", { estimates: [estimate({ dfm_ready: false, dfm_blockers: ["x"] })] }));
  const b = assessPart(signal("b", { estimates: [estimate({ dfm_ready: false, dfm_blockers: ["x"] })] }));
  const queues = buildExceptionQueues([a, b]);
  const dfm = queues.find((q) => q.id === "dfm-required");
  assert.deepEqual(dfm?.memberIds, ["a", "b"]);
});

/* ------------------------------------------------------------------ */
/*  portfolioPulse()                                                   */
/* ------------------------------------------------------------------ */

test("portfolioPulse: real counts + posture % over the assessed parts only", () => {
  const blocked = assessPart(
    signal("blk", {
      estimates: [
        estimate({
          dfm_ready: false,
          dfm_blockers: ["x"],
          drivers: [driver("a", "DEFAULT"), driver("b", "DEFAULT")],
        }),
      ],
    })
  );
  const clean = assessPart(
    signal("cln", {
      estimates: [estimate({ drivers: [driver("a", "SHOP"), driver("b", "MEASURED")] })],
    })
  );

  const pulse = portfolioPulse([blocked, clean]);
  assert.equal(pulse.assessed, 2);
  assert.equal(pulse.flagged, 1); // only blocked
  assert.equal(pulse.clean, 1);
  assert.equal(pulse.dfmRequired, 1);
  assert.equal(pulse.defaultHeavy, 1); // blocked route is also all-default
  // posture: blocked route 0/2 grounded + clean route 2/2 grounded = 2/4
  assert.equal(pulse.groundedDrivers, 2);
  assert.equal(pulse.totalDrivers, 4);
  assert.equal(pulse.groundedPct, 0.5);
});

test("portfolioPulse: empty portfolio → all zero, no divide-by-zero", () => {
  const pulse = portfolioPulse([]);
  assert.equal(pulse.assessed, 0);
  assert.equal(pulse.flagged, 0);
  assert.equal(pulse.clean, 0);
  assert.equal(pulse.groundedPct, 0);
});

/* ------------------------------------------------------------------ */
/*  bestRedesignSaving() / rankRedesignSavings()                       */
/* ------------------------------------------------------------------ */

function withRedesign(): CostDecision {
  return decision({
    recommendation: {
      "50": {
        process: "cnc_3axis",
        material: "aluminum",
        unit_cost_usd: 100,
        dfm_ready: true,
        dfm_verdict: "pass",
        lead_low_days: 5,
        lead_high_days: 9,
      },
      "5000": {
        process: "cnc_3axis",
        material: "aluminum",
        unit_cost_usd: 80,
        dfm_ready: true,
        dfm_verdict: "pass",
        lead_low_days: 5,
        lead_high_days: 9,
      },
    },
    if_redesigned: {
      "50": {
        process: "injection_molding",
        material: "aluminum",
        unit_cost_usd: 90,
        caveat: "Requires draft + tooling amortization.",
      },
      "5000": {
        process: "injection_molding",
        material: "aluminum",
        unit_cost_usd: 40,
        caveat: "Requires draft + tooling amortization.",
      },
    },
  });
}

test("bestRedesignSaving: picks the deepest real per-part delta, engine caveat verbatim", () => {
  const s = bestRedesignSaving("p", "bracket", withRedesign());
  assert.ok(s);
  // qty 5000: 80 → 40 = 50% saving beats qty 50: 100 → 90 = 10%
  assert.equal(s.qty, 5000);
  assert.equal(s.makeNowUsd, 80);
  assert.equal(s.redesignedUsd, 40);
  assert.equal(s.saveUsd, 40);
  assert.equal(s.savePct, 0.5);
  assert.equal(s.redesignedProcess, "injection_molding");
  assert.equal(s.caveat, "Requires draft + tooling amortization.");
});

test("bestRedesignSaving: null when no redesign is cheaper (never a $0 saving)", () => {
  const d = decision({
    recommendation: {
      "50": {
        process: "cnc_3axis",
        material: "aluminum",
        unit_cost_usd: 50,
        dfm_ready: true,
        dfm_verdict: "pass",
        lead_low_days: null,
        lead_high_days: null,
      },
    },
    if_redesigned: {
      "50": {
        process: "sls",
        material: "nylon",
        unit_cost_usd: 70, // pricier — not a saving
        caveat: "n/a",
      },
    },
  });
  assert.equal(bestRedesignSaving("p", "x", d), null);
  assert.equal(bestRedesignSaving("p", "x", null), null);
  assert.equal(bestRedesignSaving("p", "x", decision()), null); // empty maps
});

test("bestRedesignSaving: skips null if_redesigned entries", () => {
  const d = decision({
    recommendation: {
      "50": {
        process: "cnc_3axis",
        material: "aluminum",
        unit_cost_usd: 100,
        dfm_ready: true,
        dfm_verdict: "pass",
        lead_low_days: null,
        lead_high_days: null,
      },
    },
    if_redesigned: { "50": null },
  });
  assert.equal(bestRedesignSaving("p", "x", d), null);
});

test("rankRedesignSavings: ranks parts deepest-first, omits parts with no saving", () => {
  const rows = rankRedesignSavings([
    { id: "deep", label: "deep", decision: withRedesign() }, // 50% best
    {
      id: "shallow",
      label: "shallow",
      decision: decision({
        recommendation: {
          "50": {
            process: "cnc_3axis",
            material: "aluminum",
            unit_cost_usd: 100,
            dfm_ready: true,
            dfm_verdict: "pass",
            lead_low_days: null,
            lead_high_days: null,
          },
        },
        if_redesigned: {
          "50": { process: "sls", material: "nylon", unit_cost_usd: 90, caveat: "c" },
        },
      }),
    }, // 10%
    { id: "none", label: "none", decision: decision() }, // no saving → omitted
  ]);
  assert.deepEqual(
    rows.map((r) => r.id),
    ["deep", "shallow"]
  );
  assert.equal(rows[0].savePct, 0.5);
});

test("bestRedesignSaving: make-now/redesigned come from the REAL engine fields only", () => {
  // A decision shaped EXACTLY as backend report_to_dict serialises it (every
  // real key on both tiers, JSONB string qty keys). make-now MUST read
  // recommendation[qty].unit_cost_usd; redesigned MUST read
  // if_redesigned[qty].unit_cost_usd — never any other/absent field.
  const d = decision({
    make_now_process: "cnc_3axis",
    recommendation: {
      "250": {
        process: "cnc_3axis",
        material: "aluminum",
        unit_cost_usd: 60,
        dfm_ready: true,
        dfm_verdict: "pass",
        lead_low_days: 5,
        lead_high_days: 9,
      },
    },
    if_redesigned: {
      "250": {
        process: "injection_molding",
        material: "abs",
        unit_cost_usd: 24,
        caveat: "invest in tooling",
      },
    },
  });
  const s = bestRedesignSaving("p", "housing", d);
  assert.ok(s);
  assert.equal(s.qty, 250); // string JSONB key resolved (mirrors cost-decision lookupByQty)
  assert.equal(s.makeNowUsd, 60); // recommendation[qty].unit_cost_usd
  assert.equal(s.redesignedUsd, 24); // if_redesigned[qty].unit_cost_usd
  assert.equal(s.saveUsd, 36);
  assert.equal(s.savePct, 0.6);
  assert.equal(s.redesignedProcess, "injection_molding");
  assert.equal(s.caveat, "invest in tooling");

  // The derivation must NOT invent a make-now cost from a fabricated field: a
  // recommendation entry missing unit_cost_usd yields no (finite) saving.
  const dNoCost = decision({
    recommendation: {
      "250": {
        process: "cnc_3axis",
        material: "aluminum",
        // unit_cost_usd deliberately absent
        dfm_ready: true,
        dfm_verdict: "pass",
        lead_low_days: null,
        lead_high_days: null,
      } as unknown as CostDecision["recommendation"][string],
    },
    if_redesigned: {
      "250": { process: "injection_molding", material: "abs", unit_cost_usd: 24, caveat: "c" },
    },
  });
  assert.equal(bestRedesignSaving("p", "housing", dNoCost), null);
});

/* ------------------------------------------------------------------ */
/*  Format helpers                                                     */
/* ------------------------------------------------------------------ */

test("formatPct / formatUsd0: honest strings, em-dash for missing", () => {
  assert.equal(formatPct(0.625), "63%");
  assert.equal(formatPct(0), "0%");
  assert.equal(formatPct(Number.NaN), "—");
  assert.equal(formatUsd0(1240.7), "$1,241");
  assert.equal(formatUsd0(null), "—");
  assert.equal(formatUsd0(Number.NaN), "—");
});

test("EXCEPTION_QUEUES: three stable ids in worst-first order, each with real copy", () => {
  assert.deepEqual(
    EXCEPTION_QUEUES.map((q) => q.id),
    ["dfm-required", "default-heavy", "crossover-fragile"]
  );
  for (const q of EXCEPTION_QUEUES) {
    assert.ok(q.label.length > 0);
    assert.ok(q.description.length > 0);
    assert.ok(["fail", "warn", "info"].includes(q.tone));
  }
});
