/**
 * First-party session cookie helpers (SERVER ONLY).
 *
 * Single source of truth for the cookie name + attributes. The Next.js server
 * (never browser JS) owns this httpOnly cookie. The token itself is the backend's
 * HMAC-signed `dash_session` value (issued by /auth/login|signup); we only store
 * and forward it — we never mint or read its contents here.
 *
 * NOTE: this module imports `next/headers`, which makes it server-only by
 * construction (importing it into a client component throws at build time).
 */
import { cookies } from "next/headers";

export const SESSION_COOKIE = "dash_session";
const THIRTY_DAYS = 60 * 60 * 24 * 30;

export async function setSession(token: string): Promise<void> {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    // http://localhost is not https, so Secure must be off in dev or the cookie
    // is silently dropped. Production (https) gets Secure.
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: THIRTY_DAYS,
  });
}

export async function clearSession(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
}

export async function getSessionToken(): Promise<string | null> {
  return (await cookies()).get(SESSION_COOKIE)?.value ?? null;
}
