import { partCheckHeaders } from "./check-id.ts";
/**
 * The Verify pipeline — the request lifecycle behind the walk. It calls the REAL
 * engine through the same-origin authed proxy and shapes the responses for the
 * verdict walk. NOTHING here fabricates a number: every figure the walk renders
 * comes from one of these responses or is withheld.
 *
 *   POST /validate         → routing + DFM (ValidationResult)          [real]
 *   GET  /part-context/{h} → the part's STORED context + service conditions [real]
 *   POST /validate/cost    → the glass-box should-cost record (CostReport) [real]
 *   GET  /machine-inventory→ the org's declared floor (OwnedMachine[])  [real]
 *
 * The cost route returns a top-level `verification` block (per-route machine fit /
 * verdict lattice / env exclusions) whenever the org declared machines and/or this
 * part's service environment. The route reads the environment STORED on the part
 * (keyed by mesh_hash) server-side, so a run only READS the part context to show
 * which conditions it was costed under; it never writes it. Changing conditions is
 * an explicit edit (service-conditions.ts). When neither inventory nor an
 * environment is declared, no block is emitted → the walk renders the honest
 * "not evaluated" state, NEVER a fabricated verdict.
 */
import { validateFile, withHttpStatus, type HttpError, type ValidationResult, type CostReport, type CostGeometry } from "@/lib/api";
import { API_BASE } from "@/lib/api-base";
import { apiProblemDetail, apiQuotaMessage, apiRecoveryMessage } from "@/lib/api-recovery";
import { listMachines, ownedProcessesFrom, type OwnedMachine } from "./machine-api";
import { readVerification, type VerificationBlock } from "./verification";
import { computeMeshHash, type ServiceEnvironment } from "./part-context";
import { fetchPartContext, type PartContext } from "./part-context-read";
import {
  hasServiceConditions,
  normalizeServiceEnvironment,
  saveServiceConditions,
  storedServiceEnvironment,
} from "./service-conditions";
import { readJsonOrNull, validationAllowsCost } from "./run-gates";
import { resolvedAnnualVolume } from "./program-rollup";
import { quantityLadderFor } from "./qty-ladder";

// Re-export so existing importers keep resolving these off `run` unchanged.
export type { VerificationBlock, MakeabilityLattice } from "./verification";

export interface VerifyInput {
  file: File;
  materialClass: string;
  /** Conditions the user set BEFORE this part's record was shown. Saved only
   *  when the record holds none; stored conditions always win and are never
   *  overwritten by a run. */
  declare?: ServiceEnvironment | null;
  /** Turn the part before the check ("rotation:…", see components/v4/orient/orient.ts):
   *  its +Z is the build direction for printing and the opening direction for
   *  molding. Unset/null: the file's own axes. Same file, so no extra check. */
  orientation?: string | null;
  /** An order quantity to price exactly (the one the cost breakdown showed when the
   *  person chose Check another part): one of the six priced points, like a declared
   *  annual volume. Unset: the standard ladder. */
  quantity?: number | null;
}

/** What happened to `VerifyInput.declare`: "saved" (the record had none),
 *  "kept_stored" (the record's own conditions were applied instead) or "failed"
 *  (the save failed, so the run used the record as it was). */
export interface DeclaredBeforeRun {
  outcome: "saved" | "kept_stored" | "failed";
  error: string | null;
}

export interface VerifyProgress {
  /** The first useful engine result. Costing intentionally remains sequential so
   *  the two geometry-heavy requests never double peak worker memory. */
  validation: ValidationResult | null;
  validationError: string | null;
}

export interface RunVerificationOptions {
  onValidation?: (progress: VerifyProgress) => void;
  /** Read when pricing starts, after routing + DFM return: the material the
   *  user picked while the geometry check ran. Unset: `input.materialClass`. */
  materialClass?: () => string;
}

/** Engine process ids the cost endpoint accepts in `owned_processes` — passing an
 *  id it doesn't know 400s the WHOLE cost call, so we only forward known ids
 *  (an unknown owned machine just falls back to fully-loaded costing, still honest). */
