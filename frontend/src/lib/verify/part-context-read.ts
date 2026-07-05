/**
 * READ side of the declared part-context (GET /api/v1/part-context/{mesh_hash}).
 *
 * The frozen `part-context.ts` only WRITES the world (PUT, during the walk). The
 * Part standing page needs to READ it back to render a part's lineage
 * (program → assembly → part) and its declared annual volume. This lives in a
 * separate module by contract (part-context.ts is a wired client we must not
 * rewrite) and goes SAME-ORIGIN through the authed proxy so the httpOnly session
 * cookie authenticates it — no API key touches the browser.
 *
 * Honesty: a 404 (no declared context for this part) is NOT an error — it is the
 * "no home yet" standing the design shows verbatim. We return `null` for it and
 * surface a real error string only for genuine failures (auth/network/5xx), so
 * the page never invents a program a part was never assigned to.
 */
import { API_BASE } from "@/lib/api-base";

/** The org-scoped declared context for a part, exactly the shape the backend
 *  serializes (part_context_service.serialize_context). Every field is a USER
 *  assertion (`provenance: "user"`), never inferred. Fields the org never
 *  declared come back null. */
export interface PartContext {
  mesh_hash: string;
  program: string | null;
  parent_assembly: string | null;
  units_per_parent: number | null;
  annual_volume: number | null;
  provenance: "user";
  /** the declared service world, only present when actually declared. */
  service_environment?: Record<string, unknown>;
}

export interface PartContextResult {
  /** the declared context, or null when the org has declared none (a 404 — the
   *  honest "no home yet" state, never an error). */
  context: PartContext | null;
  /** a real failure (auth/network/5xx) — distinct from a clean "none declared". */
  error: string | null;
}

/**
 * Read a part's declared context. A 404 → `{context:null, error:null}` (the part
 * simply has no declared home yet); any other non-2xx → `{context:null, error}`
 * so the caller can tell the truth about WHY it could not be read, never faking a
 * lineage. Network failures are caught and returned the same way.
 */
export async function fetchPartContext(meshHash: string): Promise<PartContextResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/part-context/${encodeURIComponent(meshHash)}`, {
      cache: "no-store",
    });
  } catch (e) {
    return { context: null, error: e instanceof Error ? e.message : "Network error" };
  }
  if (res.status === 404) return { context: null, error: null };
  if (!res.ok) {
    const body: Record<string, unknown> = await res.json().catch(() => ({}));
    const detail =
      (body.detail as string) ||
      (body.message as string) ||
      `part-context read failed (${res.status})`;
    return {
      context: null,
      error: typeof detail === "string" ? detail : JSON.stringify(detail),
    };
  }
  const context = (await res.json()) as PartContext;
  return { context, error: null };
}
