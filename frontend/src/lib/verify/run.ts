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
import { apiProblemDetail, apiRecoveryMessage } from "@/lib/api-recovery";
import { listMachines, ownedProcessesFrom, type OwnedMachine } from "./machine-api";
import { readVerification, type VerificationBlock } from "./verification";
import {
  computeMeshHash,
  declarePartContext,
  envToServiceEnvironment,
} from "./part-context";
import { fetchPartContext, type PartContext } from "./part-context-read";
import { readJsonOrNull, validationAllowsCost } from "./run-gates";

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

export interface VerifyProgress {
  /** The first useful engine result. Costing intentionally remains sequential so
   *  the two geometry-heavy requests never double peak worker memory. */
  validation: ValidationResult | null;
  validationError: string | null;
}

export interface RunVerificationOptions {
  onValidation?: (progress: VerifyProgress) => void;
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
  /** SHA-256 of the uploaded bytes, matching the backend's mesh_hash. */
  meshHash: string | null;
  /** Existing/persisted USER context for this part, if the org declared one. */
  partContext: PartContext | null;
  partContextError: string | null;
}

/** Log-spaced quantity ladder the scrub interpolates over — the crossover story
 *  needs real computed points on both sides of the tooling break-even.
 *  Capped at 6 points to honor the backend contract (`_MAX_QTYS = 6` in
 *  routes.py); these bracket the typical crossover (~1–2k) on both sides. */
export const QTY_LADDER = [1, 100, 1000, 2000, 5000, 10000];

/** Keep the six-point engine contract while ensuring a declared annual volume
 *  becomes an exact computed point on the next verification. The closest
 *  interior ladder point is replaced because the declared point carries the
 *  same local curve information; the low/high anchors remain intact. */
export function quantityLadderForAnnual(
  annualVolume: number | null | undefined
): number[] {
  if (
    annualVolume == null ||
    !Number.isInteger(annualVolume) ||
    annualVolume <= 0 ||
    QTY_LADDER.includes(annualVolume)
  ) {
    return QTY_LADDER;
  }
  const replaceable = QTY_LADDER.slice(1, -1);
  const nearest = replaceable.reduce((best, quantity) =>
    Math.abs(Math.log(quantity) - Math.log(annualVolume)) <
    Math.abs(Math.log(best) - Math.log(annualVolume))
      ? quantity
      : best
  );
  return [...QTY_LADDER.filter((quantity) => quantity !== nearest), annualVolume].sort(
    (a, b) => a - b
  );
}

/**
 * POST /validate/cost directly so we can pass `owned_processes` (marginal
 * costing for the org's floor) — the shared `costEstimate` helper does not carry
 * that field. Mirrors its GEOMETRY_INVALID (400) branch: a structured refusal is
 * the honest "walk stops at the failed gate", never a 500 or a faked pass.
 */
async function postCost(
  input: VerifyInput,
  ownedProcesses: string[],
  quantities: number[]
): Promise<{ cost: CostReport | null; invalid: CostGeometryInvalid | null; error: string | null }> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("qty", quantities.join(","));
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
    const cost = await readJsonOrNull<CostReport>(res);
    return cost
      ? { cost, invalid: null, error: null }
      : {
          cost: null,
          invalid: null,
          error:
            "The should-cost service returned an unreadable response. Retry cost only; routing and DFM are unchanged.",
        };
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
    apiProblemDetail(body) ||
    apiRecoveryMessage({
      status: res.status,
      payload: body,
      resource: "verification",
      retryAfter: res.headers.get("retry-after"),
    });
  return { cost: null, invalid: null, error: detail };
}

export interface CostRetryResult {
  cost: CostReport | null;
  costGeometryInvalid: CostGeometryInvalid | null;
  costError: string | null;
  verification: VerificationBlock | null;
  quantities: number[];
}

/** Retry only the failed costing subsystem. Successful routing + DFM stays on
 *  screen and is not recomputed or replaced while a transient cost outage clears. */
