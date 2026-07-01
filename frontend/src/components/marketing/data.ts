/**
 * Marketing fixtures — the cost-truth engine's REAL output, captured from
 * `python -m src.costing.cli object.stl --qty 10,1000 --shop "Midwest Precision CNC"`
 * (and the Shenzhen profile for the A/B). The marketing site renders the SAME
 * report_to_dict the product renders — every claim on the page is a real number,
 * never a fabricated price and never a fabricated accuracy figure.
 *
 * VERIFIED against the live engine on 2026-06-29: object.stl + "Midwest Precision
 * CNC" yields make-now MJF $14.14/unit @ qty 10, crossover ≈1,962, routing
 * rotational→cnc_turning (DFM issues, not fail — internally consistent), and the
 * Midwest-vs-Shenzhen @ qty 1,000 compare row matches exactly. Re-capture with
 * the CLI command above when the engine changes.
 *
 * These mirror src/app/(app)/design-system/fixture.ts so the marketing surface
 * stays self-contained (no import across the route-group boundary), while the
 * values stay identical to what the platform showcase renders.
 */

import type {
  CostEstimate,
  CostRouting,
  CostFeasibility,
} from "@/lib/api";
import type { Breakeven } from "@/lib/breakeven";
import type { CompareRow } from "@/components/glass-box";

/** The canonical part the whole story is told on (the real captured file). */
export const PART = {
  name: "object.stl",
  process: "MJF (PP)",
  qty: 10,
  shop: "Midwest Precision CNC",
  shopSource: "Shop accounting export 2026-Q2 (loaded rates + negotiated resin lots)",
};

/** Make-now: MJF (PP) @ qty 10 — Midwest Precision CNC calibration. */
export const ESTIMATE: CostEstimate = {
  process: "mjf",
  material: "PP (Polypropylene)",
  quantity: 10,
  unit_cost_usd: 14.14,
  fixed_cost_usd: 0.0,
  variable_cost_usd: 10.43,
  est_error_band_pct: 40.0,
  confidence: {
    low_usd: 8.49,
    high_usd: 19.8,
    point_usd: 14.14,
    level: 0.8,
    method: "assumption-band",
    validated: false,
    n_samples: 0,
    half_width_pct: 40.0,
    basis:
      "±40% stated assumption band (cycle-time / tooling defaults) propagated around the point estimate — no ground truth yet",
    label: "assumption-based, not yet validated",
  },
  dfm_ready: true,
  dfm_verdict: "issues",
  dfm_score: 0.9,
  dfm_blockers: [],
  line_items: { amortized_fixed: 3.887, material: 0.0417, machine: 3.8213, labor: 6.3935 },
  drivers: [
    {
      name: "material_cost",
      value: 0.0417,
      unit: "$",
      provenance: "SHOP",
      source:
        "CAD volume 4.63 cm³ × PP (Polypropylene) density 0.90 g/cm³ = 0.0042 kg × $7/kg (shop polymer lot price) × (1+0.1 scrap) × region-material ×1",
      error_band_pct: 5.0,
    },
    {
      name: "parts_per_build",
      value: 223.0,
      unit: "parts",
      provenance: "DEFAULT",
      source:
        "nesting: packing 0.1 × env (380, 284, 380) ÷ part bbox (21.16, 21.43, 21.48)+5mm spacing = 223 parts/build",
      error_band_pct: null,
    },
    {
      name: "machine_cost",
      value: 3.8213,
      unit: "$",
      provenance: "SHOP",
      source:
        "0.0682 hr × $30/hr ÷ 0.8 utilization × region-labor ×1 × 1.15 overhead [build-job 380mm ÷ 25mm/hr = 15.2hr full build ÷ 223 parts/build = 0.068hr/part]",
      error_band_pct: 40.0,
    },
    {
      name: "labor_cost",
      value: 6.3935,
      unit: "$",
      provenance: "SHOP",
      source:
        "finish 0.08hr/part + bulk 0.5hr/build ÷ 223 = 0.082hr × $52/hr × region-labor ×1",
      error_band_pct: 20.0,
    },
    {
      name: "setup_cost",
      value: 3.887,
      unit: "$",
      provenance: "SHOP",
      source: "setup 0.5hr × $52/hr × ceil(10/223) = 1 setups ÷ 10 × region-labor ×1",
      error_band_pct: 20.0,
    },
  ],
  lead_time: {
    low_days: 5.6,
    high_days: 10.4,
    mid_days: 8.0,
    components: { queue: 3.0, tooling_lead: 0.0, production: 1.0, post_process: 1.0, ship: 3.0 },
    capacity: { n_machines: 6, machine_hours_per_day: 22.0, provenance: "DEFAULT" },
  },
};

