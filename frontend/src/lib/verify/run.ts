/**
 * The Verify pipeline — the request lifecycle behind the walk. It calls the REAL
 * engine through the same-origin authed proxy and shapes the responses for the
 * verdict walk. NOTHING here fabricates a number: every figure the walk renders
 * comes from one of these responses or is withheld.
 *
 *   POST /validate         → routing + DFM (ValidationResult)          [real]
 *   PUT  /part-context/{h} → persist the declared world (env round-trip)  [real]
 *   POST /validate/cost    → the glass-box should-cost record (CostReport) [real]
 *   GET  /machine-inventory→ the org's declared floor (OwnedMachine[])  [real]
 *
 * The cost route returns a top-level `verification` block (per-route machine fit /
 * verdict lattice / env exclusions) whenever the org declared machines and/or this
 * part's service environment. The environment door is REAL end-to-end: before the
 * cost call, the declared world is PERSISTED via the part-context API keyed by the
 * part's mesh_hash, so the block the server returns reflects it (env_exclusions
 * with cited standards, an environment-coherent decision). When neither inventory
 * nor an environment is declared, no block is emitted → the walk renders the honest
 * "not evaluated" state, NEVER a fabricated verdict.
 */
import { validateFile, type ValidationResult, type CostReport, type CostGeometry } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { listMachines, ownedProcessesFrom, type OwnedMachine } from "./machine-api";
import type { VerificationBlock } from "./verification";
import {
  computeMeshHash,
  declarePartContext,
  envToServiceEnvironment,
} from "./part-context";

// Re-export so existing importers keep resolving these off `run` unchanged.
export type { VerificationBlock, MakeabilityLattice } from "./verification";

export interface VerifyInput {
  file: File;
  /** The declared service world. REAL round-trip: it is persisted to the part's
   *  context (PUT /part-context/{mesh_hash}) before costing, so the engine's
   *  verification block reflects it (environment-driven material survival — NACE
   *  MR0175 / HDT). It is NEVER used client-side to fabricate a changed cost. */
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
   *  honest "not evaluated" state). Read off the cost response. */
  verification: VerificationBlock | null;
  quantities: number[];
  /** the environment round-trip outcome, so the door tells the exact truth:
   *  declared? captured to the part's record? or (on failure) why not. */
  env: { temp: boolean; sour: boolean; pressure: boolean };
  envDeclared: boolean;
  envCaptured: boolean;
  envError: string | null;
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

  // ── the environment round-trip (real) ──────────────────────────────────────
  // Persist the declared world to THIS part's context (keyed by the mesh_hash the
  // server itself computes) BEFORE costing, so the verification block the cost
  // route returns reflects it. Ambient (nothing toggled) sends an empty env, which
  // the backend treats as a no-op AND which coherently clears a prior declaration.
  // Best-effort: a failure (no org / role / network) is surfaced honestly, never
  // faked into a "captured" claim, and never blocks the walk.
  const serviceEnv = envToServiceEnvironment(input.env);
  const envDeclared = Object.keys(serviceEnv).length > 0;
  let envCaptured = false;
  let envError: string | null = null;
  const meshHash = await computeMeshHash(input.file).catch(() => null);
  if (meshHash) {
    const declared = await declarePartContext(meshHash, serviceEnv);
    envCaptured = declared.ok && envDeclared;
    if (envDeclared && !declared.ok) envError = declared.error;
  } else if (envDeclared) {
    envError = "could not compute this part's mesh hash in the browser";
  }

  // Validation and costing run after the env is on the record, so the cost route
  // reads the just-written context. (Validation carries no env; it can parallel.)
  const [validationOut, costOut] = await Promise.all([
    validateFile(input.file).then(
      (v) => ({ v, err: null as string | null }),
      (e) => ({ v: null as ValidationResult | null, err: e instanceof Error ? e.message : "Validation failed" })
    ),
    postCost(input, owned),
  ]);

  // The verification block rides the cost response when the org declared machines
  // and/or this part's environment; its ABSENCE (never a fabricated value) drives
  // the honest "not evaluated" state.
  const verification = readVerification(costOut.cost) ?? null;

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
    env: input.env,
    envDeclared,
    envCaptured,
    envError,
  };
}

function readVerification(obj: unknown): VerificationBlock | null {
  if (obj && typeof obj === "object" && "verification" in obj) {
    const v = (obj as { verification?: unknown }).verification;
    if (v && typeof v === "object" && "verdict" in v) return v as VerificationBlock;
  }
  return null;
}
