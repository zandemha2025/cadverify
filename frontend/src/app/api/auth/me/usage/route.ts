/**
 * Same-origin read of the caller's own trial usage for the /history quota
 * card. Mirrors the dedicated auth handlers (login/signup/logout): the browser
 * never holds the backend token - this server route forwards the first-party
 * dash_session cookie to the backend `GET /auth/me/usage` and relays status +
 * body verbatim, so the card always agrees with the server-side gate.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { getSessionToken } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function GET() {
  const token = await getSessionToken();
  if (!token) {
    return NextResponse.json(
      { detail: { code: "dashboard_auth_required", message: "Dashboard session required." } },
      { status: 401, headers: { "cache-control": "no-store" } },
    );
  }
  try {
    const res = await fetch(backendUrl("/auth/me/usage"), {
      method: "GET",
      headers: { cookie: `dash_session=${token}` },
      cache: "no-store",
    });
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: { code: "usage_unavailable", message: "Usage data is temporarily unavailable." } },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