/** make-vs-buy curves fitted from the engine's own reported unit costs. */
export const BREAKEVEN: Breakeven = {
  curves: [
    { process: "mjf", material: "PP", fixedAmort: 37.27, variablePerUnit: 10.41, dfmReady: true, leadLow: 5.6, leadHigh: 10.4, points: [{ qty: 10, unit: 14.14 }, { qty: 1000, unit: 10.45 }] },
    { process: "injection_molding", material: "PP", fixedAmort: 7800, variablePerUnit: 6.45, dfmReady: false, leadLow: 25, leadHigh: 40, points: [{ qty: 10, unit: 786.45 }, { qty: 1000, unit: 14.25 }] },
    { process: "cnc_turning", material: "6061-T6", fixedAmort: 35.35, variablePerUnit: 26.88, dfmReady: true, leadLow: 7, leadHigh: 12, points: [{ qty: 10, unit: 30.42 }, { qty: 1000, unit: 26.92 }] },
  ],
  qtyMin: 1,
  qtyMax: 10000,
  crossoverQty: 1962,
  makeNowProcess: "mjf",
  toolingProcess: "injection_molding",
};

export const ROUTING: CostRouting = {
  archetype: "rotational",
  recommended_process: "cnc_turning",
  eval_family: "subtractive",
  material_hint: "aluminum",
  confidence: 0.8,
  reasoning:
    "Axisymmetric cross-section (round, turnable): axis 21mm × Ø21mm → CNC turning / mill-turn. A round metal part is rarely powder-bed printed at production volume.",
  alternatives: ["cnc_5axis", "mjf"],
  drivers: {
    sheet_gauge_mm: 21.161,
    planar_aspect: 1.01,
    bend_count: 0,
    outline_perimeter_mm: 85.8,
    nominal_wall_mm: 6.17,
    rotational: true,
    sheet_like: false,
  },
};

export const FEASIBILITY: CostFeasibility[] = [
  { process: "mjf", verdict: "issues", score: 0.9, costed: true },
  { process: "cnc_turning", verdict: "issues", score: 0.9, costed: true },
  { process: "cnc_5axis", verdict: "issues", score: 0.8, costed: true },
  { process: "cnc_3axis", verdict: "fail", score: 0.0, costed: true },
  { process: "injection_molding", verdict: "fail", score: 0.0, costed: true },
  { process: "sheet_metal", verdict: "issues", score: 0.8, costed: false },
];

export const BLOCKERS: Record<string, string> = {
  cnc_3axis: "423 faces (59.6%) undercut for 3-axis access",
  injection_molding: "1 sidewall < 1.0° draft",
};

/** SHOP-vs-SHOP at qty 1000: Midwest Precision CNC vs Shenzhen Contract Mfg. */
export const COMPARE_ROWS: CompareRow[] = [
  { process: "mjf", a: { unitCost: 10.45, halfWidthPct: 40, dfmReady: true }, b: { unitCost: 2.68, halfWidthPct: 40, dfmReady: true } },
  { process: "sls", a: { unitCost: 10.64, halfWidthPct: 40, dfmReady: true }, b: { unitCost: 2.86, halfWidthPct: 40, dfmReady: true } },
  { process: "cnc_turning", a: { unitCost: 26.92, halfWidthPct: 50, dfmReady: true }, b: { unitCost: 5.96, halfWidthPct: 50, dfmReady: true } },
  { process: "cnc_5axis", a: { unitCost: 47.36, halfWidthPct: 50, dfmReady: true }, b: { unitCost: 10.95, halfWidthPct: 50, dfmReady: true } },
  { process: "injection_molding", a: { unitCost: 14.25, halfWidthPct: 60, dfmReady: false, redesign: true }, b: { unitCost: 4.65, halfWidthPct: 60, dfmReady: false, redesign: true } },
];

/** SHOP-tagged rates bound to Midwest, and the DEFAULT gaps still showing. */
export const SHOP_RATES = [
  { name: "labor", display: "$52/hr" },
  { name: "CNC-3ax", display: "$95/hr" },
  { name: "MJF", display: "$30/hr" },
  { name: "margin", display: "0.30" },
  { name: "utilization", display: "0.80" },
];
export const DEFAULT_RATES = [
  { name: "stock_allowance", display: "1.10×" },
  { name: "daily_machine_hours", display: "8 hr" },
  { name: "n_cavities", display: "1" },
];
