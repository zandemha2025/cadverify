/**
 * Unit tests for the Part standing page's pure derivations (part-standing.ts).
 *
 * Runs on the repo's zero-dependency runner: `node --test` with native TS type
 * stripping (see package.json "test"). No vitest/jest, no runtime relative
 * imports (type-only) so it strips cleanly.
 *
 * Proves the honesty contract of the standing:
 *   (a) a DFM-blocked route WITHHOLDS its price — deriveStanding never carries a
 *       make-price for a part the catalog withheld (usd stays null);
 *   (b) blockers are REAL findings (message / measured / required / faces /
 *       citation), sourced from the record's Issues, the messages, then the
 *       withheld reason — never fabricated, and [] when the part is not blocked;
 *   (c) `validated` defaults false (assumption band, HATCHED, n=0) until the
 *       engine says otherwise;
 *   (d) a part with no declared context has NO home (lineage), and history is the
 *       real same-file decisions, newest first.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isBlocked,
  standingKind,
  standingTag,
  deriveStanding,
  extractBlockers,
  lineageView,
  historyForFile,
} from "./part-standing.ts";
import type {
  CatalogRowApi,
  CostDecisionDetail,
  CostDecisionSummary,
  CostReport,
  Issue,
} from "@/lib/api";

function row(over: Partial<CatalogRowApi> = {}): CatalogRowApi {
  return {
    part_key: "meshA",
    filename: "part.stl",
    file_type: "stl",
    lifecycle_state: "Costed",
    recommended_route: { process: "cnc_turning", material: "4140", source: "costed" },
    unit_cost: { usd: 14.14, qty: 1, currency: "USD", withheld: false, withheld_reason: null, validated: false },
    findings: null,
    provenance_posture: null,
    route_blocker_count: 0,
    cost_decision: { id: "dec-1", url: "/api/v1/cost-decisions/dec-1" },
    analysis: null,
    updated_at: "2026-07-02T10:00:00Z",
    ...over,
  };
}

function detailWith(estimate: Partial<CostReport["estimates"][number]>): CostDecisionDetail {
  const report: CostReport = {
    filename: "part.stl",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 4.63, surface_area_cm2: 10, bbox_mm: [21.16, 21.16, 21.43], watertight: true, face_count: 423 },
    material_class: "metal",
    quantities: [1, 1000],
    estimates: [
      {
        process: "cnc_turning",
        material: "4140",
        quantity: 1000,
        unit_cost_usd: 14.14,
        fixed_cost_usd: 0,
        variable_cost_usd: 14.14,
        est_error_band_pct: 40,
        dfm_ready: true,
        dfm_verdict: "pass",
        dfm_score: 1,
        dfm_blockers: [],
        line_items: {},
        drivers: [],
        lead_time: { low_days: 5, high_days: 10, mid_days: 7, components: {}, capacity: {} },
        ...estimate,
      },
    ],
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: {
      make_now_process: "cnc_turning",
      make_now_material: "4140",
      tooling_process: null,
      tooling_dfm_ready: false,
      crossover_qty: 1962,
      recommendation: {},
      if_redesigned: {},
      note: "",
    },
  };
  return {
    id: "dec-1",
    filename: "part.stl",
    file_type: "stl",
    label: null,
    created_at: "2026-07-02T10:00:00Z",
    engine_version: "1.2.3",
    make_now_process: "cnc_turning",
    crossover_qty: 1962,
    quantities: [1, 1000],
    is_public: false,
    share_url: null,
    result: report,
  };
}

test("isBlocked: withheld price OR a positive route_blocker_count", () => {
  assert.equal(isBlocked(row()), false);
  assert.equal(isBlocked(row({ route_blocker_count: 2 })), true);
  assert.equal(
    isBlocked(row({ unit_cost: { usd: null, qty: 1, currency: "USD", withheld: true, withheld_reason: "draft angle", validated: false } })),
    true
  );
});

test("standingKind: costed / blocked / drafted / invalid from real fields", () => {
  assert.equal(standingKind(row()), "costed");
  assert.equal(standingKind(row({ lifecycle_state: "Drafted", cost_decision: null, unit_cost: null })), "drafted");
  assert.equal(
    standingKind(row({ unit_cost: { usd: null, qty: 1, currency: "USD", withheld: true, withheld_reason: "x", validated: false } })),
    "blocked"
  );
  // Costed artifact with no price and NOT blocked → honestly invalid, never a $0.
  assert.equal(standingKind(row({ unit_cost: null, route_blocker_count: 0 })), "invalid");
  assert.equal(standingTag(row()).tone, "neutral");
  assert.equal(standingTag(row()).label, "COSTED · RECORD");
  assert.equal(standingTag(row({ route_blocker_count: 1 })).tone, "fail");
});

test("deriveStanding: a withheld (blocked) price is NEVER carried as a number", () => {
  const blockedRow = row({
    route_blocker_count: 1,
    unit_cost: { usd: null, qty: 1, currency: "USD", withheld: true, withheld_reason: "sidewall < 1.0°", validated: false },
  });
  const s = deriveStanding(blockedRow, null);
  assert.equal(s.kind, "blocked");
  assert.equal(s.withheld, true);
  assert.equal(s.unitCostUsd, null);
});

test("deriveStanding: an environment-excluded detail estimate withholds fallback price", () => {
  const s = deriveStanding(
    row({ unit_cost: null, route_blocker_count: 0 }),
    detailWith({
      material: "304 Stainless",
      environment_excluded: true,
      environment_exclusion_reason:
        "304 Stainless excluded: sour service requires NACE MR0175 qualification",
    })
  );

  assert.equal(s.kind, "blocked");
  assert.equal(s.withheld, true);
  assert.equal(s.unitCostUsd, null);
  assert.equal(s.material, "4140");
});

test("deriveStanding: validated defaults false (assumption band, n=0) → hatched", () => {
  const s = deriveStanding(row(), null);
  assert.equal(s.validated, false);
  assert.equal(s.unitCostUsd, 14.14);
  assert.equal(s.crossoverQty, null); // no record loaded → withheld, not faked
  const withRecord = deriveStanding(row(), detailWith({}));
  assert.equal(withRecord.crossoverQty, 1962); // real record field
});

test("deriveStanding carries the persisted makeability lattice independently of DFM", () => {
  const detail = detailWith({ dfm_ready: true, dfm_verdict: "issues" });
  detail.result.verification = { verdict: "makeable_outsource_only" };
  const s = deriveStanding(row(), detail);
  assert.equal(s.makeabilityVerdict, "makeable_outsource_only");
});

test("extractBlockers: prefers the record's FULL blocker Issues (measured/faces/citation)", () => {
  const issue: Issue = {
    code: "IM_DRAFT_ANGLE",
    severity: "error",
    message: "Sidewall draft below minimum",
    fix_suggestion: "Add ≥ 1.0° draft",
    process: "injection_molding",
    affected_face_count: 1,
    measured_value: 0.6,
    required_value: 1.0,
    citation: { standard: "DFM-IM", clause: "§4.1" },
    scope: "localized",
  };
  const detail = detailWith({ dfm_ready: false, dfm_verdict: "fail", dfm_blockers: ["Sidewall draft below minimum"], dfm_blocker_details: [issue] });
  const blocked = row({ route_blocker_count: 1, unit_cost: { usd: null, qty: 1, currency: "USD", withheld: true, withheld_reason: "Sidewall draft below minimum", validated: false } });
  const b = extractBlockers(blocked, detail);
  assert.equal(b.length, 1);
  assert.equal(b[0].measured, 0.6);
  assert.equal(b[0].required, 1.0);
  assert.equal(b[0].affectedFaces, 1);
  assert.equal(b[0].citation, "DFM-IM · §4.1");
});

test("extractBlockers: falls back to the catalog withheld reason; [] when not blocked", () => {
  const blocked = row({ unit_cost: { usd: null, qty: 1, currency: "USD", withheld: true, withheld_reason: "Exceeds every owned envelope", validated: false } });
  const b = extractBlockers(blocked, null);
  assert.equal(b.length, 1);
  assert.equal(b[0].message, "Exceeds every owned envelope");
  assert.equal(extractBlockers(row(), null).length, 0);
});

test("lineageView: no declared context → NO home (never an invented program)", () => {
  const none = lineageView(null);
  assert.equal(none.hasHome, false);
  assert.equal(none.program, null);
  const homed = lineageView({ program: "Hydraulic actuator", parent_assembly: "Gearbox assy", annual_volume: 5000 });
  assert.equal(homed.hasHome, true);
  assert.equal(homed.program, "Hydraulic actuator");
  assert.equal(homed.annualVolume, 5000);
});

test("historyForFile: real same-file decisions, newest first", () => {
  const decisions: CostDecisionSummary[] = [
    { id: "a", filename: "part.stl", file_type: "stl", label: null, make_now_process: "cnc_turning", crossover_qty: 1900, quantities: [1], created_at: "2026-06-30T10:00:00Z", is_public: false, share_url: null },
    { id: "b", filename: "other.stl", file_type: "stl", label: null, make_now_process: "mjf", crossover_qty: null, quantities: [1], created_at: "2026-07-01T10:00:00Z", is_public: false, share_url: null },
    { id: "c", filename: "part.stl", file_type: "stl", label: null, make_now_process: "cnc_turning", crossover_qty: 1962, quantities: [1], created_at: "2026-07-02T10:00:00Z", is_public: false, share_url: null },
  ];
  const h = historyForFile(decisions, "part.stl");
  assert.deepEqual(h.map((d) => d.id), ["c", "a"]);
});
