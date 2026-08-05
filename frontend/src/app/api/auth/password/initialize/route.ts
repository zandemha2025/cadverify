/** Set an initial password only after a first-party verified session exists. */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { getSessionToken, setSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const session = await getSessionToken();
  if (!session) {
    return NextResponse.json(
      { detail: { message: "Sign in with your email link first." } },
      { status: 401, headers: { "cache-control": "no-store" } },
    );
  }
  const body = await req.json().catch(() => ({}));
  try {
    const res = await fetch(backendUrl("/auth/password/initialize"), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        Cookie: `dash_session=${session}`,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data = (await res.json().catch(() => ({}))) as {
      session?: unknown;
      detail?: unknown;
    };
    if (!res.ok) {
      return NextResponse.json(data, {
        status: res.status,
        headers: { "cache-control": "no-store" },
      });
    }
    if (typeof data.session !== "string" || data.session.length < 32) {
      return NextResponse.json(
        { detail: { message: "Could not rotate the secure session." } },
        { status: 502, headers: { "cache-control": "no-store" } },
      );
    }
    await setSession(data.session);
    return NextResponse.json(
      { ok: true },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { detail: { message: "Could not configure the password." } },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
