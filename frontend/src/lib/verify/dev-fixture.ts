/**
 * Dev-only happy-path fixture for "Fixture Test 1".
 * Returned when the backend is unavailable in development so the UI can be
 * worked on without a running engine. Never reaches production — guarded by
 * NODE_ENV === "development" at the call site in verify-app.tsx.
 */
import type { VerifyResult } from "./run";
import { QTY_LADDER } from "./run";
import type {
  ValidationResult,
  CostReport,
  Issue,
  CostDriver,
} from "@/lib/api";

// ── geometry ────────────────────────────────────────────────────────────────

const WALL_ISSUES: Issue[] = [
  {
    code: "WALL_THIN_CNC",
    severity: "warning",
    message: "Wall section at pocket edge is 1.8 mm — above the 1.5 mm minimum but within 20% of the floor. Tool deflection risk at depth.",
    fix_suggestion: "Increase wall to ≥ 2.2 mm or add a radius fillet at the base.",
    affected_face_count: 14,
    affected_faces_sample: [204,205,206,207,208,209,210,211,212,213,214,215,216,217],
    scope: "localized",
    citation: { standard: "MachiningHandbook-27", clause: "§4.3.2", text: "Minimum wall-to-depth ratio for 3-axis end milling" },
  },
  {
    code: "POCKET_ASPECT",
    severity: "warning",
    message: "Central pocket depth-to-width ratio is 3.1:1 — exceeds the 3:1 guideline for standard end mills. Chip evacuation risk.",
    fix_suggestion: "Add a through-hole at the pocket floor or reduce depth by 2 mm.",
    affected_face_count: 32,
    affected_faces_sample: [418,419,420,421,422,423,424,425,426,427,428,429,430,431,432,433],
    scope: "localized",
    citation: { standard: "SME-MachiningHandbook", clause: "§6.1", text: "Pocket depth-to-width ratio for end milling" },
  },
];

export const FIXTURE_VALIDATION: ValidationResult = {
  filename: "Fixture_Test_1.stl",
  file_type: "stl",
  overall_verdict: "issues",
  best_process: "cnc_3axis",
  analysis_time_ms: 1_243,
  geometry: {
    vertices: 1284,
    faces: 847,
    volume_mm3: 27_840,
    surface_area_mm2: 13_920,
    bounding_box_mm: [65, 45, 20],
    is_watertight: true,
    is_manifold: true,
    center_of_mass: [32.5, 22.5, 10],
    units: "mm",
  },
  segments: [
    { id: 1, type: "planar",      face_count: 480, centroid: [32, 22, 10], confidence: 0.97 },
    { id: 2, type: "cylindrical", face_count: 144, centroid: [14, 22, 10], confidence: 0.91 },
    { id: 3, type: "pocket",      face_count: 223, centroid: [48, 22, 10], confidence: 0.88 },
  ],
  universal_issues: [],
  process_scores: [
    { process: "cnc_3axis",        score: 0.87, verdict: "issues", recommended_material: "6061-T6 Aluminum",  recommended_machine: null, estimated_cost_factor: 1.00, issues: WALL_ISSUES },
    { process: "cnc_5axis",        score: 0.91, verdict: "pass",   recommended_material: "6061-T6 Aluminum",  recommended_machine: null, estimated_cost_factor: 1.40, issues: [] },
    { process: "injection_molding",score: 0.78, verdict: "issues", recommended_material: "Glass-filled PA66", recommended_machine: null, estimated_cost_factor: 0.18, issues: [] },
    { process: "fdm",              score: 0.52, verdict: "issues", recommended_material: "PETG",              recommended_machine: null, estimated_cost_factor: 0.08, issues: [] },
  ],
  priority_fixes: [
    { code: "WALL_THIN_CNC", severity: "warning", message: WALL_ISSUES[0].message, process: "cnc_3axis", fix: WALL_ISSUES[0].fix_suggestion, measured_value: 1.8, required_value: 2.2 },
    { code: "POCKET_ASPECT",  severity: "warning", message: WALL_ISSUES[1].message, process: "cnc_3axis", fix: WALL_ISSUES[1].fix_suggestion, measured_value: 3.1, required_value: 3.0 },
  ],
};

// ── cost ─────────────────────────────────────────────────────────────────────

const LEAD_CNC  = { low_days: 5, high_days: 8,  mid_days: 6,  components: { setup: 0.5, machining: 2.5, finishing: 0.5, shipping: 2.5 }, capacity: { n_machines: 2, machine_hours_per_day: 16, provenance: "model" } };
const LEAD_IM   = { low_days: 18, high_days: 28, mid_days: 22, components: { tooling: 14, trial: 4, shipping: 4 },                        capacity: {} };

const CNC_DRIVERS: CostDriver[] = [
  { name: "machine_rate",   value: 95,   unit: "$/hr",     provenance: "DEFAULT", source: "US West regional benchmark", error_band_pct: 15 },
  { name: "cycle_time",     value: 18.4, unit: "min",      provenance: "DEFAULT", source: "volume model",               error_band_pct: 12 },
  { name: "material_price", value: 4.20, unit: "$/kg",     provenance: "DEFAULT", source: "LME Al + 3% mill premium",   error_band_pct: 8  },
  { name: "setup_time",     value: 1.95, unit: "hr",       provenance: "DEFAULT", source: "complexity estimate",         error_band_pct: 20 },
];

const IM_DRIVERS: CostDriver[] = [
  { name: "tooling_cost",   value: 14500, unit: "$",   provenance: "DEFAULT", source: "complexity band",       error_band_pct: 25 },
  { name: "cycle_time",     value: 42,    unit: "s",   provenance: "DEFAULT", source: "volume model",          error_band_pct: 10 },
  { name: "cavities",       value: 1,     unit: "",    provenance: "USER",    source: "declared",               error_band_pct: null },
  { name: "material_price", value: 3.80,  unit: "$/kg",provenance: "DEFAULT", source: "spot + glass fill",     error_band_pct: 10 },
];

