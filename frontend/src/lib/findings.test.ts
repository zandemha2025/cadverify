/**
 * Unit tests for the pure derived-findings core (FE-2 Inspection column).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (Node >= 22.6). Type-only imports from `@/lib/*` are erased, so this
 * resolves without a path-alias loader, exactly like the other pure-lib suites.
 *
 * Proves:
 *   (a) provenance caveats surface ONLY DEFAULT drivers, scoped to the
 *       recommended route, deduped by name; MEASURED/SHOP/USER never leak;
 *   (b) confidence caveat fires iff a band exists AND validated === false —
 *       absent band or validated band emit nothing (no faked accuracy);
 *   (c) fragility fires iff the crossover sits within 4× of a costed qty, in
 *       either direction, and is null when crossover is null/far;
 *   (d) deriveFindings orders fragility → confidence → provenance and every
 *       finding carries a real engine-field `source`.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  provenanceCaveats,
  confidenceCaveat,
  fragilityFinding,
  deriveFindings,
  FRAGILITY_FACTOR,
} from "./findings.ts";
import type {
  CostReport,
  CostDriver,
  CostEstimate,
  CostConfidence,
  CostDecision,
  Provenance,
} from "@/lib/api";
import type { Breakeven } from "@/lib/breakeven";

/* ---- fixture helpers -------------------------------------------- */

function driver(name: string, provenance: Provenance, source = ""): CostDriver {
  return { name, value: 1, unit: "$", provenance, source, error_band_pct: null };
}

function confidence(overrides: Partial<CostConfidence> = {}): CostConfidence {
  return {
    low_usd: 8,
    high_usd: 16,
    point_usd: 12,
    level: 0.8,
    method: "assumption-band",
    validated: false,
    n_samples: 0,
    half_width_pct: 33,
    basis: "Assumption band, no held-out residuals yet.",
    label: "assumption-based, not yet validated",
    ...overrides,
  };
}

function estimate(overrides: Partial<CostEstimate> = {}): CostEstimate {
  return {
    process: "cnc_3axis",
    material: "aluminum_6061",
    quantity: 100,
    unit_cost_usd: 12,
    fixed_cost_usd: 200,
    variable_cost_usd: 10,
    est_error_band_pct: 30,
    dfm_ready: true,
    dfm_verdict: "pass",
    dfm_score: 90,
    dfm_blockers: [],
    line_items: {},
    drivers: [],
    lead_time: { low_days: 5, high_days: 10, mid_days: 7, components: {}, capacity: {} },
    ...overrides,
  };
}

function decision(overrides: Partial<CostDecision> = {}): CostDecision {
  return {
    make_now_process: "cnc_3axis",
    make_now_material: "aluminum_6061",
    tooling_process: "injection_molding",
    tooling_dfm_ready: true,
    crossover_qty: null,
    recommendation: {},
    if_redesigned: {},
    note: "",
    ...overrides,
  };
}

function report(overrides: Partial<CostReport> = {}): CostReport {
  return {
    filename: "part.stl",
    status: "OK",
    reason: null,
    geometry: {
      volume_cm3: 10,
      surface_area_cm2: 40,
      bbox_mm: [10, 10, 10],
      watertight: true,
      face_count: 500,
    },
    material_class: "aluminum",
    quantities: [100, 5000],
    estimates: [],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: decision(),
    ...overrides,
  };
}

function breakeven(crossoverQty: number | null): Breakeven {
  return {
    curves: [],
    qtyMin: 1,
    qtyMax: 100000,
    crossoverQty,
    makeNowProcess: "cnc_3axis",
    toolingProcess: "injection_molding",
  };
}

/* ---- provenance caveats ----------------------------------------- */

