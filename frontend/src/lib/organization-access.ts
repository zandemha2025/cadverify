export type OrganizationRole = "viewer" | "member" | "admin";

export type OrganizationSummary = {
  orgId: string;
  orgName: string;
  role: OrganizationRole;
  isActive: boolean;
};

export type OrganizationAccess = {
  activeOrgId: string | null;
  organizations: OrganizationSummary[];
};

const ORGANIZATION_ROLES = new Set<OrganizationRole>([
  "viewer",
  "member",
  "admin",
]);

/** Parse the authenticated `/api/v1/orgs` response without turning malformed
 * or contradictory organization state into an honest-looking empty tenant. */
export function parseOrganizationAccess(value: unknown): OrganizationAccess | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (!Array.isArray(raw.organizations)) return null;
  if (raw.active_org_id !== null && typeof raw.active_org_id !== "string") return null;
  if (typeof raw.active_org_id === "string" && !raw.active_org_id.trim()) return null;

  const organizations: OrganizationSummary[] = [];
  const ids = new Set<string>();
  for (const entry of raw.organizations) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
    const org = entry as Record<string, unknown>;
    if (
      typeof org.org_id !== "string" || !org.org_id.trim() ||
      typeof org.name !== "string" || !org.name.trim() ||
      typeof org.org_role !== "string" ||
      !ORGANIZATION_ROLES.has(org.org_role as OrganizationRole) ||
      typeof org.is_active !== "boolean" ||
      ids.has(org.org_id)
    ) {
      return null;
    }
    ids.add(org.org_id);
    organizations.push({
      orgId: org.org_id,
      orgName: org.name,
      role: org.org_role as OrganizationRole,
      isActive: org.is_active,
    });
  }

  const markedActive = organizations.filter((org) => org.isActive);
  if (markedActive.length > 1) return null;
  let activeOrgId = raw.active_org_id as string | null;
  if (activeOrgId && !ids.has(activeOrgId)) return null;
  if (!activeOrgId && markedActive.length === 1) activeOrgId = markedActive[0].orgId;
  if (
    activeOrgId &&
    markedActive.length === 1 &&
    markedActive[0].orgId !== activeOrgId
  ) {
    return null;
  }

  return {
    activeOrgId,
    organizations: organizations.map((org) => ({
      ...org,
      isActive: org.orgId === activeOrgId,
    })),
  };
}
