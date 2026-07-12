/** Public pilot-intake bridge with signed client-IP forwarding. */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";

export const dynamic = "force-dynamic";

const DEV_RELEASES = new Set(["", "dev", "development", "local", "test", "ci"]);
const DEPLOYMENTS = new Set(["undecided", "cloud", "vpc", "air-gapped"]);
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function message(status: number, text: string) {
  return NextResponse.json(
    { detail: { message: text } },
    { status, headers: { "cache-control": "no-store" } },
  );
}

export async function GET() {
  const release = (process.env.RELEASE || "dev").trim().toLowerCase();
  const released = !DEV_RELEASES.has(release);
  const siteKey = (process.env.TURNSTILE_SITE_KEY || "").trim();
  if (released && (siteKey.length < 10 || /\s/.test(siteKey))) {
    return message(503, "Online intake is temporarily unavailable. Please retry later.");
  }
  return NextResponse.json(
    { turnstileSiteKey: siteKey || null },
    { headers: { "cache-control": "no-store" } },
  );
}

export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const requestId = body.requestId;
  const email = body.email;
  const company = body.company;
  const what = body.what;
  const deployment = body.deployment;
  const turnstileToken = body.turnstileToken;
  const website = body.website;
  if (
    typeof requestId !== "string" || !UUID_RE.test(requestId) ||
    typeof email !== "string" || email.length < 3 || email.length > 320 ||
    typeof company !== "string" || company.trim().length < 1 || company.length > 160 ||
    typeof what !== "string" || what.trim().length < 1 || what.length > 2000 ||
    typeof deployment !== "string" || !DEPLOYMENTS.has(deployment) ||
    (turnstileToken !== null && turnstileToken !== undefined &&
      (typeof turnstileToken !== "string" || turnstileToken.length > 4096)) ||
    typeof website !== "string" || website.length > 200
  ) {
    return message(400, "Complete every required field, then try again.");
  }

  const backendPath = "/auth/pilot-request";
  const headers: Record<string, string> = {
    "content-type": "application/json",
    ...signedAuthProxyHeaders(req, backendPath),
  };
  const userAgent = req.headers.get("user-agent");
  if (userAgent) headers["user-agent"] = userAgent.slice(0, 500);

  try {
    const res = await fetch(backendUrl(backendPath), {
      method: "POST",
      headers,
      body: JSON.stringify({
        request_id: requestId,
        email,
        company,
        what,
        deployment,
        turnstile_token: turnstileToken || null,
        website,
      }),
      cache: "no-store",
    });
    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, {
      status: res.status,
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return message(503, "Could not reach online intake. Please retry later.");
  }
}
