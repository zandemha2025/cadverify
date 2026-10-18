"use server";
/**
 * Create or rotate an API key from the v4 API page and hand its one-time
 * secret to this page only.
 *
 * The backend delivers a new key's secret once, in a short-lived `cv_mint_once`
 * cookie scoped to the old page's path (/settings/developer), which the v4 page
 * at /app/account/api can't read. This action calls the backend server-side
 * with the session cookie, takes the secret from that cookie, and re-issues it
 * the same way: a 60-second `cv_mint_once` cookie scoped to the v4 page's path,
 * which the page reads once and deletes. The secret never appears in a
 * response body, and nothing stores it.
 */
import { cookies } from "next/headers";
import { backendUrl } from "@/lib/api-base";

const REVEAL = "cv_mint_once";
const API_PAGE = "/app/account/api";

export type MintResult = { ok: true; id: number; prefix: string } | { ok: false; status: number; error: string };

function problem(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const d = (body as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") return (d as { message: string }).message;
  return null;
}

/** The secret from the backend's Set-Cookie headers, if it sent one. */
function revealed(headers: Headers): string | null {
  const all = typeof headers.getSetCookie === "function" ? headers.getSetCookie() : [headers.get("set-cookie") ?? ""];
  for (const line of all) {
    const m = /^\s*cv_mint_once=("?)([A-Za-z0-9_\-]+)\1\s*(;|$)/.exec(line);
    if (m) return m[2];
  }
  return null;
}

export async function mintKey(op: { kind: "create"; name: string } | { kind: "rotate"; id: number }): Promise<MintResult> {
  const jar = await cookies();
  const session = jar.get("dash_session")?.value;
  if (!session) return { ok: false, status: 401, error: "Sign in again to manage keys." };

  let path: string;
  let body: string | undefined;
  if (op.kind === "create") {
    const name = (typeof op.name === "string" ? op.name : "").trim().slice(0, 80) || "Default";
    path = "/api/v1/keys";
    body = JSON.stringify({ name });
  } else {
    if (!Number.isSafeInteger(op.id) || op.id <= 0) return { ok: false, status: 400, error: "That key isn’t available. Reload and try again." };
    path = `/api/v1/keys/${op.id}/rotate`;
  }

  let res: Response;
  try {
    res = await fetch(backendUrl(path), {
      method: "POST",
      headers: { Cookie: `dash_session=${session}`, ...(body ? { "content-type": "application/json" } : {}) },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
  } catch {
    return { ok: false, status: 503, error: "Couldn’t reach ScaleCAD. Nothing changed." };
  }
  const data = (await res.json().catch(() => null)) as { id?: unknown; prefix?: unknown } | null;
  if (!res.ok) {
    return { ok: false, status: res.status, error: problem(data) ?? (op.kind === "create" ? `Key not created (${res.status}).` : `Key not rotated (${res.status}).`) };
  }
  const secret = revealed(res.headers);
  if (!secret) {
    return { ok: false, status: 502, error: "The key was made but its secret didn’t arrive. Revoke it and create another." };
  }
  jar.set(REVEAL, secret, { path: API_PAGE, maxAge: 60, secure: true, httpOnly: false, sameSite: "lax" });
  return { ok: true, id: Number(data?.id), prefix: String(data?.prefix ?? "") };
}
