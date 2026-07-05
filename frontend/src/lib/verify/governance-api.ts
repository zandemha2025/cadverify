/**
 * Governed change-request client for the Verify surface — the REAL W4 governance
 * flow (backend/src/api/governance.py, mounted at /api/v1/governance). Every call
 * goes SAME-ORIGIN through the Next authed proxy (`/api/proxy/governance/*`), so
 * the httpOnly session cookie authenticates it and no API key touches the browser.
 *
 * Honesty: a change request is a REAL org-scoped row (propose -> review -> publish
 * over the governed rate-card / shop-profile libraries). Absent governance activity
 * -> an empty list, byte-identical to the feature unused. `status === "proposed"`
 * is the only one that NEEDS a reviewer; the Home "Needs your action" queue filters
 * on it. Nothing here is invented — the queue is empty when the org has no drafts.
 */
import { API_BASE } from "@/lib/api-base";

/** One change request as the backend serializes it (governance_service.serialize_request). */
export interface ChangeRequest {
  id: number;
  ulid: string;
  org_id: string;
  asset_type: string; // "rate_card" | "shop_profile" | ...
  target_version_id: number;
  status: "draft" | "proposed" | "approved" | "rejected" | string;
  title: string;
  note: string;
  proposed_by: number | null;
  reviewed_by: number | null;
  created_at: string | null;
  decided_at: string | null;
}

const BASE = `${API_BASE}/governance`;

async function toError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  const detail =
    (body && (body.detail || body.message)) || `Request failed (${res.status})`;
  return new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
}

/** All change requests for the caller's org, newest first; optional status filter. */
export async function listChangeRequests(
  status?: string
): Promise<{ change_requests: ChangeRequest[] }> {
  const url = status
    ? `${BASE}/change-requests?status=${encodeURIComponent(status)}`
    : `${BASE}/change-requests`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw await toError(res);
  return res.json();
}
