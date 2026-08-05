/**
 * Same-origin signup. Proxies {email,password} to the backend; on success sets
 * the first-party httpOnly `dash_session` cookie (auto-login). The session token
 * is never exposed to browser JS.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { setSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const backendPath = "/auth/signup";
  try {
    const res = await fetch(backendUrl(backendPath), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...signedAuthProxyHeaders(req, backendPath),
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    if (
      !res.ok ||
      typeof data?.session !== "string" ||
      data.session.length < 32 ||
      data.session.length > 4096
    ) {
      return NextResponse.json(data, {
        status: res.ok ? 502 : res.status,
        headers: { "cache-control": "no-store" },
      });
    }
    await setSession(data.session);
    return NextResponse.json(
      { user: data.user },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { detail: { message: "Could not reach the authentication service." } },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
