/**
 * Test fixtures for the find-and-fix model, trimmed from a real engine run on
 * backend/tests/trap-corpus/trap-wall-0.5mm-shell.stl (the 0.5 mm hollow cube):
 * the same codes, messages, measured and required values, citations and prices.
 */
import type { CostReport, ValidationResult } from "@/lib/api";

type AnyObj = Record<string, unknown>;

export function issue(code: string, severity: string, message: string, extra: AnyObj = {}): AnyObj {
  return { code, severity, message, fix_suggestion: null, ...extra };
}

const THIN = (proc: string, need: number, citation?: AnyObj) =>
  issue("THIN_WALL", "error", `24 faces (100.0%) below ${need}mm min wall for ${proc}. Thinnest: 0.5mm.`, {
    process: proc,
    affected_face_count: 24,
    affected_faces_sample: Array.from({ length: 24 }, (_, i) => i),
    region_center: [10, 10, 10],
    measured_value: 0.49999999999999645,
    required_value: need,
    measurement_unit: "mm",
    fix_suggestion: `Increase wall thickness to >= ${need}mm. Thin walls vibrate; ${need}mm min metals.`,
    ...(citation ? { citation } : {}),
    scope: "localized",
  });

const TRAP = (proc: string, need: number, citation?: AnyObj) =>
  issue("TRAPPED_VOLUME", "error", `Internal cavity (6859mm³) traps material in ${proc}. Needs >= ${need}mm drain holes.`, {
    process: proc,
    region_center: [10, 10, 10],
    fix_suggestion: `Add drain holes >= ${need}mm diameter.`,
    ...(citation ? { citation } : {}),
    scope: "localized",
  });

const OVER = (proc: string) =>
  issue("OVERHANG", "warning", `2 faces (8.3%) exceed 19.0° overhang threshold for ${proc}. Supports required.`, {
    process: proc,
    affected_face_count: 2,
    affected_faces_sample: [3, 4],
    region_center: [10, 10, 19.5],
    scope: "localized",
  });

const PREC = (proc: string) => issue("WALL_THICKNESS_PRECISION", "warning", "Wall checks have stable measurements for 24 of 24 faces.", { process: proc, scope: "whole_part" });

const DRAFT = (proc: string, need: number, extra: AnyObj = {}) =>
  issue("INSUFFICIENT_DRAFT", "error", `16 sidewall faces (100.0% of sidewall area) below ${need}° draft for ${proc}.`, {
    process: proc,
    affected_face_count: 16,
    affected_faces_sample: Array.from({ length: 16 }, (_, i) => i + 4),
    required_value: need,
    measurement_unit: "deg",
    fix_suggestion: `Add >= ${need}° draft to all walls in pull direction. Protolabs: 1° min external, 2° internal.`,
    citation: { standard: "Protolabs", text: "1° min external, 2° internal." },
    scope: "localized",
    ...extra,
  });

