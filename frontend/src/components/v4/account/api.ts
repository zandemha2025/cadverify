/**
 * Browser data calls for the Account screens. Everything goes same-origin
 * through the authed proxy (`API_BASE` → backend `/api/v1`), so the session
 * cookie authenticates it. Mutations that already have server actions
 * (invites, members, SAML mappings, org switch) use those; key create/rotate
 * use ./actions so the one-time secret reaches this page (see there).
 */
import { API_BASE } from "@/lib/api-base";
import { isStripeUrl } from "@/lib/billing";
import type { OrgRole } from "./derive";

export class HttpError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/** The server's own words from a FastAPI error body (`detail` string or `{ message }`). */
export function messageFrom(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const b = body as { detail?: unknown; message?: unknown };
  const d = b.detail;
  if (typeof d === "string" && d.trim()) return d.trim();
  if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") return (d as { message: string }).message;
  if (typeof b.message === "string" && b.message.trim()) return b.message.trim();
  return null;
}

export function errText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}

export function isGated(e: unknown): boolean {
  return e instanceof HttpError && (e.status === 401 || e.status === 403);
}

async function call<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: init?.method ?? "GET",
    cache: "no-store",
    headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new HttpError(messageFrom(body) ?? `Request failed (${res.status})`, res.status);
  }
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}

// ── organizations ──────────────────────────────────────────────────────────
export type OrgSummary = { org_id: string; name: string; org_role: OrgRole; joined_at: string | null; is_active: boolean };
export type OrgList = { active_org_id: string | null; organizations: OrgSummary[] };
export type OrgMember = { user_id: number; email: string; is_active: boolean; org_role: OrgRole; joined_at: string | null };
export type OrgInvite = {
  id: number;
  email: string;
  role: OrgRole;
  status: "pending" | "accepted" | "expired" | "revoked";
  expires_at: string | null;
  accepted_at: string | null;
  revoked_at?: string | null;
  created_at: string | null;
};
export type PlatformUser = { id: number; email: string; role: string; org_id: string | null; org_role: string | null; auth_provider: string | null; created_at: string | null };
export type SamlMapping = { id: number; attribute_name: string; group_value: string; org_role: OrgRole; created_at: string | null };

export const getOrgs = () => call<OrgList>("/orgs");
/** Rename the active organization (org admins only); invites and the header use the new name. */
export const renameOrg = (name: string) => call<{ org_id: string; name: string; slug: string }>("/orgs/current", { method: "PATCH", body: { name } });
export const getMembers = () => call<{ members: OrgMember[] }>("/orgs/members").then((b) => b.members ?? []);
export const getInvites = () => call<{ invites: OrgInvite[] }>("/orgs/invites").then((b) => b.invites ?? []);
export const getMappings = () => call<{ mappings: SamlMapping[] }>("/orgs/saml/group-mappings").then((b) => b.mappings ?? []);
export const setOrgRole = (userId: number, role: OrgRole) => call<{ user_id: number; org_role: OrgRole }>(`/orgs/members/${userId}/role`, { method: "PATCH", body: { role } });
/** Platform ("workspace") role. The backend allows this to platform superadmins only, never on yourself. */
export const setWorkspaceRole = (userId: number, role: string) => call<{ id: number; role: string }>(`/admin/users/${userId}/role`, { method: "PATCH", body: { role } });

/** Every member's platform role and sign-in (org admins only), following the cursor. */
export async function getPlatformUsers(): Promise<PlatformUser[]> {
  const out: PlatformUser[] = [];
  let cursor: number | null = null;
  for (let page = 0; page < 20; page++) {
    const q: string = cursor == null ? "?limit=100" : `?limit=100&cursor=${cursor}`;
    const b: { users: PlatformUser[]; next_cursor: number | null; has_more: boolean } = await call(`/admin/users${q}`);
    out.push(...(b.users ?? []));
    if (!b.has_more || b.next_cursor == null) break;
    cursor = b.next_cursor;
  }
  return out;
}

