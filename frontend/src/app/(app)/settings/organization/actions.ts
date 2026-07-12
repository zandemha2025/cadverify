"use server";
/**
 * Org-admin settings server actions.
 *
 * Every call is same-rails as keys/actions.ts: read the httpOnly `dash_session`
 * cookie and forward it server-side to the backend (`backendUrl`). Org-admin
 * RBAC is enforced by the backend (`require_org_role`) — these actions never
 * fabricate authorization. Reads return plain data; mutations return a
 * discriminated `{ ok }` result so callers surface the backend's real error
 * (e.g. last-admin protection, duplicate SAML mapping) honestly instead of
 * crashing the route.
 */
import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { backendUrl, backendOrigin } from "@/lib/api-base";

const ORG_SETTINGS_PATH = "/settings/organization";

async function authed(path: string, init?: RequestInit) {
  const c = await cookies();
  const dash = c.get("dash_session")?.value ?? "";
  return fetch(backendUrl(path), {
    ...init,
    headers: { ...(init?.headers || {}), Cookie: `dash_session=${dash}` },
    cache: "no-store",
  });
}

/** Pull a human-readable message out of a FastAPI error body (detail may be a
 *  string or a structured `{ message }` object). */
async function errorFrom(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail ?? body?.message ?? null;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  return `${fallback} (${res.status})`;
}

// ── types ─────────────────────────────────────────────────────────────────────
export type OrgRole = "viewer" | "member" | "admin";

export type OrgContext = {
  orgId: string;
  orgName: string;
  role: OrgRole;
};

export type Member = {
  user_id: number;
  email: string;
  is_active: boolean;
  org_role: OrgRole;
  joined_at: string | null;
};

export type Invite = {
  id: number;
  email: string;
  role: OrgRole;
  status: "pending" | "accepted" | "expired" | "revoked";
  expires_at: string | null;
  accepted_at: string | null;
  created_at: string | null;
};

export type SamlMapping = {
  id: number;
  attribute_name: string;
  group_value: string;
  org_role: OrgRole;
  created_at: string | null;
};

export type HealthDeep = {
  reachable: boolean;
  status: string; // "ok" | "degraded" | "unreachable"
  httpStatus: number | null;
  version?: string;
  checks?: {
    postgres?: { ok: boolean; error: string | null };
    redis?: {
      ok: boolean;
      expected: boolean;
      configured: boolean;
      error: string | null;
    };
    worker?: {
      state: string;
      heartbeat_age_seconds: number | null;
      stale_threshold_seconds: number;
      strict: boolean;
    };
    queue?: { depth: number | null; name: string };
  };
};

export type SsoStatus = {
  backendOrigin: string;
  saml: {
    state: "reachable" | "not_enabled" | "misconfigured" | "unknown";
    httpStatus: number | null;
  };
  oidc: {
    state: "reachable" | "not_enabled" | "misconfigured" | "unknown";
    httpStatus: number | null;
  };
  urls: {
    samlAcs: string;
    samlMetadata: string;
    samlLogin: string;
    oidcLogin: string;
    oidcCallback: string;
    scimBase: string;
  };
};

export type ActionResult<T = unknown> =
  | { ok: true; data?: T }
  | { ok: false; error: string };

// ── reads ──────────────────────────────────────────────────────────────────────
export async function getOrgContext(): Promise<OrgContext | null> {
  const r = await authed("/api/v1/orgs");
  if (!r.ok) return null;
  const body = await r.json().catch(() => null);
  const orgs: Array<{
    org_id: string;
    name: string;
    org_role: OrgRole;
    is_active: boolean;
  }> = body?.organizations ?? [];
  if (orgs.length === 0) return null;
  const active =
    orgs.find((o) => o.org_id === body?.active_org_id) ??
    orgs.find((o) => o.is_active) ??
    orgs[0];
  return { orgId: active.org_id, orgName: active.name, role: active.org_role };
}

export async function listMembers(): Promise<Member[]> {
  const r = await authed("/api/v1/orgs/members");
  if (!r.ok) return [];
  const body = await r.json().catch(() => null);
  return (body?.members ?? []) as Member[];
}

export async function listInvites(): Promise<Invite[]> {
  const r = await authed("/api/v1/orgs/invites");
  if (!r.ok) return [];
  const body = await r.json().catch(() => null);
  return (body?.invites ?? []) as Invite[];
}

export async function listSamlMappings(): Promise<SamlMapping[]> {
  const r = await authed("/api/v1/orgs/saml/group-mappings");
  if (!r.ok) return [];
  const body = await r.json().catch(() => null);
  return (body?.mappings ?? []) as SamlMapping[];
}

/** `/health/deep` is NOT under `/api/v1` — probe it directly and degrade
 *  gracefully. A 503 is a real, expected state (degraded) — read the body. */