test("provenance caveats surface only DEFAULT drivers on the recommended route", () => {
  const r = report({
    decision: decision({ make_now_process: "cnc_3axis" }),
    estimates: [
      estimate({
        process: "cnc_3axis",
        drivers: [
          driver("machine_cost", "MEASURED", "× 0.4 hr @ $30/hr"),
          driver("labor_cost", "DEFAULT", "generic $28/hr"),
          driver("material_cost", "SHOP", "shop $7/kg"),
          driver("setup_cost", "DEFAULT", "generic setup"),
        ],
      }),
      // an off-route process whose DEFAULT drivers must NOT leak into the headline
      estimate({
        process: "injection_molding",
        drivers: [driver("tooling_cost", "DEFAULT", "generic tool")],
      }),
    ],
  });
  const caveats = provenanceCaveats(r);
  const names = caveats.map((c) => c.title);
  assert.equal(caveats.length, 2, "only the 2 DEFAULT drivers on cnc_3axis");
  assert.ok(names.some((t) => t.includes("Labor rate")));
  assert.ok(names.some((t) => t.includes("Setup cost")));
  assert.ok(!names.some((t) => t.includes("Tooling")), "off-route driver excluded");
  for (const c of caveats) {
    assert.equal(c.cls, "provenance-caveat");
    assert.equal(c.severity, "info");
    assert.match(c.source, /provenance = DEFAULT/);
  }
});

test("provenance caveats dedup a DEFAULT driver seen across costed quantities", () => {
  const r = report({
    quantities: [100, 5000],
    decision: decision({ make_now_process: "cnc_3axis" }),
    estimates: [
      estimate({ process: "cnc_3axis", quantity: 100, drivers: [driver("labor_cost", "DEFAULT")] }),
      estimate({ process: "cnc_3axis", quantity: 5000, drivers: [driver("labor_cost", "DEFAULT")] }),
    ],
  });
  assert.equal(provenanceCaveats(r).length, 1, "one caveat, not one per quantity");
});

test("provenance caveats are empty when every driver is grounded", () => {
  const r = report({
    estimates: [
      estimate({
        process: "cnc_3axis",
        drivers: [driver("machine_cost", "MEASURED"), driver("labor_cost", "SHOP")],
      }),
    ],
  });
  assert.deepEqual(provenanceCaveats(r), []);
});

/* ---- confidence caveat ------------------------------------------ */

test("confidence caveat fires when the recommended band is not validated", () => {
  const r = report({
    estimates: [estimate({ process: "cnc_3axis", confidence: confidence({ validated: false }) })],
  });
  const c = confidenceCaveat(r);
  assert.ok(c);
  assert.equal(c!.cls, "confidence-caveat");
  assert.equal(c!.severity, "info");
  assert.match(c!.source, /validated = false/);
  assert.match(c!.detail, /±33%/);
});

test("confidence caveat is null when the band is validated", () => {
  const r = report({
    estimates: [estimate({ process: "cnc_3axis", confidence: confidence({ validated: true }) })],
  });
  assert.equal(confidenceCaveat(r), null);
});

test("confidence caveat is null when no band is surfaced (backend build-gap, never faked)", () => {
  const r = report({ estimates: [estimate({ process: "cnc_3axis", confidence: undefined })] });
  assert.equal(confidenceCaveat(r), null);
});

test("confidence caveat reads the recommended process, preferring the larger costed qty", () => {
  const r = report({
    decision: decision({ make_now_process: "cnc_3axis" }),
    estimates: [
      estimate({ process: "cnc_3axis", quantity: 100, confidence: confidence({ half_width_pct: 50 }) }),
      estimate({ process: "cnc_3axis", quantity: 5000, confidence: confidence({ half_width_pct: 20 }) }),
      // a different process's band must not be picked
      estimate({ process: "sls", quantity: 9000, confidence: confidence({ half_width_pct: 5 }) }),
    ],
  });
  const c = confidenceCaveat(r);
  assert.ok(c);
  assert.match(c!.detail, /±20%/, "picks the qty-5000 cnc band, not the qty-100 or the sls one");
});