// ── API keys ───────────────────────────────────────────────────────────────
export type ApiKey = { id: number; name: string; prefix: string; created_at: string; last_used_at: string | null; revoked_at: string | null };
export const getKeys = () => call<ApiKey[]>("/keys");
export const renameKey = (id: number, name: string) => call<{ id: number; name: string }>(`/keys/${id}`, { method: "PATCH", body: { name } });
export const revokeKey = (id: number) => call<null>(`/keys/${id}`, { method: "DELETE" });

// ── activity (org admins) ──────────────────────────────────────────────────
export type UsageSummary = {
  window_days: number;
  counts: { analyses: number; cost_decisions: number; usage_events: number; webhook_deliveries: number };
  event_counts: Record<string, number>;
  webhook_status_counts: Record<string, number>;
};
export type WebhookDelivery = {
  id: number;
  batch_id: number;
  batch_ulid: string;
  event_type: string;
  status: string;
  attempts: number;
  response_code: number | null;
  created_at: string | null;
  last_attempt_at: string | null;
  next_retry_at: string | null;
};
export type AuditEntry = {
  id: number;
  timestamp: string | null;
  user_id: number | null;
  user_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  detail: Record<string, unknown> | null;
  result_summary: string | null;
};
export type AuditPage = { entries: AuditEntry[]; next_cursor: string | null; has_more: boolean };

export const getUsage = (days: number) => call<UsageSummary>(`/admin/usage-summary?days=${days}`);
export const getDeliveries = (limit = 12) => call<{ deliveries: WebhookDelivery[] }>(`/admin/webhook-deliveries?limit=${limit}`).then((b) => b.deliveries ?? []);

/** ISO with an explicit +00:00 (the backend's fromisoformat on older Pythons rejects a bare Z). */
export function auditRange(days: number, now = Date.now()): { start: string; end: string } {
  const iso = (ms: number) => new Date(ms).toISOString().replace("Z", "+00:00");
  return { start: iso(now - days * 86_400_000), end: iso(now) };
}

export function getAuditPage(range: { start: string; end: string }, cursor: string | null, limit = 200): Promise<AuditPage> {
  const q = new URLSearchParams({ start: range.start, end: range.end, limit: String(limit) });
  if (cursor) q.set("cursor", cursor);
  return call<AuditPage>(`/admin/audit-log?${q.toString()}`);
}

/** The audit log as CSV for a range (a real download the page saves). */
export async function downloadAuditCsv(range: { start: string; end: string }): Promise<Blob> {
  const q = new URLSearchParams({ start: range.start, end: range.end, format: "csv" });
  const res = await fetch(`${API_BASE}/admin/audit-log?${q.toString()}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new HttpError(messageFrom(body) ?? `Export failed (${res.status})`, res.status);
  }
  return res.blob();
}

// ── billing ────────────────────────────────────────────────────────────────
export type BillingStatus = {
  checkout_available: boolean;
  plan: string;
  status: string | null;
  current_period_end: string | null;
  manage_available: boolean;
  pro_monthly_checks: number;
};
export const getBilling = () => call<BillingStatus>("/billing");

/**
 * Start Checkout or open the portal. `return_to: "app"` asks the backend to send
 * the person back into this app (Checkout success → /app?upgraded=1, cancel and
 * portal → Plan and billing); a backend without that field ignores it.
 */
export async function billingLink(kind: "checkout" | "portal"): Promise<{ kind: "redirect"; url: string } | { kind: "manage" } | { kind: "sign_in" } | { kind: "error"; message: string }> {
  try {
    const res = await fetch(`${API_BASE}/billing/${kind}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ return_to: "app" }),
    });
    const body = await res.json().catch(() => null);
    if (res.status === 401) return { kind: "sign_in" };
    const code = body && typeof body === "object" && body.detail && typeof body.detail === "object" ? (body.detail as { code?: unknown }).code : null;
    if (kind === "checkout" && res.status === 409 && code === "already_pro") return { kind: "manage" };
    const url = body && typeof body === "object" ? (body as { url?: unknown }).url : null;
    if (res.ok && typeof url === "string" && isStripeUrl(url)) return { kind: "redirect", url };
    return { kind: "error", message: messageFrom(body) ?? (kind === "checkout" ? "Checkout didn’t open." : "Billing didn’t open.") };
  } catch {
    return { kind: "error", message: "Check your connection and try again." };
  }
}
