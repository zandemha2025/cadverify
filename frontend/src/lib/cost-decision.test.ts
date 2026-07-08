/**
 * Unit tests for the pure cost-decision helpers (Phase 2 gap #3 frontend).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest.
 *
 * Proves:
 *   (a) the recommendation reader tolerates STRING quantity keys (the JSONB
 *       round-trip on persisted decisions) as well as int keys — a saved
 *       decision must read identically to a live one;
 *   (b) redesigned reader + quantities extraction are string-key safe;
 *   (c) the compare-diff formatter signs/labels deltas honestly and returns "—"
 *       (never a fabricated number) when a side has no estimate;
 *   (d) cheaperSide picks the lower unit cost / equal / n-a correctly;
 *   (e) the COST_PERSIST_UI flag defaults ON and honors explicit opt-out.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  recommendationForQty,
  redesignedForQty,
  recommendedQuantities,
  formatUnitCostDelta,
  cheaperSide,
  costPersistUiEnabled,
} from "./cost-decision.ts";
import type {
  CostDecision,
  CostRecommendation,
  CostRedesigned,
  CostCompareUnitRow,
} from "@/lib/api";

/* ---- fixtures --------------------------------------------------- */

function rec(process: string, unit: number): CostRecommendation {
  return {
    process,
    material: "aluminum-6061",
    unit_cost_usd: unit,
    dfm_ready: true,
    dfm_verdict: "pass",
    lead_low_days: 5,
    lead_high_days: 10,
  };
}

function redesign(process: string, unit: number): CostRedesigned {
  return {
    process,
    material: "aluminum-6061",
    unit_cost_usd: unit,
    caveat: "requires design-for-molding",
  };
}

/** A PERSISTED decision — recommendation/if_redesigned keys are STRINGS. */
function persistedDecision(): CostDecision {
  return {
    make_now_process: "cnc_milling",
    make_now_material: "aluminum-6061",
    tooling_process: "injection_molding",
    tooling_dfm_ready: false,
    crossover_qty: 1200,
    recommendation: {
      "50": rec("cnc_milling", 42.5),
      "5000": rec("injection_molding", 3.1),
    },
    if_redesigned: {
      "50": null,
      "5000": redesign("die_casting", 2.4),
    },
    note: "",
  };
}

/* ---- (a) string-key recommendation reader ----------------------- */

test("recommendationForQty reads STRING quantity keys (persisted JSONB)", () => {
  const d = persistedDecision();
  // caller passes a NUMBER (from the scrubber); keys are strings.
  assert.equal(recommendationForQty(d, 50)?.process, "cnc_milling");
  assert.equal(recommendationForQty(d, 5000)?.process, "injection_molding");
  assert.equal(recommendationForQty(d, 5000)?.unit_cost_usd, 3.1);
});

test("recommendationForQty reads INT keys too (live decision) and string args", () => {
  const d = persistedDecision();
  // string arg still resolves
  assert.equal(recommendationForQty(d, "50")?.process, "cnc_milling");
  // int-keyed map (a live report) with a numeric arg
  const liveKeyed = {
    recommendation: { 50: rec("mjf", 9.9) } as unknown as CostDecision["recommendation"],
  };
  assert.equal(recommendationForQty(liveKeyed, 50)?.process, "mjf");
});

test("recommendationForQty returns null for an unknown qty or null decision", () => {
  const d = persistedDecision();
  assert.equal(recommendationForQty(d, 999), null);
  assert.equal(recommendationForQty(null, 50), null);
  assert.equal(recommendationForQty(undefined, 50), null);
});

/* ---- (b) redesigned reader + quantities ------------------------- */

test("redesignedForQty is string-key safe and preserves explicit null", () => {
  const d = persistedDecision();
  assert.equal(redesignedForQty(d, 50), null, "no redesign at qty 50");
  assert.equal(redesignedForQty(d, 5000)?.process, "die_casting");
});

test("recommendedQuantities returns sorted numbers from string keys", () => {
  const d = persistedDecision();
  assert.deepEqual(recommendedQuantities(d), [50, 5000]);
  assert.deepEqual(recommendedQuantities(null), []);
});

/* ---- (c) compare-diff formatter --------------------------------- */

test("formatUnitCostDelta signs and labels deltas (B relative to A)", () => {
  const up = formatUnitCostDelta(3.2, 12.5);
  assert.equal(up.direction, "pricier");
  assert.equal(up.text, "+$3.20 (+12.5%)");

  const down = formatUnitCostDelta(-1, -4);
  assert.equal(down.direction, "cheaper");
  assert.equal(down.text, "-$1.00 (-4%)");

  const flat = formatUnitCostDelta(0, 0);
  assert.equal(flat.direction, "flat");
  assert.equal(flat.text, "no change");
});

test("formatUnitCostDelta returns '—' (never a fake number) when a side is missing", () => {
  const na = formatUnitCostDelta(null, null);
  assert.equal(na.direction, "na");
  assert.equal(na.text, "—");
});

test("formatUnitCostDelta omits the pct clause when delta_pct is null", () => {
  const r = formatUnitCostDelta(5, null);
  assert.equal(r.text, "+$5.00");
  assert.equal(r.direction, "pricier");
});

/* ---- (d) cheaperSide -------------------------------------------- */

test("cheaperSide picks the lower unit cost / equal / n-a", () => {
  const row = (ua: number | null, ub: number | null): CostCompareUnitRow => ({
    quantity: 100,
    a: ua == null ? null : { process: "p", unit_cost_usd: ua },
    b: ub == null ? null : { process: "p", unit_cost_usd: ub },
    delta_usd: ua != null && ub != null ? ub - ua : null,
    delta_pct: null,
  });
  assert.equal(cheaperSide(row(10, 12)), "a");
  assert.equal(cheaperSide(row(12, 10)), "b");
  assert.equal(cheaperSide(row(10, 10)), "equal");
  assert.equal(cheaperSide(row(10, null)), "na");
  assert.equal(cheaperSide(row(null, 10)), "na");
});

/* ---- (e) feature flag default ON -------------------------------- */

test("costPersistUiEnabled defaults ON and honors explicit opt-out", () => {
  const prev = process.env.NEXT_PUBLIC_COST_PERSIST_UI;
  try {
    delete process.env.NEXT_PUBLIC_COST_PERSIST_UI;
    assert.equal(costPersistUiEnabled(), true, "unset => ON");

    process.env.NEXT_PUBLIC_COST_PERSIST_UI = "0";
    assert.equal(costPersistUiEnabled(), false, "'0' => off");

    process.env.NEXT_PUBLIC_COST_PERSIST_UI = "false";
    assert.equal(costPersistUiEnabled(), false, "'false' => off");

    process.env.NEXT_PUBLIC_COST_PERSIST_UI = "1";
    assert.equal(costPersistUiEnabled(), true, "'1' => ON");
  } finally {
    if (prev === undefined) delete process.env.NEXT_PUBLIC_COST_PERSIST_UI;
    else process.env.NEXT_PUBLIC_COST_PERSIST_UI = prev;
  }
});
