/**
 * Same-origin login. The browser POSTs {email,password} here; we proxy to the
 * backend and, on success, set the first-party httpOnly `dash_session` cookie.
 * The session token is NEVER returned to the browser JS.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { setSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const res = await fetch(backendUrl("/auth/login"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data?.session) {
    return NextResponse.json(data, { status: res.ok ? 502 : res.status });
  }
  await setSession(data.session);
  return NextResponse.json({ user: data.user });
}
