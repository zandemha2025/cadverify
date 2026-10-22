/**
 * Calls for deleting a part, the organization or your account, and for share links that end.
 * Signed-in calls go through the same-origin authed proxy (`API_BASE`); the
 * public share reads go to the backend's public routes.
 */
import { API_BASE, browserOrBackendUrl } from "@/lib/api-base";
import type { AccountPreview, ExpiryChoice, LinkStatus, OrgPreview, PartPreview, Receipt } from "./words";

export class DataApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = "DataApiError";
    this.status = status;
    this.code = code;
  }
}

/** The app serves a coded error as the body itself ({code, message}); plain ones as {detail}. */
function message(body: unknown, status: number): { text: string; code: string | null } {
  const top = body as { detail?: unknown; code?: unknown; message?: unknown } | null;
  if (typeof top?.code === "string" && typeof top.message === "string" && top.message.trim()) return { text: top.message, code: top.code };
  const d = top?.detail;
  if (typeof d === "string" && d.trim()) return { text: d, code: null };
  if (d && typeof d === "object") {
    const m = (d as { message?: unknown; code?: unknown }).message;
    const c = (d as { code?: unknown }).code;
    if (typeof m === "string" && m.trim()) return { text: m, code: typeof c === "string" ? c : null };
  }
  if (status === 404) return { text: "Not found in your organization.", code: null };
  if (status === 403) return { text: "Your role can't do this. Ask an admin.", code: null };
  if (status === 429) return { text: "Too many requests for now. Wait a few minutes and retry.", code: null };
  if (status >= 500) return { text: "The server had a problem. Nothing more was changed. Retry in a moment.", code: null };
  return { text: `The server answered ${status}.`, code: null };
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { cache: "no-store", ...init });
  } catch {
    throw new DataApiError("The server couldn't be reached. Check your connection and retry.", 0);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const m = message(body, res.status);
    throw new DataApiError(m.text, res.status, m.code);
  }
  return body as T;
}

function jsonBody(method: string, payload: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(payload) };
}

const enc = encodeURIComponent;

export function partDeletionPreview(key: string, keepCopies = false): Promise<PartPreview> {
  return call<PartPreview>(`/parts/${enc(key)}/deletion-preview${keepCopies ? "?keep_fixed_copies=true" : ""}`);
}

export function deletePart(key: string, keepCopies = false): Promise<Receipt> {
  return call<Receipt>(`/parts/${enc(key)}${keepCopies ? "?keep_fixed_copies=true" : ""}`, { method: "DELETE" });
}

export function orgDeletionPreview(): Promise<OrgPreview> {
  return call<OrgPreview>("/orgs/current/deletion-preview");
}

export function deleteOrg(confirmName: string, keepPlan = false): Promise<Receipt> {
  return call<Receipt>("/orgs/current/delete", jsonBody("POST", { confirm_name: confirmName, keep_plan: keepPlan }));
}

export function accountDeletionPreview(): Promise<AccountPreview> {
  return call<AccountPreview>("/account/deletion-preview");
}

/** Deletes the signed-in person's account. The session stops working on the server at once. */
export function deleteAccount(confirmEmail: string): Promise<Receipt> {
  return call<Receipt>("/account/delete", jsonBody("POST", { confirm_email: confirmEmail }));
}

export function deletionStatus(id: string): Promise<Receipt> {
  return call<Receipt>(`/data-deletions/${enc(id)}`);
}

/* ── share links ─────────────────────────────────────────────────────────── */

export type LinkKind = "check" | "record" | "package";

export interface ShareLinkFields {
  is_public: boolean;
  share_url: string | null;
  share_status: LinkStatus | null;
  share_expires_at: string | null;
  share_created_at: string | null;
  share_ended_at: string | null;
  share_end_date_added: boolean;
}

export interface ShareLinkRow {
  kind: LinkKind;
  id: string;
  /** null for a package's link. */
  part_key: string | null;
  /** What a part's or package's link shows (null for a check's, or one made before the choice). */
  shows?: { include_cost?: boolean; include_cad?: boolean } | null;
  name: string;
  url: string;
  status: LinkStatus;
  created_at: string | null;
  expires_at: string | null;
  ended_at: string | null;
  end_date_added: boolean;
  mine: boolean;
  can_switch_off: boolean;
  made_by: string | null;
}

export interface ShareLinkList {
  scope: "mine" | "org";
  is_admin: boolean;
  default_days: number;
  links: ShareLinkRow[];
}

function sharePath(kind: LinkKind, id: string): string {
  if (kind === "package") return `/rfq-packages/${enc(id)}/share`;
  return kind === "check" ? `/analyses/${enc(id)}/share` : `/cost-decisions/${enc(id)}/share`;
}

/** Make a link that ends after `days` (null: the explicit "no end date"). An existing working link comes back unchanged. */
export function createLink(kind: LinkKind, id: string, days: ExpiryChoice): Promise<ShareLinkFields & { share_short_id: string }> {
  return call(sharePath(kind, id), jsonBody("POST", { expires_in_days: days }));
}

export async function switchOffLink(kind: LinkKind, id: string): Promise<void> {
  await call<unknown>(sharePath(kind, id), { method: "DELETE" });
}

export function listLinks(scope: "mine" | "org"): Promise<ShareLinkList> {
  return call<ShareLinkList>(`/share-links?scope=${scope}`);
}

/* ── the public page's read ──────────────────────────────────────────────── */

export type PublicShare<T> =
  | { ok: true; data: T }
  | { ok: false; reason: "expired" | "off" | "missing" | "error"; endedAt: string | null };

/** A shared link's payload, or why it can't be shown (410 ended / switched off, 404 unknown). */
export async function readPublicShare<T>(path: `/s/${string}`): Promise<PublicShare<T>> {
  let res: Response;
  try {
    res = await fetch(browserOrBackendUrl(path), { cache: "no-store" });
  } catch {
    return { ok: false, reason: "error", endedAt: null };
  }
  if (res.ok) return { ok: true, data: (await res.json()) as T };
  type Ended = { code?: string; ended_at?: string | null };
  const body = (await res.json().catch(() => null)) as (Ended & { detail?: Ended }) | null;
  const code = body?.code ?? body?.detail?.code;
  const endedAt = body?.ended_at ?? body?.detail?.ended_at ?? null;
  if (res.status === 410 && code === "share_expired") return { ok: false, reason: "expired", endedAt };
  if (res.status === 410) return { ok: false, reason: "off", endedAt };
  if (res.status === 404) return { ok: false, reason: "missing", endedAt: null };
  return { ok: false, reason: "error", endedAt: null };
}