export function shellValidation(): ValidationResult {
  const ps = (process: string, verdict: string, issues: AnyObj[]) => ({ process, verdict, score: verdict === "fail" ? 0 : 0.9, issues, recommended_material: null, recommended_machine: null, estimated_cost_factor: 1 });
  return {
    filename: "trap-wall-0.5mm-shell.stl",
    file_type: "stl",
    overall_verdict: "issues",
    best_process: "wire_edm",
    analysis_time_ms: 900,
    geometry: { vertices: 16, faces: 24, volume_mm3: 1141, surface_area_mm2: 4400, bounding_box_mm: [20, 20, 20], is_watertight: true, is_manifold: true, center_of_mass: [10, 10, 10], units: "mm" },
    segments: [],
    universal_issues: [issue("MULTIPLE_BODIES", "warning", "Mesh contains 2 disconnected bodies.", { fix_suggestion: "Combine into a single solid body using boolean union, or separate into individual files.", scope: "whole_part" })],
    process_scores: [
      ps("wire_edm", "issues", [issue("PRISMATIC_PROFILE_UNVERIFIED", "warning", "A constant straight extrusion could not be verified.", { process: "wire_edm" }), issue("CONDUCTIVITY_REQUIRED", "info", "Wire EDM requires electrically conductive material.", { process: "wire_edm" })]),
      ps("sla", "fail", [PREC("sla"), OVER("sla"), TRAP("sla", 3.5, { standard: "Formlabs", text: "3.5mm drain holes for hollowed parts." }), issue("CUPPING_RISK", "warning", "Large downward-facing area (761mm², 17%) — resin cupping / suction risk during peel.", { process: "sla", fix_suggestion: "Add drain holes, tilt part 10-15°, or orient concave side up.", scope: "whole_part" })]),
      ps("dlp", "fail", [PREC("dlp"), OVER("dlp"), TRAP("dlp", 3.5)]),
      ps("mjf", "fail", [PREC("mjf"), TRAP("mjf", 5.0, { standard: "HP MJF DG", clause: "§4.2", text: "5mm escape holes." })]),
      ps("fdm", "fail", [PREC("fdm"), THIN("fdm", 0.8, { clause: "§3", text: "2x nozzle diameter (0.4mm). Stratasys DFM." }), OVER("fdm"), TRAP("fdm", 3.0)]),
      ps("sls", "fail", [THIN("sls", 0.7, { standard: "EOS PA12", text: "0.7mm min wall." }), TRAP("sls", 3.5)]),
      ps("cnc_3axis", "fail", [
        issue("SETUP_ACCESS_UNVERIFIED", "warning", "A setup without re-entrant surfaces could not be verified.", { process: "cnc_3axis" }),
        issue("SHARP_INTERNAL_CORNERS", "warning", "12 sharp concave edges — tool radius 0.5mm cannot reach. Applies to cnc_3axis.", { process: "cnc_3axis", required_value: 0.5, measurement_unit: "mm", citation: { standard: "Sandvik", text: "smallest end mill 1mm Ø → 0.5mm radius." }, scope: "whole_part" }),
        THIN("cnc_3axis", 0.8, { text: "Thin walls vibrate; 0.8mm min metals." }),
      ]),
      ps("cnc_5axis", "fail", [issue("SHARP_INTERNAL_CORNERS", "warning", "12 sharp concave edges — tool radius 0.5mm cannot reach.", { process: "cnc_5axis", required_value: 0.5, measurement_unit: "mm", scope: "whole_part" }), THIN("cnc_5axis", 0.8)]),
      ps("cnc_turning", "fail", [issue("NOT_ROTATIONALLY_SYMMETRIC", "error", "Part lacks positive rotational geometry (eigenvalue ratios: 1.00, 1.00). Required for cnc_turning.", { process: "cnc_turning", fix_suggestion: "CNC turning requires axially symmetric geometry. Use mill-turn or 3/5-axis CNC.", scope: "whole_part" }), THIN("cnc_turning", 1.0)]),
      ps("injection_molding", "fail", [DRAFT("injection_molding", 1.0), issue("UNDERCUT_MOLDING", "warning", "4 faces form undercuts requiring side actions in injection_molding tooling.", { process: "injection_molding", affected_face_count: 4, affected_faces_sample: [5, 6, 7, 8] })]),
      ps("die_casting", "fail", [
        DRAFT("die_casting", 1.0, { citation: { standard: "NADCA", clause: "§3", text: "1° min external, 2° internal." } }),
        issue("THIN_WALL_MOLDING", "error", "Min wall 0.5mm < 0.8mm for die_casting.", { process: "die_casting", measured_value: 0.5, required_value: 0.8, measurement_unit: "mm", scope: "whole_part" }),
        issue("MISSING_FILLETS", "warning", "12 sharp concave mesh edges need >= 1.0mm fillets for die_casting.", { process: "die_casting", required_value: 1.0, measurement_unit: "mm" }),
        issue("UNDERCUT_MOLDING", "warning", "4 faces form undercuts requiring side actions in die_casting tooling.", { process: "die_casting", affected_face_count: 4, affected_faces_sample: [5, 6, 7, 8] }),
      ]),
      ps("sand_casting", "fail", [DRAFT("sand_casting", 3.0, { citation: { standard: "AFS", text: "3° min — rougher mold surface." } })]),
    ],
    priority_fixes: [
      { code: "THIN_WALL", severity: "error", message: "24 faces below 0.8mm min wall for fdm.", process: "fdm", fix: "Increase wall thickness to >= 0.8mm.\n\nAlternative: Consider SLA (min 0.3mm) or DMLS (min 0.4mm) for thinner walls.", measured_value: 0.5, required_value: 0.8 },
    ],
  } as unknown as ValidationResult;
}

