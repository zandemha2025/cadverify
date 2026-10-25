/**
 * A part's STORED service conditions on the Verify surface: the read / edit /
 * save logic behind the conditions editor, kept UI-free so a redesigned surface
 * can reuse it.
 *
 * Contract: a verification run only READS the stored conditions
 * (GET /part-context/{mesh_hash}); the cost route applies them server-side. Only
 * an explicit user edit writes them back, and a save always sends the COMPLETE
 * edited set (or an explicit null to clear), never an empty or partial object
 * that would overwrite conditions the user never saw.
 */
import { declarePartContext, type ServiceEnvironment } from "./part-context.ts";
import type { PartContext } from "./part-context-read.ts";

const NUMBER_FIELDS = ["min_temp_c", "max_temp_c", "pressure_bar"] as const;
const BOOLEAN_FIELDS = ["corrosive", "sour_service"] as const;
const TEXT_FIELDS = ["medium", "standard"] as const;

const NUMBER_LABELS: Record<(typeof NUMBER_FIELDS)[number], string> = {
  min_temp_c: "Min temperature",
  max_temp_c: "Max temperature",
  pressure_bar: "Pressure",
};

/** Keep only the fields the API accepts, each with a value that declares
 *  something: a finite number, `true`, or non-blank text. `false`, null and blank
 *  declare nothing, so they never make an environment look "declared". */
export function normalizeServiceEnvironment(raw: unknown): ServiceEnvironment {
  const out: ServiceEnvironment = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  const source = raw as Record<string, unknown>;
  for (const key of NUMBER_FIELDS) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value)) out[key] = value;
  }
  for (const key of BOOLEAN_FIELDS) {
    if (source[key] === true) out[key] = true;
  }
  for (const key of TEXT_FIELDS) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) out[key] = value.trim();
  }
  return out;
}

/** The conditions stored on a part's record (empty when none are declared). */
export function storedServiceEnvironment(
  context: PartContext | null | undefined
): ServiceEnvironment {
  return normalizeServiceEnvironment(context?.service_environment);
}

export function hasServiceConditions(env: ServiceEnvironment | null | undefined): boolean {
  return Object.keys(normalizeServiceEnvironment(env)).length > 0;
}

export function sameServiceEnvironment(
  a: ServiceEnvironment | null | undefined,
  b: ServiceEnvironment | null | undefined
): boolean {
  const left = normalizeServiceEnvironment(a) as Record<string, unknown>;
  const right = normalizeServiceEnvironment(b) as Record<string, unknown>;
  const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
  for (const key of keys) {
    if (left[key] !== right[key]) return false;
  }
  return true;
}

/** True when the part's record now holds different conditions from the ones the
 *  shown verification was costed under (an edit was saved after the run). */
export function conditionsChangedSinceRun(
  runEnvironment: ServiceEnvironment,
  record: PartContext | null | undefined
): boolean {
  return !sameServiceEnvironment(runEnvironment, storedServiceEnvironment(record));
}

/** Editor state: numbers stay text while typing so invalid input is reported,
 *  never silently dropped. */
export interface ServiceConditionsDraft {
  min_temp_c: string;
  max_temp_c: string;
  pressure_bar: string;
  corrosive: boolean;
  sour_service: boolean;
  medium: string;
  standard: string;
}

export function draftFromServiceEnvironment(
  env: ServiceEnvironment | null | undefined
): ServiceConditionsDraft {
  const n = normalizeServiceEnvironment(env);
  return {
    min_temp_c: n.min_temp_c == null ? "" : String(n.min_temp_c),
    max_temp_c: n.max_temp_c == null ? "" : String(n.max_temp_c),
    pressure_bar: n.pressure_bar == null ? "" : String(n.pressure_bar),
    corrosive: n.corrosive === true,
    sour_service: n.sour_service === true,
    medium: n.medium ?? "",
    standard: n.standard ?? "",
  };
}

export interface ParsedServiceConditions {
  env: ServiceEnvironment;
  errors: string[];
}

/** Parse the editor into the API shape, with the same rules the backend
 *  validator applies (numbers, pressure >= 0) plus a min <= max sanity check. */
export function serviceEnvironmentFromDraft(
  draft: ServiceConditionsDraft
): ParsedServiceConditions {
  const env: ServiceEnvironment = {};
  const errors: string[] = [];
  for (const key of NUMBER_FIELDS) {
    const text = draft[key].trim();
    if (!text) continue;
    const value = Number(text);
    if (!Number.isFinite(value)) {
      errors.push(`${NUMBER_LABELS[key]} must be a number.`);
      continue;
    }
    env[key] = value;
  }
  if (env.pressure_bar != null && env.pressure_bar < 0) {
    errors.push("Pressure must be 0 bar or more.");
  }
  if (env.min_temp_c != null && env.max_temp_c != null && env.min_temp_c > env.max_temp_c) {
    errors.push("Min temperature must not be above max temperature.");
  }
  for (const key of BOOLEAN_FIELDS) {
    if (draft[key]) env[key] = true;
  }
  for (const key of TEXT_FIELDS) {
    const text = draft[key].trim();
    if (text) env[key] = text;
  }
  return { env, errors };
}

export interface SaveServiceConditionsResult {
  ok: boolean;
  error: string | null;
  /** The part's record after the write, for the caller to show (null on failure). */
  context: PartContext | null;
}

/**
 * Save an explicit edit. `env` is the COMPLETE set the user is looking at: it
 * replaces the stored environment, and an empty set is sent as an explicit null
 * so clearing is deliberate. Only service_environment is sent; the part's other
 * declared context (program, assembly, volume) is left as it is.
 */
export async function saveServiceConditions(
  meshHash: string,
  env: ServiceEnvironment,
  previous: PartContext | null = null
): Promise<SaveServiceConditionsResult> {
  const complete = normalizeServiceEnvironment(env);
  const declared = hasServiceConditions(complete);
  const saved = await declarePartContext(meshHash, declared ? complete : null);
  if (!saved.ok) return { ok: false, error: saved.error, context: null };
  if (saved.context) return { ok: true, error: null, context: saved.context };
  // The write landed but its body was unreadable: show the previous record with
  // the saved conditions rather than pretend nothing changed.
  const context: PartContext = previous
    ? { ...previous }
    : {
        mesh_hash: meshHash,
        program: null,
        parent_assembly: null,
        units_per_parent: null,
        annual_volume: null,
        provenance: "user",
      };
  delete context.service_environment;
  if (declared) context.service_environment = { ...complete };
  return { ok: true, error: null, context };
}
