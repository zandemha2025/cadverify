/**
 * Same-origin login. The browser POSTs {email,password} here; we proxy to the
 * backend and, on success, set the first-party httpOnly `dash_session` cookie.
 * The session token is NEVER returned to the browser JS.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { setSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const backendPath = "/auth/login";
  try {
    const res = await fetch(backendUrl(backendPath), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...signedAuthProxyHeaders(req, backendPath),
      },
      body: JSON.stringify(body),
      cache: "no-store",
      // Cold starts on the free backend tier can take over a minute; without a
      // deadline the browser waits forever on "Working...". Fail honestly
      // inside Vercel's function limit instead.
      signal: AbortSignal.timeout(55_000),
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
  } catch (err) {
    const timedOut =
      err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
    return NextResponse.json(
      {
        detail: {
          message: timedOut
            ? "The service is waking up. Try again in a minute."
            : "Could not reach the authentication service.",
        },
      },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