function est(process: string, quantity: number, unit: number, material = "PLA", extra: AnyObj = {}) {
  return { process, material, quantity, unit_cost_usd: unit, fixed_cost_usd: 0, variable_cost_usd: unit, est_error_band_pct: 50, dfm_ready: false, dfm_verdict: "fail", dfm_score: 0, dfm_blockers: [], line_items: {}, drivers: [], lead_time: { low_days: 5, high_days: 9, mid_days: 7, components: {}, capacity: {} }, ...extra };
}

export function shellCost(): CostReport {
  const rows: [string, number, number, string][] = [
    ["mjf", 7.5, 4.21, "PP (Polypropylene)"],
    ["sls", 7.5, 4.3, "PA12 (Nylon 12)"],
    ["dlp", 8.28, 7.42, "Standard Resin"],
    ["fdm", 8.67, 7.96, "PLA"],
    ["sla", 9.09, 8.59, "Standard Resin"],
    ["cnc_3axis", 36.18, 12.8, "Delrin (POM)"],
    ["cnc_5axis", 46.78, 15.63, "Delrin (POM)"],
    ["injection_molding", 601.82, 2.42, "PP (Molded)"],
  ];
  return {
    filename: "trap-wall-0.5mm-shell.stl",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 1.14, surface_area_cm2: 44, bbox_mm: [20, 20, 20], watertight: true, face_count: 24 },
    material_class: "polymer",
    quantities: [1, 10, 100, 1000, 10000],
    estimates: rows.flatMap(([p, a, b, m]) => [est(p, 10, a, m), est(p, 10000, b, m)]),
    engine_feasibility: [],
    notes: [],
    assumptions: [],
    decision: {
      make_now_process: "fdm",
      make_now_material: "PLA",
      tooling_process: "injection_molding",
      tooling_dfm_ready: false,
      crossover_qty: 2506,
      recommendation: {},
      if_redesigned: { "10": null, "10000": { process: "injection_molding", material: "PP (Molded)", unit_cost_usd: 2.42, caveat: "add draft, tooling-dominated" } },
      note: "",
    },
  } as unknown as CostReport;
}

/** A Design Studio enclosure checked through cost only (no stored analysis), like a saved revision. */
export function enclosureCostOnly(): CostReport {
  const draft = { code: "INSUFFICIENT_DRAFT", severity: "error", message: "132042 sidewall faces (100.0% of sidewall area) below 1.0° draft for injection_molding.", fix_suggestion: "Add >= 1.0° draft to all walls in pull direction.", required_value: 1.0, measurement_unit: "deg", affected_face_count: 132042, affected_faces_sample: [1, 2, 3] };
  const ok = (p: string, q: number, u: number) => est(p, q, u, "PLA", { dfm_ready: true, dfm_verdict: "issues" });
  return {
    filename: "open-enclosure-120x80x40-r1.step",
    status: "OK",
    reason: null,
    geometry: { volume_cm3: 15.16, surface_area_cm2: 400, bbox_mm: [120, 80, 40], watertight: true, face_count: 212526 },
    material_class: "polymer",
    quantities: [10, 1000],
    estimates: [
      ok("fdm", 10, 24.03),
      ok("fdm", 1000, 23.45),
      est("injection_molding", 10, 1501.85, "PP (Molded)", { dfm_blocker_details: [draft], dfm_blockers: [draft.message] }),
      est("injection_molding", 1000, 16.85, "PP (Molded)", { dfm_blocker_details: [draft], dfm_blockers: [draft.message] }),
    ],
    engine_feasibility: [{ process: "fdm", verdict: "issues", score: 0.9, costed: true }, { process: "injection_molding", verdict: "fail", score: 0.1, costed: true, blockers: [draft.message] }],
    notes: [],
    assumptions: [],
    decision: {
      make_now_process: "fdm",
      make_now_material: "PLA",
      tooling_process: "injection_molding",
      tooling_dfm_ready: false,
      crossover_qty: 695,
      recommendation: {},
      if_redesigned: { "10": null, "1000": { process: "injection_molding", material: "PP (Molded)", unit_cost_usd: 16.85, caveat: "add draft, tooling-dominated" } },
      note: "",
    },
  } as unknown as CostReport;
}
