/**
 * The server-rendered share pages' read (/s/{id}, /s/cost/{id}, /s/pkg/{id}).
 *
 * The API limits share views per visitor IP. Rendered here, the call comes
 * from this web server, so without the signed visitor IP every visitor of
 * every link would count against this server's one bucket, and one anonymous
 * client could use it up for everyone (security review R4, F3). This read signs
 * the incoming visitor's IP for the exact backend path, as /api/public-share
 * does for browser reads. Server only: it reads the incoming request headers.
 */
import "server-only";

import { headers } from "next/headers";
import { backendUrl } from "../../../lib/api-base.ts";
import { signedAuthProxyHeaders } from "../../../lib/auth-proxy.ts";

export type PublicShare<T> =
  | { ok: true; data: T }
  | { ok: false; reason: "expired" | "off" | "missing" | "error"; endedAt: string | null };

/** A shared link's payload, or why it can't be shown (410 ended / switched off, 404 unknown). */
export async function readPublicShare<T>(path: `/s/${string}`): Promise<PublicShare<T>> {
  let res: Response;
  try {
    const visitor = { method: "GET", headers: await headers() };
    res = await fetch(backendUrl(path), {
      headers: signedAuthProxyHeaders(visitor, path),
      cache: "no-store",
      redirect: "error",
    });
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
