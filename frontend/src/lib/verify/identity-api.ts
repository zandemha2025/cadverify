/**
 * The confirm CALL for retrieval-grounded identity — POST /identity/confirm through
 * the same-origin authed proxy. Split from `identity.ts` (which stays import-free so
 * its pure selectors run under `node --test`) because this touches `fetch` + the API
 * base. A confirm turns a retrieved SUGGESTION into a USER-asserted identity on the
 * org's corpus row; the response carries the updated record (provenance USER).
 */
import { API_BASE } from "@/lib/api-base";

export interface ConfirmIdentityInput {
  mesh_hash: string;
  declared_part_id?: string | null;
  declared_name?: string | null;
  program?: string | null;
}

/** The confirmed corpus row the endpoint returns (serialize_signature). */
export interface ConfirmedIdentity {
  mesh_hash: string;
  declared_part_id: string | null;
  declared_name: string | null;
  program: string | null;
  source: string | null;
  provenance: string; // "USER"
  confirmed: boolean;
  updated_at: string | null;
}

export type ConfirmIdentityResult =
  | { ok: true; record: ConfirmedIdentity; error: null }
  | { ok: false; record: null; error: string };

/** POST a confirmed identity. Best-effort at the call site: a failure is returned
 *  honestly (never thrown), so the card can show a quiet error and keep the result
 *  intact. */
export async function confirmIdentity(
  input: ConfirmIdentityInput
): Promise<ConfirmIdentityResult> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/identity/confirm`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch (e) {
    return { ok: false, record: null, error: e instanceof Error ? e.message : "Network error" };
  }
  if (res.ok) {
    const record = (await res.json()) as ConfirmedIdentity;
    return { ok: true, record, error: null };
  }
  const body: Record<string, unknown> = await res.json().catch(() => ({}));
  const detail =
    (body.detail as string) || (body.message as string) || `Confirm failed (${res.status})`;
  return { ok: false, record: null, error: typeof detail === "string" ? detail : JSON.stringify(detail) };
}
