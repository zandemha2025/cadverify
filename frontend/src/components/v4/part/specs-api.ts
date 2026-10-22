/** Save a part's declared specs (PUT /part-context/{mesh_hash} with only `part_specs`). */
import { API_BASE } from "@/lib/api-base";
import type { PartContext } from "@/lib/verify/part-context-read";
import type { PartSpecs } from "./specs";
import { viewerRefusal } from "./plain-errors";

export interface SaveSpecsResult {
  ok: boolean;
  error: string | null;
  context: PartContext | null;
  /** How many saved records of this part are now out of date (their prices used the old specs). */
  markedStale: number;
}

function detailText(body: unknown, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail;
  const viewer = viewerRefusal(status, d, "change a part's specs");
  if (viewer) return viewer;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") return (d as { message: string }).message;
  return `The specs weren't saved (${status}).`;
}

/** Only `part_specs` is sent, so the part's other declared context stays as it is. Null clears. */
export async function savePartSpecs(meshHash: string, specs: PartSpecs | null, previous: PartContext | null): Promise<SaveSpecsResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/part-context/${encodeURIComponent(meshHash)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ part_specs: specs }),
      cache: "no-store",
    });
  } catch {
    return { ok: false, error: "The specs weren't saved: no connection.", context: null, markedStale: 0 };
  }
  const body = (await res.json().catch(() => null)) as (PartContext & { decisions_marked_stale?: number }) | null;
  if (!res.ok) return { ok: false, error: detailText(body, res.status), context: null, markedStale: 0 };
  const context: PartContext | null =
    body && typeof body.mesh_hash === "string"
      ? body
      : previous
        ? { ...previous, ...(specs ? { part_specs: specs as Record<string, unknown> } : {}) }
        : null;
  if (context && !specs) delete context.part_specs;
  return { ok: true, error: null, context, markedStale: body?.decisions_marked_stale ?? 0 };
}