export async function getHealthDeep(): Promise<HealthDeep> {
  try {
    const res = await fetch(backendUrl("/health/deep"), { cache: "no-store" });
    const body = await res.json().catch(() => null);
    if (!body) {
      return { reachable: false, status: "unreachable", httpStatus: res.status };
    }
    return {
      reachable: true,
      status: body.status ?? (res.ok ? "ok" : "degraded"),
      httpStatus: res.status,
      version: body.version,
      checks: body.checks,
    };
  } catch {
    return { reachable: false, status: "unreachable", httpStatus: null };
  }
}

/** SSO/SCIM read-only status. The URLs are the BACKEND's IdP-facing endpoints an
 *  admin hands to their IdP; base SSO enablement is deploy-level (AUTH_MODE + IdP
 *  env). SAML gets a genuine reachability probe via the unauthenticated SP
 *  metadata route (no egress, no cookies). OIDC uses its local-only status route,
 *  which validates coordinates without contacting the external IdP. */
export async function getSsoStatus(): Promise<SsoStatus> {
  const origin = backendOrigin();
  let samlState: SsoStatus["saml"]["state"] = "unknown";
  let samlHttp: number | null = null;
  let oidcState: SsoStatus["oidc"]["state"] = "unknown";
  let oidcHttp: number | null = null;
  try {
    const res = await fetch(`${origin}/auth/saml/metadata`, {
      cache: "no-store",
      redirect: "manual",
    });
    samlHttp = res.status;
    if (res.ok) samlState = "reachable";
    else if (res.status === 404) samlState = "not_enabled";
    else samlState = "misconfigured";
  } catch {
    samlState = "unknown";
  }
  try {
    const res = await fetch(`${origin}/auth/oidc/status`, {
      cache: "no-store",
      redirect: "manual",
    });
    oidcHttp = res.status;
    if (res.ok) oidcState = "reachable";
    else if (res.status === 404) oidcState = "not_enabled";
    else oidcState = "misconfigured";
  } catch {
    oidcState = "unknown";
  }
  return {
    backendOrigin: origin,
    saml: { state: samlState, httpStatus: samlHttp },
    oidc: { state: oidcState, httpStatus: oidcHttp },
    urls: {
      samlAcs: `${origin}/auth/saml/acs`,
      samlMetadata: `${origin}/auth/saml/metadata`,
      samlLogin: `${origin}/auth/saml/login`,
      oidcLogin: `${origin}/auth/oidc/login`,
      oidcCallback: `${origin}/auth/oidc/callback`,
      scimBase: `${origin}/scim/v2`,
    },
  };
}

// ── mutations ────────────────────────────────────────────────────────────────
export async function createInvite(
  email: string,
  role: OrgRole
): Promise<ActionResult<{ accept_link: string; emailed: boolean }>> {
  const r = await authed("/api/v1/orgs/invites", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
  if (!r.ok) return { ok: false, error: await errorFrom(r, "Could not create invite") };
  const body = await r.json().catch(() => ({}));
  revalidatePath(ORG_SETTINGS_PATH);
  return {
    ok: true,
    data: { accept_link: body.accept_link ?? "", emailed: !!body.emailed },
  };
}

export async function revokeInvite(inviteId: number): Promise<ActionResult> {
  const r = await authed(`/api/v1/orgs/invites/${inviteId}`, { method: "DELETE" });
  if (!r.ok) return { ok: false, error: await errorFrom(r, "Could not revoke invite") };
  revalidatePath(ORG_SETTINGS_PATH);
  return { ok: true };
}

export async function removeMember(userId: number): Promise<ActionResult> {
  const r = await authed(`/api/v1/orgs/members/${userId}`, { method: "DELETE" });
  if (!r.ok) return { ok: false, error: await errorFrom(r, "Could not remove member") };
  revalidatePath(ORG_SETTINGS_PATH);
  return { ok: true };
}

export async function createSamlMapping(
  attributeName: string,
  groupValue: string,
  orgRole: OrgRole
): Promise<ActionResult> {
  const r = await authed("/api/v1/orgs/saml/group-mappings", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      attribute_name: attributeName,
      group_value: groupValue,
      org_role: orgRole,
    }),
  });
  if (!r.ok) return { ok: false, error: await errorFrom(r, "Could not add mapping") };
  revalidatePath(ORG_SETTINGS_PATH);
  return { ok: true };
}

export async function deleteSamlMapping(mappingId: number): Promise<ActionResult> {
  const r = await authed(`/api/v1/orgs/saml/group-mappings/${mappingId}`, {
    method: "DELETE",
  });
  if (!r.ok) return { ok: false, error: await errorFrom(r, "Could not delete mapping") };
  revalidatePath(ORG_SETTINGS_PATH);
  return { ok: true };
}
