/**
 * Real engine output (object.stl, qty 10/1000, shop "Midwest Precision CNC" and
 * "Shenzhen Contract Mfg"), captured from `python -m src.costing.cli … --json`.
 * The design-system showcase renders the glass-box components against THIS — the
 * cost-truth engine's real report_to_dict, not the old toy cost_per_cm3 model.
 */

import type {
  CostEstimate,
  CostAssumption,
  CostRouting,
  CostFeasibility,
} from "@/lib/api";
import type { CompareRow } from "@/components/glass-box";

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

export const ASSUMPTIONS: CostAssumption[] = [
  { name: "labor_rate", value: 52.0, unit: "$/hr", provenance: "SHOP", source: "loaded shop-floor labor [shop: Midwest Precision CNC]" },
  { name: "margin", value: 0.3, unit: "frac", provenance: "SHOP", source: "target margin (price vs should-cost) [shop: Midwest Precision CNC]" },
  { name: "overhead", value: 0.15, unit: "frac", provenance: "SHOP", source: "indirect burden on conversion cost [shop: Midwest Precision CNC]" },
  { name: "utilization", value: 0.8, unit: "frac", provenance: "SHOP", source: "machine utilization (idle-recovery on machine cost) [shop: Midwest Precision CNC]" },
  { name: "stock_allowance", value: 1.1, unit: "×", provenance: "DEFAULT", source: "CNC billet oversize on hull" },
  { name: "daily_machine_hours", value: 8.0, unit: "hr/day", provenance: "DEFAULT", source: "for lead-time production days" },
  { name: "n_cavities", value: 1.0, unit: "cav", provenance: "DEFAULT", source: "formative tooling cavities = 1 (DEFAULT single-cavity should-cost)" },
];

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
