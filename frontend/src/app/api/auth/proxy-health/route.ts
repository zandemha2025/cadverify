/** Deploy-time proof that the web and API auth-proxy secrets match. */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const backendPath = "/auth/proxy-health";
  try {
    const res = await fetch(backendUrl(backendPath), {
      method: "GET",
      headers: signedAuthProxyHeaders(req, backendPath),
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(
        { ok: false },
        { status: 503, headers: { "cache-control": "no-store" } },
      );
    }
    return NextResponse.json(
      { ok: true },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { ok: false },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
