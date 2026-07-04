/**
 * The Verify pipeline — the request lifecycle behind the walk. It calls the REAL
 * engine through the same-origin authed proxy and shapes the responses for the
 * verdict walk. NOTHING here fabricates a number: every figure the walk renders
 * comes from one of these responses or is withheld.
 *
 *   POST /validate         → routing + DFM (ValidationResult)          [real]
 *   POST /validate/cost    → the glass-box should-cost record (CostReport) [real]
 *   GET  /machine-inventory→ the org's declared floor (OwnedMachine[])  [real]
 *
 * The dev-branch engine does NOT surface a top-level `verification` block
 * (per-route machine fit / verdict lattice), so the walk renders the honest
 * makeability state ("no inventory declared" / feature pending), NEVER a fake
 * makeable/not-makeable verdict. When the engine wires that block, `verification`
 * on the result carries it through untouched.
 */
import { validateFile, type ValidationResult, type CostReport, type CostGeometry } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { listMachines, ownedProcessesFrom, type OwnedMachine } from "./machine-api";

/** The verdict lattice the engine emits WHEN a makeability block is present. */
export type MakeabilityLattice =
  | "makeable_in_house"
  | "makeable_with_secondary_op"
  | "makeable_not_on_owned"
  | "makeable_outsource_only"
  | "environment_excluded"
  | "not_makeable"
  | "unknown";

/** The (currently unsurfaced) top-level verification block. Rendered verbatim
 *  when present; its absence drives the honest unknown/feature state. */
export interface VerificationBlock {
  verdict: MakeabilityLattice;
  best_machine?: string | null;
  gap?: { gate: string; axis: string; need: unknown; have: unknown; human: string }[];
  env_exclusions?: { gate: string; axis: string; need: unknown; have: unknown; human: string }[];
  per_route?: Record<string, unknown>;
}

export interface VerifyInput {
  file: File;
  /** The declared service world. HONEST NOTE: the dev-branch /validate/cost has
   *  no env parameter, so this is captured for the record + the stage reaction
   *  only; environment-driven material survival (NACE MR0175 / HDT) is part of
   *  the makeability verification, which this engine build does not yet surface.
   *  It is NEVER used to fabricate a changed cost. */
  env: { temp: boolean; sour: boolean; pressure: boolean };
  materialClass: string;
}

/** Engine process ids the cost endpoint accepts in `owned_processes` — passing an
 *  id it doesn't know 400s the WHOLE cost call, so we only forward known ids
 *  (an unknown owned machine just falls back to fully-loaded costing, still honest). */
const KNOWN_ENGINE_PROCESSES = new Set([
  "fdm", "sla", "dlp", "sls", "mjf", "dmls", "slm", "ebm", "binder_jetting",
  "ded", "waam", "cnc_3axis", "cnc_5axis", "cnc_turning", "wire_edm",
  "injection_molding", "die_casting", "investment_casting", "sand_casting",
  "sheet_metal", "forging",
]);

export interface CostGeometryInvalid {
  message: string;
  geometry: CostGeometry | null;
}

export interface VerifyResult {
  file: File;
  validation: ValidationResult | null;
  validationError: string | null;
  cost: CostReport | null;
  /** set when /validate/cost refused broken geometry (the walk stops at G1). */
  costGeometryInvalid: CostGeometryInvalid | null;
  costError: string | null;
  machines: OwnedMachine[];
  machinesError: string | null;
  /** the makeability lattice block IF the engine surfaced one (else null →
   *  honest unknown/feature state). Read off both responses. */
  verification: VerificationBlock | null;
  quantities: number[];
}

/** Log-spaced quantity ladder the scrub interpolates over — the crossover story
 *  needs real computed points on both sides of the tooling break-even. */
export const QTY_LADDER = [1, 10, 50, 100, 250, 500, 1000, 2000, 5000, 10000];

/**
 * POST /validate/cost directly so we can pass `owned_processes` (marginal
 * costing for the org's floor) — the shared `costEstimate` helper does not carry
 * that field. Mirrors its GEOMETRY_INVALID (400) branch: a structured refusal is
 * the honest "walk stops at the failed gate", never a 500 or a faked pass.
 */
async function postCost(
  input: VerifyInput,
  ownedProcesses: string[]
): Promise<{ cost: CostReport | null; invalid: CostGeometryInvalid | null; error: string | null }> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("qty", QTY_LADDER.join(","));
  form.append("cavities", "1");
  form.append("complexity", "moderate");
  form.append("material_class", input.materialClass);
  if (ownedProcesses.length > 0) {
    form.append("owned_processes", ownedProcesses.join(","));
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/validate/cost`, { method: "POST", body: form });
  } catch (e) {
    return { cost: null, invalid: null, error: e instanceof Error ? e.message : "Network error" };
  }

  if (res.ok) {
    return { cost: (await res.json()) as CostReport, invalid: null, error: null };
  }

  const body: Record<string, unknown> = await res.json().catch(() => ({}));
  if (res.status === 400 && body.code === "GEOMETRY_INVALID") {
    return {
      cost: null,
      invalid: {
        message: (body.message as string) || "Geometry invalid — repair required.",
        geometry: (body.geometry as CostGeometry) ?? null,
      },
      error: null,
    };
  }
  const detail =
    (body.message as string) || (body.detail as string) || `Cost request failed (${res.status})`;
  return { cost: null, invalid: null, error: detail };
}

/** Run the full verification for one dropped part. Independent calls run in
 *  parallel; each failure is isolated so a partial result is still honest. */
export async function runVerification(input: VerifyInput): Promise<VerifyResult> {
  // The floor first (cheap) — its owned processes calibrate the cost to marginal.
  let machines: OwnedMachine[] = [];
  let machinesError: string | null = null;
  try {
    machines = (await listMachines()).machines;
  } catch (e) {
    machinesError = e instanceof Error ? e.message : "Could not load machine inventory";
  }
  const owned = ownedProcessesFrom(machines).filter((p) => KNOWN_ENGINE_PROCESSES.has(p));

  const [validationOut, costOut] = await Promise.all([
    validateFile(input.file).then(
      (v) => ({ v, err: null as string | null }),
      (e) => ({ v: null as ValidationResult | null, err: e instanceof Error ? e.message : "Validation failed" })
    ),
    postCost(input, owned),
  ]);

  // The verification block is not surfaced by the dev-branch engine. Read it off
  // either response if a future build adds it; otherwise null → honest state.
  const verification =
    readVerification(validationOut.v) ?? readVerification(costOut.cost) ?? null;

  return {
    file: input.file,
    validation: validationOut.v,
    validationError: validationOut.err,
    cost: costOut.cost,
    costGeometryInvalid: costOut.invalid,
    costError: costOut.error,
    machines,
    machinesError,
    verification,
    quantities: costOut.cost?.quantities ?? QTY_LADDER,
  };
}

function readVerification(obj: unknown): VerificationBlock | null {
  if (obj && typeof obj === "object" && "verification" in obj) {
    const v = (obj as { verification?: unknown }).verification;
    if (v && typeof v === "object" && "verdict" in v) return v as VerificationBlock;
  }
  return null;
}
