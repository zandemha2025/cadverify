/**
 * Data Access Layer — the REAL (secure) session gate (SERVER ONLY).
 *
 * `getUser()` forwards the first-party cookie to the backend `GET /auth/me`,
 * which validates the HMAC signature + expiry and returns the user (or 401).
 * `verifySession()` is the hard gate used by the (app) server layout: it
 * redirects to /login when there is no valid session. Memoized per-request with
 * React `cache` so a single render only hits the backend once.
 *
 * Imports `next/headers` (via ./session) → server-only by construction.
 */
import { cache } from "react";
import { redirect } from "next/navigation";
import { getSessionToken } from "./session";
import { backendUrl } from "./api-base";

export type SessionUser = {
  id: number;
  email: string;
  role: string;
  auth_provider: string;
};

export const getUser = cache(async (): Promise<SessionUser | null> => {
  const token = await getSessionToken();
  if (!token) return null;
  try {
    const res = await fetch(backendUrl("/auth/me"), {
      headers: { Cookie: `dash_session=${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as SessionUser;
  } catch {
    return null;
  }
});

export const verifySession = cache(async (): Promise<SessionUser> => {
  const user = await getUser();
  if (!user) redirect("/login");
  return user;
});
