import { test } from "node:test";
import assert from "node:assert/strict";
import {
  posture,
  makeNowEstimate,
  deriveCatalogMetrics,
  matchesSavedView,
  lifecycleRank,
  formatUnitUsd,
  savedViewById,
  SAVED_VIEWS,
} from "./catalog.ts";
import type {
  CostReport,
  CostEstimate,
  CostDriver,
  CostDecision,
  Provenance,
} from "./api.ts";

/* ------------------------------------------------------------------ */
/*  Minimal real-shaped fixtures                                       */
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

/* ------------------------------------------------------------------ */
/*  posture()                                                          */
/* ------------------------------------------------------------------ */

test("posture: counts each provenance and computes grounded / guess split", () => {
  const p = posture([
    driver("a", "MEASURED"),
    driver("b", "SHOP"),
    driver("c", "USER"),
    driver("d", "DEFAULT"),
    driver("e", "DEFAULT"),
  ]);
  assert.equal(p.measured, 1);
  assert.equal(p.shop, 1);
  assert.equal(p.user, 1);
  assert.equal(p.default, 2);
  assert.equal(p.total, 5);
  assert.equal(p.grounded, 3);
  assert.equal(p.guess, 2);
  assert.equal(p.groundedPct, 3 / 5);
});

test("posture: empty / missing drivers → all zeros, no divide-by-zero", () => {
  for (const d of [[], null, undefined]) {
    const p = posture(d as CostDriver[] | null | undefined);
    assert.equal(p.total, 0);
    assert.equal(p.grounded, 0);
    assert.equal(p.groundedPct, 0);
  }
});

/* ------------------------------------------------------------------ */
/*  makeNowEstimate()                                                  */
/* ------------------------------------------------------------------ */

test("makeNowEstimate: returns the FIRST estimate for the make-now process", () => {
  const r = report({
    estimates: [
      estimate({ process: "sls", quantity: 50, unit_cost_usd: 99 }),
      estimate({ process: "cnc_3axis", quantity: 50, unit_cost_usd: 42.5 }),
      estimate({ process: "cnc_3axis", quantity: 5000, unit_cost_usd: 30 }),
    ],
    decision: decision({ make_now_process: "cnc_3axis" }),
  });
  const est = makeNowEstimate(r);
  assert.equal(est?.process, "cnc_3axis");
  assert.equal(est?.unit_cost_usd, 42.5); // first cnc row (qty 50), not the qty-5000 row
});

test("makeNowEstimate: null when there is no decision or no matching estimate", () => {
  assert.equal(makeNowEstimate(report({ decision: null })), null);
  assert.equal(
    makeNowEstimate(report({ decision: decision({ make_now_process: "forging" }) })),
    null
  );
  assert.equal(makeNowEstimate(null), null);
});

/* ------------------------------------------------------------------ */
/*  deriveCatalogMetrics()                                             */
/* ------------------------------------------------------------------ */

test("deriveCatalogMetrics: grounded SHOP route → calibrated, real price, not blocked", () => {
  const r = report({
    estimates: [
      estimate({
        drivers: [driver("machine_cost", "SHOP"), driver("material_cost", "MEASURED")],
      }),
    ],
  });
  const m = deriveCatalogMetrics(r);
  assert.equal(m.lifecycle, "calibrated");
  assert.equal(m.blocked, false);
  assert.equal(m.unitUsd, 42.5);
  assert.equal(m.withheldReason, null);
  assert.equal(m.posture.grounded, 2);
  assert.equal(m.routeProcess, "cnc_3axis");
  assert.equal(m.routeMaterial, "aluminum");
  assert.equal(m.refQty, 50);
});

test("deriveCatalogMetrics: a USER override wins the lifecycle (override queue)", () => {
  const r = report({
    estimates: [
      estimate({
        drivers: [driver("machine_cost", "SHOP"), driver("labor_cost", "USER")],
      }),
    ],
  });
  assert.equal(deriveCatalogMetrics(r).lifecycle, "overridden");
});

test("deriveCatalogMetrics: all-DEFAULT rates → assumption (DEFAULT-heavy)", () => {
  const r = report({
    estimates: [
      estimate({
        drivers: [driver("machine_cost", "DEFAULT"), driver("labor_cost", "DEFAULT")],
      }),
    ],
  });
  assert.equal(deriveCatalogMetrics(r).lifecycle, "assumption");
});

