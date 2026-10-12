import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { getSessionToken } from "@/lib/session";

export async function POST(req: Request) {
  const token = await getSessionToken();
  if (!token) return NextResponse.json({ ok: false }, { status: 401, headers: { "cache-control": "no-store" } });
  try {
    const response = await fetch(backendUrl("/auth/me/profile"), {
      method: "POST", headers: { "content-type": "application/json", cookie: `dash_session=${token}` },
      body: JSON.stringify(await req.json()), cache: "no-store", signal: AbortSignal.timeout(10_000),
    });
    return NextResponse.json({ ok: response.ok }, { status: response.status, headers: { "cache-control": "no-store" } });
  } catch {
    return NextResponse.json({ ok: false }, { status: 503, headers: { "cache-control": "no-store" } });
  }
}
