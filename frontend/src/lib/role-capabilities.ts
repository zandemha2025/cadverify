/**
 * Client-side presentation gates derived from the authoritative session role.
 *
 * The backend remains the security boundary. These helpers keep read-only users
 * from seeing controls that the backend will reject, and deliberately fail
 * closed for missing or future/unknown roles.
 */
const WORKSPACE_MUTATION_ROLES = new Set(["analyst", "admin", "superadmin"]);

export function canMutateWorkspace(role: string | null | undefined): boolean {
  return typeof role === "string" && WORKSPACE_MUTATION_ROLES.has(role);
}