test("deriveCatalogMetrics: DFM-blocked route → blocked, price WITHHELD, reason surfaced", () => {
  const r = report({
    estimates: [
      estimate({
        dfm_ready: false,
        dfm_verdict: "fail",
        dfm_blockers: ["Wall 0.4mm below 0.8mm minimum", "Undercut on face 12"],
      }),
    ],
  });
  const m = deriveCatalogMetrics(r);
  assert.equal(m.blocked, true);
  assert.equal(m.lifecycle, "blocked");
  assert.equal(m.unitUsd, null); // withheld — no price on an unmakeable route
  assert.equal(m.withheldReason, "Wall 0.4mm below 0.8mm minimum");
  assert.equal(m.routeBlockerCount, 2);
});

test("deriveCatalogMetrics: a validated confidence band → validated (brass)", () => {
  const r = report({
    estimates: [
      estimate({
        confidence: {
          low_usd: 40,
          high_usd: 45,
          point_usd: 42.5,
          level: 0.8,
          method: "measured-residual",
          validated: true,
          n_samples: 12,
          half_width_pct: 6,
          basis: "residuals",
          label: "validated on 12 parts",
        },
      }),
    ],
  });
  assert.equal(deriveCatalogMetrics(r).lifecycle, "validated");
});

test("deriveCatalogMetrics: no decision / no estimate → unknown, no fabricated price", () => {
  const m = deriveCatalogMetrics(report({ decision: null, estimates: [] }));
  assert.equal(m.lifecycle, "unknown");
  assert.equal(m.unitUsd, null);
  assert.equal(m.routeBlockerCount, 0);
  assert.equal(m.posture.total, 0);
});

/* ------------------------------------------------------------------ */
/*  Saved views (the real client-side filters)                        */
/* ------------------------------------------------------------------ */

test("SAVED_VIEWS: the four are stable and all REAL (no presentational-only)", () => {
  assert.deepEqual(
    SAVED_VIEWS.map((v) => v.id),
    ["all", "override", "assumption", "blocked"]
  );
  for (const v of SAVED_VIEWS) {
    assert.equal(v.real, true, `${v.id} is a real filter`);
    assert.ok(v.description.length > 0);
  }
  assert.equal(savedViewById("override").id, "override");
  // @ts-expect-error — bad id falls back to the "all" view
  assert.equal(savedViewById("nope").id, "all");
});

test("matchesSavedView: each view filters on its real derived field", () => {
  const overridden = deriveCatalogMetrics(
    report({ estimates: [estimate({ drivers: [driver("m", "USER")] })] })
  );
  const assumption = deriveCatalogMetrics(
    report({ estimates: [estimate({ drivers: [driver("m", "DEFAULT")] })] })
  );
  const blocked = deriveCatalogMetrics(
    report({ estimates: [estimate({ dfm_ready: false, dfm_blockers: ["x"] })] })
  );

  // "all" matches everything
  for (const m of [overridden, assumption, blocked]) {
    assert.equal(matchesSavedView(m, "all"), true);
  }
  // override queue
  assert.equal(matchesSavedView(overridden, "override"), true);
  assert.equal(matchesSavedView(assumption, "override"), false);
  // DEFAULT-heavy
  assert.equal(matchesSavedView(assumption, "assumption"), true);
  assert.equal(matchesSavedView(overridden, "assumption"), false);
  // price withheld
  assert.equal(matchesSavedView(blocked, "blocked"), true);
  assert.equal(matchesSavedView(assumption, "blocked"), false);
});

/* ------------------------------------------------------------------ */
/*  Sort + format                                                      */
/* ------------------------------------------------------------------ */

test("lifecycleRank: blocked sorts worst-first, unknown sinks last", () => {
  assert.ok(lifecycleRank("blocked") > lifecycleRank("assumption"));
  assert.ok(lifecycleRank("assumption") > lifecycleRank("calibrated"));
  assert.ok(lifecycleRank("calibrated") > lifecycleRank("overridden"));
  assert.ok(lifecycleRank("overridden") > lifecycleRank("validated"));
  assert.ok(lifecycleRank("validated") > lifecycleRank("unknown"));
});

test("formatUnitUsd: two-decimal money, em-dash for missing", () => {
  assert.equal(formatUnitUsd(42.5), "$42.50");
  assert.equal(formatUnitUsd(1234.5), "$1,234.50");
  assert.equal(formatUnitUsd(null), "—");
  assert.equal(formatUnitUsd(undefined), "—");
  assert.equal(formatUnitUsd(Number.NaN), "—");
});