export const KNOWN_ENGINE_PROCESSES = new Set([
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
  /** The refusal's HTTP status and code when the server refused the check (413
   *  CHECK_TOO_LARGE: too heavy for the web process; the worker can take it). */
  validationStatus?: number | null;
  validationCode?: string | null;
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
  /** The service conditions STORED on the part when this run read its record:
   *  the ones the cost route applied (env exclusions, NACE MR0175 / HDT). A run
   *  never writes them. */
  serviceEnvironment: ServiceEnvironment;
  envDeclared: boolean;
  /** why the stored conditions could not be read (null when read cleanly). */
  envError: string | null;
  /** set only when the run carried `VerifyInput.declare`. */
  declaredBeforeRun?: DeclaredBeforeRun | null;
  /** SHA-256 of the uploaded bytes, matching the backend's mesh_hash. */
  meshHash: string | null;
  /** Existing/persisted USER context for this part, if the org declared one. */
  partContext: PartContext | null;
  partContextError: string | null;
}

// The six quantities a check prices (log-spaced, the backend's six-point limit)
// live in qty-ladder.ts (pure, tested); declared volumes and a carried order
// quantity become exact points on it.
export { QTY_LADDER, quantityLadderFor, quantityLadderForAnnual } from "./qty-ladder";

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
  if (input.orientation) form.append("orientation", input.orientation);
  if (ownedProcesses.length > 0) {
    form.append("owned_processes", ownedProcesses.join(","));
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/validate/cost`, { method: "POST", body: form, headers: partCheckHeaders(input.file) });
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
    apiQuotaMessage(body) || apiProblemDetail(body) ||
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
  const quantities = quantityLadderFor([annualVolume, input.quantity]);
  const costOut = await postCost(input, owned, quantities);
  return {
    cost: costOut.cost,
    costGeometryInvalid: costOut.invalid,
    costError: costOut.error,
    verification: readVerification(costOut.cost) ?? null,
    quantities: costOut.cost?.quantities ?? quantities,
  };
}

/** POST /validate?orientation=… for a turned re-check, with the same refusals as
 *  validateFile (which carries no orientation). */
async function validateOriented(file: File, orientation: string, partCheckId?: string): Promise<ValidationResult> {
  const form = new FormData();
  form.append("file", file);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/validate?orientation=${encodeURIComponent(orientation)}`, {
      method: "POST",
      body: form,
      headers: partCheckId ? { "x-part-check-id": partCheckId } : undefined,
    });
  } catch {
    throw new Error("The check couldn't reach the server. Check the connection and try again.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw withHttpStatus(
      new Error(
        apiQuotaMessage(body) || apiProblemDetail(body) ||
          apiRecoveryMessage({ status: res.status, payload: body, resource: "verification", retryAfter: res.headers.get("retry-after") }),
      ),
      res.status,
      body,
    );
  }
  if (!body) throw new Error("Unexpected server response");
  return body as ValidationResult;
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
  const checkId = partCheckHeaders(input.file)["x-part-check-id"];
  const validationPromise = (input.orientation
    ? validateOriented(input.file, input.orientation, checkId)
    : validateFile(input.file, undefined, undefined, undefined, undefined, checkId)).then(
    (v) => ({ v, err: null as string | null, status: null as number | null, code: null as string | null }),
    (e) => ({
      v: null as ValidationResult | null,
      err: e instanceof Error ? e.message : "Validation failed",
      status: (e as HttpError)?.status ?? null,
      code: (e as HttpError)?.code ?? null,
    })
  );

  const machinesPromise = listMachines().then(
    (payload) => ({ machines: payload.machines, error: null as string | null }),
    (e) => ({
      machines: [] as OwnedMachine[],
      error: e instanceof Error ? e.message : "Could not load machine inventory",
    })
  );

  // ── the part's stored context ──────────────────────────────────────────────
  // The cost route applies the STORED service conditions server-side, so a run
  // reads them to show which conditions it was costed under. It never writes over
  // them: writing here (as it once did, with an empty or chip-only set) erased
  // stored conditions. The one write is `declare`, and only onto an empty record.
  const contextPromise = (async () => {
    let envError: string | null = null;
    let partContext: PartContext | null = null;
    let partContextError: string | null = null;
    let declaredBeforeRun: DeclaredBeforeRun | null = null;
    const meshHash = await computeMeshHash(input.file).catch(() => null);
    if (meshHash) {
      const stored = await fetchPartContext(meshHash);
      partContextError = stored.error;
      envError = stored.error;
      partContext = stored.context;
      const declare = normalizeServiceEnvironment(input.declare);
      if (!stored.error && hasServiceConditions(declare)) {
        if (hasServiceConditions(storedServiceEnvironment(stored.context))) {
          declaredBeforeRun = { outcome: "kept_stored", error: null };
        } else if (validationAllowsCost((await validationPromise).v)) {
          // Persist only after routing + DFM returned (QA ISSUE-001).
          const saved = await saveServiceConditions(meshHash, declare, stored.context);
          if (saved.ok) partContext = saved.context;
          declaredBeforeRun = saved.ok
            ? { outcome: "saved", error: null }
            : { outcome: "failed", error: saved.error };
        }
      }
    } else {
      envError = "could not compute this part's mesh hash in the browser";
    }
    const serviceEnvironment = storedServiceEnvironment(partContext);
    return {
      meshHash,
      serviceEnvironment,
      envDeclared: hasServiceConditions(serviceEnvironment),
      envError,
      declaredBeforeRun,
      partContext,
      partContextError,
    };
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
  const quantities = quantityLadderFor([resolvedAnnualVolume(context.partContext), input.quantity]);

  if (!validationAllowsCost(validationOut.v)) {
    return {
      file: input.file,
      validation: null,
      validationError: validationOut.err,
      validationStatus: validationOut.status,
      validationCode: validationOut.code,
      cost: null,
      costGeometryInvalid: null,
      costError: null,
      machines: floor.machines,
      machinesError: floor.error,
      verification: null,
      quantities,
      serviceEnvironment: context.serviceEnvironment,
      envDeclared: context.envDeclared,
      envError: context.envError,
      declaredBeforeRun: context.declaredBeforeRun,
      meshHash: context.meshHash,
      partContext: context.partContext,
      partContextError: context.partContextError,
    };
  }

  const owned = ownedProcessesFrom(floor.machines).filter((p) =>
    KNOWN_ENGINE_PROCESSES.has(p)
  );
  // The geometry check doesn't depend on the material; the price does. Price in
  // the material answered while the check ran (the same file and check id, so
  // the server reuses the geometry it just analysed and uses no extra check).
  const costOut = await postCost(
    options.materialClass ? { ...input, materialClass: options.materialClass() } : input,
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
    serviceEnvironment: context.serviceEnvironment,
    envDeclared: context.envDeclared,
    envError: context.envError,
    declaredBeforeRun: context.declaredBeforeRun,
    meshHash: context.meshHash,
    partContext: context.partContext,
    partContextError: context.partContextError,
  };
}
