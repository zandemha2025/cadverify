/**
 * Consume a one-time email token server-to-server, then set first-party
 * session/reveal cookies. Neither secret is returned to browser JavaScript.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { setRevealOnce, setSession } from "@/lib/session";
import { crossSiteRefusal } from "@/lib/same-origin-request";
import { isChallenge, isPurpose, setTwoStepChallenge } from "@/lib/two-step-cookie";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const crossSite = crossSiteRefusal(req);
  if (crossSite) return crossSite;
  const body = (await req.json().catch(() => ({}))) as { token?: unknown };
  if (
    typeof body.token !== "string" ||
    body.token.length < 32 ||
    body.token.length > 4096
  ) {
    return NextResponse.json(
      { detail: { message: "Magic link invalid or expired." } },
      { status: 400, headers: { "cache-control": "no-store" } },
    );
  }

  const backendPath = "/auth/magic/exchange";
  try {
    const res = await fetch(backendUrl(backendPath), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...signedAuthProxyHeaders(req, backendPath),
      },
      body: JSON.stringify({ token: body.token }),
      cache: "no-store",
    });
    const data = (await res.json().catch(() => ({}))) as {
      session?: unknown;
      mint_once?: unknown;
      key_prefix?: unknown;
      detail?: unknown;
      two_step?: unknown;
      challenge?: unknown;
    };
    if (!res.ok) {
      return NextResponse.json(data, {
        status: res.status,
        headers: { "cache-control": "no-store" },
      });
    }
    // Two-step sign-in owed: keep the challenge server-side, ask for the code.
    if (isPurpose(data.two_step) && isChallenge(data.challenge)) {
      await setTwoStepChallenge(data.challenge);
      return NextResponse.json(
        { two_step: data.two_step, redirect: "/login/two-step" },
        { headers: { "cache-control": "no-store" } },
      );
    }
    if (typeof data.session !== "string" || data.session.length < 32) {
      return NextResponse.json(
        { detail: { message: "Could not establish a secure session." } },
        { status: 502, headers: { "cache-control": "no-store" } },
      );
    }

    await setSession(data.session);
    let redirect = "/verify";
    if (
      typeof data.mint_once === "string" &&
      data.mint_once.startsWith("cv_") &&
      data.mint_once.length <= 512 &&
      typeof data.key_prefix === "string" &&
      data.key_prefix.length <= 128
    ) {
      await setRevealOnce(data.mint_once);
      redirect = `/settings/developer?new=1&prefix=${encodeURIComponent(data.key_prefix)}`;
    }
    return NextResponse.json(
      { redirect },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { detail: { message: "Could not establish a secure session." } },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