export async function retryVerificationCost(
  input: VerifyInput,
  machines: OwnedMachine[],
  annualVolume?: number | null
): Promise<CostRetryResult> {
  const owned = ownedProcessesFrom(machines).filter((p) => KNOWN_ENGINE_PROCESSES.has(p));
  const quantities = quantityLadderForAnnual(annualVolume);
  const costOut = await postCost(input, owned, quantities);
  return {
    cost: costOut.cost,
    costGeometryInvalid: costOut.invalid,
    costError: costOut.error,
    verification: readVerification(costOut.cost) ?? null,
    quantities: costOut.cost?.quantities ?? quantities,
  };
}

/** Run the full verification for one dropped part. Lightweight independent work
 *  runs in parallel. Costing starts only after routing + DFM returns, so a service
 *  interruption cannot be misrepresented as a manufacturing verdict. */
export async function runVerification(
  input: VerifyInput,
  options: RunVerificationOptions = {}
): Promise<VerifyResult> {
  // Start the first useful answer immediately. Floor/context work is lightweight
  // and runs beside it; the second geometry-heavy call (cost) still waits until
  // validation has released its worker memory.
  const validationPromise = validateFile(input.file).then(
    (v) => ({ v, err: null as string | null }),
    (e) => ({
      v: null as ValidationResult | null,
      err: e instanceof Error ? e.message : "Validation failed",
    })
  );

  const machinesPromise = listMachines().then(
    (payload) => ({ machines: payload.machines, error: null as string | null }),
    (e) => ({
      machines: [] as OwnedMachine[],
      error: e instanceof Error ? e.message : "Could not load machine inventory",
    })
  );

  // ── the environment round-trip (real) ──────────────────────────────────────
  const serviceEnv = envToServiceEnvironment(input.env);
  const envDeclared = Object.keys(serviceEnv).length > 0;
  const contextPromise = (async () => {
    let envCaptured = false;
    let envError: string | null = null;
    let partContext: PartContext | null = null;
    let partContextError: string | null = null;
    const meshHash = await computeMeshHash(input.file).catch(() => null);
    const validationGate = await validationPromise;
    if (!validationAllowsCost(validationGate.v)) {
      return {
        meshHash,
        envCaptured,
        envError,
        partContext,
        partContextError,
      };
    }
    if (meshHash) {
      const declared = await declarePartContext(meshHash, serviceEnv);
      envCaptured = declared.ok && envDeclared;
      if (envDeclared && !declared.ok) envError = declared.error;
      const fresh = await fetchPartContext(meshHash);
      if (fresh.error) partContextError = fresh.error;
      partContext = fresh.context ?? null;
    } else if (envDeclared) {
      envError = "could not compute this part's mesh hash in the browser";
    }
    return { meshHash, envCaptured, envError, partContext, partContextError };
  })();

  const validationOut = await validationPromise;
  try {
    options.onValidation?.({
      validation: validationOut.v,
      validationError: validationOut.err,
    });
  } catch {
    // Rendering progress is best-effort and must never change the deterministic run.
  }

  const [floor, context] = await Promise.all([machinesPromise, contextPromise]);
  const quantities = quantityLadderForAnnual(context.partContext?.annual_volume);

  if (!validationAllowsCost(validationOut.v)) {
    return {
      file: input.file,
      validation: null,
      validationError: validationOut.err,
      cost: null,
      costGeometryInvalid: null,
      costError: null,
      machines: floor.machines,
      machinesError: floor.error,
      verification: null,
      quantities,
      env: input.env,
      envDeclared,
      envCaptured: context.envCaptured,
      envError: context.envError,
      meshHash: context.meshHash,
      partContext: context.partContext,
      partContextError: context.partContextError,
    };
  }

  const owned = ownedProcessesFrom(floor.machines).filter((p) =>
    KNOWN_ENGINE_PROCESSES.has(p)
  );
  const costOut = await postCost(
    input,
    owned,
    quantities
  );

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
    machines: floor.machines,
    machinesError: floor.error,
    verification,
    quantities: costOut.cost?.quantities ?? quantities,
    env: input.env,
    envDeclared,
    envCaptured: context.envCaptured,
    envError: context.envError,
    meshHash: context.meshHash,
    partContext: context.partContext,
    partContextError: context.partContextError,
  };
}
