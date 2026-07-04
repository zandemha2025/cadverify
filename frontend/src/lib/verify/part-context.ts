/**
 * Declared part-context client for the Verify surface — the REAL org-scoped
 * service-environment record (backend/src/api/part_context.py, mounted at
 * /api/v1/part-context/{mesh_hash}). This is what makes the environment door
 * REAL end-to-end: the walk persists the declared world keyed by the part's
 * mesh_hash BEFORE it asks for a cost, so the cost route — which resolves the
 * org server-side and reads `get_context(org_id, mesh_hash).service_environment`
 * — returns a verification block whose env_exclusions reflect the declared world.
 *
 * The mesh_hash is the SHA-256 of the raw uploaded file bytes, exactly as the
 * server computes it (analysis_service.compute_mesh_hash → sha256 hexdigest). We
 * reproduce it in the browser with Web Crypto over the SAME File the cost call
 * uploads, so the two hashes are byte-for-byte identical and the context the
 * server reads back is the one we just wrote.
 *
 * Every call goes SAME-ORIGIN through the Next authed proxy so the httpOnly
 * session cookie authenticates it; no API key touches the browser. The declared
 * environment is a USER assertion (`provenance: "user"`), never inferred.
 */
import { API_BASE } from "@/lib/api-base";

/** The declared service environment, exactly the shape the backend validates
 *  (part_context_service.validate_service_environment): numeric temp/pressure,
 *  boolean corrosive/sour, free-text medium/standard. Unknown keys are rejected
 *  server-side, so we only ever send these. */
export interface ServiceEnvironment {
  max_temp_c?: number;
  min_temp_c?: number;
  pressure_bar?: number;
  corrosive?: boolean;
  sour_service?: boolean;
  medium?: string;
  standard?: string;
}

/** SHA-256 hex of the raw file bytes — the SAME digest the server keys context on
 *  (compute_mesh_hash). Web Crypto is available in every browser we target and in
 *  the Node test runtime; callers that lack it get a null (persistence is skipped,
 *  never faked). */
export async function computeMeshHash(file: File): Promise<string | null> {
  const subtle =
    typeof globalThis !== "undefined" &&
    globalThis.crypto &&
    globalThis.crypto.subtle;
  if (!subtle) return null;
  const buf = await file.arrayBuffer();
  const digest = await subtle.digest("SHA-256", buf);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export interface DeclareEnvResult {
  ok: boolean;
  /** the exact server error (why the world could NOT be captured), for honest copy. */
  error: string | null;
}

/**
 * Persist the declared world for a part (PUT /part-context/{mesh_hash}). Idempotent
 * on (org, mesh_hash). Best-effort by contract: a failure (no org on the session,
 * insufficient role, network) is returned as `{ok:false, error}` so the caller can
 * tell the truth ("drives this preview only — not captured"), never swallowed and
 * never surfaced as a fabricated success.
 */
export async function declarePartContext(
  meshHash: string,
  env: ServiceEnvironment
): Promise<DeclareEnvResult> {
  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/part-context/${encodeURIComponent(meshHash)}`,
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ service_environment: env }),
        cache: "no-store",
      }
    );
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Network error" };
  }
  if (res.ok) return { ok: true, error: null };
  const body: Record<string, unknown> = await res.json().catch(() => ({}));
  const detail =
    (body.detail as string) ||
    (body.message as string) ||
    `part-context declare failed (${res.status})`;
  return { ok: false, error: typeof detail === "string" ? detail : JSON.stringify(detail) };
}

/** Map the walk's three environment toggles to the backend service-environment
 *  shape. Ambient (nothing toggled) → an empty object, which the backend treats
 *  as a no-op (byte-identical) AND which coherently CLEARS a prior declaration on
 *  the same part when the user un-declares its world. The concrete numbers mirror
 *  the door's chip labels (120 °C / sour H₂S / 35 MPa = 350 bar). */
export function envToServiceEnvironment(env: {
  temp: boolean;
  sour: boolean;
  pressure: boolean;
}): ServiceEnvironment {
  const out: ServiceEnvironment = {};
  if (env.temp) out.max_temp_c = 120;
  if (env.sour) out.sour_service = true;
  if (env.pressure) out.pressure_bar = 350; // 35 MPa → 350 bar
  return out;
}
