/** Same-origin magic-link start with authenticated client-IP forwarding. */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as {
    email?: unknown;
    turnstileToken?: unknown;
  };
  if (
    typeof body.email !== "string" ||
    body.email.length > 320 ||
    typeof body.turnstileToken !== "string" ||
    body.turnstileToken.length < 1 ||
    body.turnstileToken.length > 4096
  ) {
    return NextResponse.json(
      { detail: { message: "Enter an email and complete the security check." } },
      { status: 400, headers: { "cache-control": "no-store" } },
    );
  }

  const backendPath = "/auth/magic/start";
  const form = new FormData();
  form.set("email", body.email);
  form.set("cf_turnstile_response", body.turnstileToken);
  try {
    const res = await fetch(backendUrl(backendPath), {
      method: "POST",
      headers: signedAuthProxyHeaders(req, backendPath),
      body: form,
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, {
      status: res.status,
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { detail: { message: "Email delivery is temporarily unavailable." } },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
