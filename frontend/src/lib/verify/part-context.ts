/**
 * Declared part-context client for the Verify surface — the REAL org-scoped
 * service-environment record (backend/src/api/part_context.py, mounted at
 * /api/v1/part-context/{mesh_hash}). The cost route resolves the org server-side
 * and reads `get_context(org_id, mesh_hash).service_environment`, so its
 * verification block reflects the conditions STORED on the part. A verification
 * run only reads them; this writer is called only for an explicit user edit
 * (see service-conditions.ts), never as a side effect of verifying.
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
import type { PartContext } from "./part-context-read.ts";

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
  /** the part's record as the PUT returned it (null on failure or an unreadable body). */
  context: PartContext | null;
}

export interface PreservePartContextFields {
  program?: string | null;
  parent_assembly?: string | null;
  units_per_parent?: number | null;
  annual_volume?: number | null;
}

/**
 * Persist the declared world for a part (PUT /part-context/{mesh_hash}). Idempotent
 * on (org, mesh_hash). `env` REPLACES the stored environment, so callers send the
 * complete set; `null` explicitly clears it (the API leaves a stored environment
 * unchanged for `{}`). A failure (no org on the session, insufficient role,
 * network) is returned as `{ok:false, error}` so the caller can tell the truth,
 * never swallowed and never surfaced as a fabricated success.
 */
export async function declarePartContext(
  meshHash: string,
  env: ServiceEnvironment | null,
  preserve?: PreservePartContextFields | null
): Promise<DeclareEnvResult> {
  const body: Record<string, unknown> = { service_environment: env };
  if (preserve) {
    body.program = preserve.program ?? null;
    body.parent_assembly = preserve.parent_assembly ?? null;
    body.units_per_parent = preserve.units_per_parent ?? null;
    body.annual_volume = preserve.annual_volume ?? null;
  }
  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/part-context/${encodeURIComponent(meshHash)}`,
      {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store",
      }
    );
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Network error", context: null };
  }
  if (res.ok) {
    const saved = (await res.json().catch(() => null)) as PartContext | null;
    const context = saved && typeof saved.mesh_hash === "string" ? saved : null;
    return { ok: true, error: null, context };
  }
  const errorBody: Record<string, unknown> = await res.json().catch(() => ({}));
  const detail =
    (errorBody.detail as string) ||
    (errorBody.message as string) ||
    `part-context declare failed (${res.status})`;
  return {
    ok: false,
    error: typeof detail === "string" ? detail : JSON.stringify(detail),
    context: null,
  };
}