function cnc(qty: number, unit: number) {
  return {
    process: "cnc_3axis", material: "6061-T6 Aluminum", quantity: qty,
    unit_cost_usd: unit, fixed_cost_usd: 185, variable_cost_usd: unit - 185 / qty,
    est_error_band_pct: 12, dfm_ready: false, dfm_verdict: "issues" as const,
    dfm_score: 0.87, dfm_blockers: [],
    line_items: { material: unit * 0.28, machining: unit * 0.48, setup: 185 / qty, finishing: unit * 0.14, overhead: unit * 0.10 },
    drivers: CNC_DRIVERS, lead_time: LEAD_CNC,
  };
}

function im(qty: number, unit: number) {
  return {
    process: "injection_molding", material: "Glass-filled PA66", quantity: qty,
    unit_cost_usd: unit, fixed_cost_usd: 14_500, variable_cost_usd: unit - 14500 / qty,
    est_error_band_pct: 18, dfm_ready: false, dfm_verdict: "issues" as const,
    dfm_score: 0.78, dfm_blockers: ["Draft angle < 0.5° on pocket sidewalls"],
    line_items: { material: unit * 0.12, cycle: unit * 0.31, tooling_amortization: 14500 / qty, finishing: unit * 0.08, overhead: unit * 0.09 },
    drivers: IM_DRIVERS, lead_time: LEAD_IM,
  };
}

export const FIXTURE_COST: CostReport = {
  filename: "Fixture_Test_1.stl",
  status: "OK",
  reason: null,
  geometry: { volume_cm3: 27.84, surface_area_cm2: 139.2, bbox_mm: [65, 45, 20], watertight: true, face_count: 847 },
  material_class: "aluminum",
  quantities: QTY_LADDER,
  estimates: [
    cnc(1,     382.00), cnc(100,  42.40), cnc(1000, 28.10),
    cnc(2000,  26.80),  cnc(5000, 25.60), cnc(10000, 24.90),
    im(1,    14_620.00), im(100, 148.50),  im(1000,  20.20),
    im(2000,   14.65),  im(5000,  11.20),  im(10000,  9.95),
  ],
  engine_feasibility: [
    { process: "cnc_3axis",         verdict: "issues", score: 0.87, costed: true  },
    { process: "cnc_5axis",         verdict: "pass",   score: 0.91, costed: false },
    { process: "injection_molding", verdict: "issues", score: 0.78, costed: true  },
    { process: "fdm",               verdict: "issues", score: 0.52, costed: false },
  ],
  routing: {
    archetype: "prismatic_bracket",
    recommended_process: "cnc_3axis",
    eval_family: "machined",
    material_hint: "6061-T6 Aluminum",
    confidence: 0.87,
    reasoning: "Prismatic envelope with one open pocket and two through-bores — standard 3-axis setup. Pocket aspect ratio is at the guideline limit; 5-axis resolves it without repositioning but adds ~40% unit cost at low volumes.",
    alternatives: ["cnc_5axis", "injection_molding"],
    drivers: { has_undercut: false, pocket_depth_ratio: 3.1, thin_wall: true, bore_count: 2 },
  },
  notes: [
    "Two DFM warnings on the 3-axis route — no hard blockers. Part is makeable as-is.",
    "Injection molding becomes cost-competitive above ~2 500 units if draft angle is corrected.",
  ],
  assumptions: [
    { name: "machine_rate",      value: 95,   unit: "$/hr",     provenance: "DEFAULT", source: "US West regional benchmark" },
    { name: "material_price_al", value: 4.20, unit: "$/kg",     provenance: "DEFAULT", source: "LME + mill premium"         },
    { name: "labor_rate",        value: 38,   unit: "$/hr",     provenance: "DEFAULT", source: "US skilled machinist avg"   },
    { name: "overhead_rate",     value: 0.18, unit: "fraction", provenance: "DEFAULT", source: "job shop benchmark"         },
  ],
  decision: {
    make_now_process: "cnc_3axis",
    make_now_material: "6061-T6 Aluminum",
    tooling_process: "injection_molding",
    tooling_dfm_ready: false,
    crossover_qty: 2500,
    recommendation: {
      cnc_3axis: { process: "cnc_3axis", material: "6061-T6 Aluminum", unit_cost_usd: 42.40, dfm_ready: false, dfm_verdict: "issues", lead_low_days: 5, lead_high_days: 8 },
    },
    if_redesigned: {
      cnc_3axis:         { process: "cnc_3axis",         material: "6061-T6 Aluminum",  unit_cost_usd: 38.90, caveat: "Widen pocket wall to 2.2 mm and reduce pocket depth by 2 mm" },
      injection_molding: { process: "injection_molding", material: "Glass-filled PA66", unit_cost_usd: 11.20, caveat: "Add 1° draft to pocket sidewalls" },
    },
    note: "Make by CNC 3-axis now. Two minor DFM warnings — no blockers. Switch to injection molding above ~2 500 units if draft is corrected.",
  },
  verification: null,
};

export function buildFixtureResult(file: File): VerifyResult {
  return {
    file,
    validation: FIXTURE_VALIDATION,
    validationError: null,
    cost: FIXTURE_COST,
    costGeometryInvalid: null,
    costError: null,
    machines: [],
    machinesError: null,
    verification: null,
    quantities: QTY_LADDER,
    env: { temp: false, sour: false, pressure: false },
    envDeclared: false,
    envCaptured: false,
    envError: null,
    meshHash: "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    partContext: null,
    partContextError: null,
  };
}