/* ---- fragility -------------------------------------------------- */

test("fragility fires when the crossover is within 4x of a costed quantity", () => {
  // crossover 5000 vs costed 5000 → ratio 1.0
  const r = report({ quantities: [100, 5000], estimates: [estimate({ quantity: 5000 })] });
  const f = fragilityFinding(r, breakeven(5000));
  assert.ok(f);
  assert.equal(f!.cls, "fragility");
  assert.equal(f!.severity, "warning");
  assert.match(f!.source, /crossover_qty/);
});

test("fragility respects the 4x boundary in both directions", () => {
  const r = report({ estimates: [estimate({ quantity: 1000 })] });
  // exactly 4x above (crossover 4000 vs 1000) → fragile (<=)
  assert.ok(fragilityFinding(r, breakeven(1000 * FRAGILITY_FACTOR)));
  // exactly 4x below (crossover 250 vs 1000) → fragile
  assert.ok(fragilityFinding(r, breakeven(1000 / FRAGILITY_FACTOR)));
  // just beyond 4x → robust, no finding
  assert.equal(fragilityFinding(r, breakeven(1000 * FRAGILITY_FACTOR + 1)), null);
  assert.equal(fragilityFinding(r, breakeven(200)), null);
});

test("fragility is null when there is no crossover (make wins at every volume)", () => {
  const r = report({ estimates: [estimate({ quantity: 5000 })] });
  assert.equal(fragilityFinding(r, breakeven(null)), null);
  assert.equal(fragilityFinding(r, null), null);
});

test("fragility uses the NEAREST costed quantity across a spread", () => {
  // crossover 4800: far from 100 (48x) but near 5000 (1.04x) → fragile via 5000
  const r = report({ quantities: [100, 5000], estimates: [estimate({ quantity: 100 }), estimate({ quantity: 5000 })] });
  const f = fragilityFinding(r, breakeven(4800));
  assert.ok(f);
  assert.match(f!.detail, /5,000-unit/);
});

/* ---- aggregate -------------------------------------------------- */

test("deriveFindings orders fragility → confidence → provenance", () => {
  const r = report({
    quantities: [5000],
    decision: decision({ make_now_process: "cnc_3axis", crossover_qty: 5000 }),
    estimates: [
      estimate({
        process: "cnc_3axis",
        quantity: 5000,
        confidence: confidence({ validated: false }),
        drivers: [driver("labor_cost", "DEFAULT")],
      }),
    ],
  });
  const all = deriveFindings(r, breakeven(5000));
  assert.deepEqual(
    all.map((f) => f.cls),
    ["fragility", "confidence-caveat", "provenance-caveat"]
  );
  // every finding names a real engine field
  for (const f of all) assert.ok(f.source.length > 0);
});

test("deriveFindings emits nothing when the report is fully grounded, validated, and robust", () => {
  const r = report({
    decision: decision({ make_now_process: "cnc_3axis", crossover_qty: null }),
    estimates: [
      estimate({
        process: "cnc_3axis",
        confidence: confidence({ validated: true }),
        drivers: [driver("machine_cost", "MEASURED"), driver("labor_cost", "SHOP")],
      }),
    ],
  });
  assert.deepEqual(deriveFindings(r, breakeven(null)), []);
});

test("keys are unique across a merged finding set", () => {
  const r = report({
    quantities: [5000],
    estimates: [
      estimate({
        process: "cnc_3axis",
        quantity: 5000,
        confidence: confidence({ validated: false }),
        drivers: [driver("labor_cost", "DEFAULT"), driver("setup_cost", "DEFAULT")],
      }),
    ],
    decision: decision({ crossover_qty: 5000 }),
  });
  const keys = deriveFindings(r, breakeven(5000)).map((f) => f.key);
  assert.equal(new Set(keys).size, keys.length, "no duplicate keys");
});
