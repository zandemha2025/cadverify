/**
 * What an invite link is for, before its holder signs in: the organization,
 * the role, who sent it, the invited address and when it expires. Same-origin
 * POST (the token stays out of URLs and logs) relayed to the API's public
 * invite summary; no session needed, because the emailed link is the secret.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { crossSiteRefusal } from "@/lib/same-origin-request";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const crossSite = crossSiteRefusal(req);
  if (crossSite) return crossSite;
  const body = (await req.json().catch(() => ({}))) as { token?: unknown };
  const token = typeof body.token === "string" ? body.token.trim() : "";
  if (!token || token.length > 512) {
    return NextResponse.json({ detail: { message: "The link is missing its code." } }, { status: 400, headers: { "cache-control": "no-store" } });
  }
  try {
    const res = await fetch(backendUrl("/api/v1/orgs/invites/summary"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status, headers: { "cache-control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: { message: "Could not reach ScaleCAD." } }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}
