/**
 * Data Access Layer — the REAL (secure) session gate (SERVER ONLY).
 *
 * `getUser()` forwards the first-party cookie to the backend `GET /auth/me`,
 * which validates the HMAC signature + expiry and returns the user (or 401).
 * `verifySession()` is the hard gate used by the (app) server layout: it
 * redirects to /login when there is no valid session. Memoized per-request with
 * React `cache` so a single render only hits the backend once.
 * Verification failures throw to the existing retry boundary; they are not
 * evidence that the caller's credentials were rejected.
 *
 * Imports `next/headers` (via ./session) → server-only by construction.
 */
import { cache } from "react";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getSessionToken } from "./session";
import { backendUrl } from "./api-base";
import { loginHrefForReturnPath } from "./safe-return-path";
import {
  parseOrganizationAccess,
  type OrganizationAccess,
} from "./organization-access";

export type SessionUser = {
  id: number;
  email: string;
  role: string;
  auth_provider: string;
  has_password?: boolean;
};

export const getUser = cache(async (): Promise<SessionUser | null> => {
  const token = await getSessionToken();
  if (!token) return null;
  const res = await fetch(backendUrl("/auth/me"), {
    headers: { Cookie: `dash_session=${token}` },
    cache: "no-store",
    signal: AbortSignal.timeout(55_000),
  });
  if (res.status === 401 || res.status === 403) return null;
  if (!res.ok) throw new Error(`Session verification failed (${res.status})`);
  const user = await res.json();
  if (
    !user || !Number.isSafeInteger(user.id) || user.id <= 0 ||
    typeof user.email !== "string" || !user.email.trim() ||
    typeof user.role !== "string" || !user.role.trim() ||
    typeof user.auth_provider !== "string" || !user.auth_provider.trim() ||
    (user.has_password !== undefined && typeof user.has_password !== "boolean")
  ) throw new Error("Invalid session verification response");
  return user as SessionUser;
});

export const verifySession = cache(async (): Promise<SessionUser> => {
  const user = await getUser();
  if (!user) {
    const requestedPath = (await headers()).get("x-proofshape-request-path");
    redirect(loginHrefForReturnPath(requestedPath));
  }
  return user;
});

/** Server-side organization boundary for org-scoped product surfaces. `null`
 * means the boundary could not be verified; an object with no organizations is
 * a real signed-in account that has not joined a workspace yet. */
export const getSessionOrganizationAccess = cache(
  async (): Promise<OrganizationAccess | null> => {
    const token = await getSessionToken();
    if (!token) return null;
    try {
      const res = await fetch(backendUrl("/api/v1/orgs"), {
        headers: { Cookie: `dash_session=${token}` },
        cache: "no-store",
      });
      if (!res.ok) return null;
      return parseOrganizationAccess(await res.json());
    } catch {
      return null;
    }
  },
);
