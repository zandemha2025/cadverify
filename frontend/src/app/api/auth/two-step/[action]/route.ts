/**
 * Two-step sign-in, relayed server to server.
 *
 * Sign-in actions (no session yet) read the httpOnly challenge cookie set by
 * /api/auth/login, /api/auth/magic/exchange or the Google callback, and send it
 * with the code. Account actions forward the first-party session cookie. When
 * the backend answers with a session (sign-in finished, two-step turned on,
 * other browsers signed out), this handler sets the `dash_session` cookie
 * itself and strips the token: browser JavaScript never sees it.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { crossSiteRefusal } from "@/lib/same-origin-request";
import { getSessionToken, setSession } from "@/lib/session";
import { clearTwoStepChallenge, getTwoStepChallenge } from "@/lib/two-step-cookie";

export const dynamic = "force-dynamic";

type Action = {
  path: string;
  methods: ("GET" | "POST" | "PUT")[];
  /** "challenge": sign-in in progress; "session": a signed-in account. */
  auth: "challenge" | "session";
  /** The sign-in is complete once this answers with a session. */
  finishes?: boolean;
};

const ACTIONS: Record<string, Action> = {
  state: { path: "/auth/two-step/challenge/state", methods: ["POST"], auth: "challenge" },
  verify: { path: "/auth/two-step/challenge/verify", methods: ["POST"], auth: "challenge", finishes: true },
  setup: { path: "/auth/two-step/challenge/setup", methods: ["POST"], auth: "challenge" },
  "setup-confirm": { path: "/auth/two-step/challenge/setup/confirm", methods: ["POST"], auth: "challenge", finishes: true },
  status: { path: "/auth/two-step", methods: ["GET"], auth: "session" },
  enrol: { path: "/auth/two-step/enrol", methods: ["POST"], auth: "session" },
  "enrol-confirm": { path: "/auth/two-step/enrol/confirm", methods: ["POST"], auth: "session" },
  disable: { path: "/auth/two-step/disable", methods: ["POST"], auth: "session" },
  "recovery-codes": { path: "/auth/two-step/recovery-codes", methods: ["POST"], auth: "session" },
  org: { path: "/auth/two-step/org", methods: ["GET", "PUT"], auth: "session" },
  "sign-out-others": { path: "/auth/sessions/sign-out-others", methods: ["POST"], auth: "session" },
};

const NO_STORE = { "cache-control": "no-store" };

function fail(status: number, message: string, code?: string) {
  return NextResponse.json({ detail: { message, ...(code ? { code } : {}) } }, { status, headers: NO_STORE });
}

async function handle(req: Request, ctx: { params: Promise<{ action: string }> }): Promise<Response> {
  const { action } = await ctx.params;
  const spec = Object.prototype.hasOwnProperty.call(ACTIONS, action) ? ACTIONS[action] : undefined;
  const method = req.method.toUpperCase() as "GET" | "POST" | "PUT";
  if (!spec) return fail(404, "Not found.");
  if (!spec.methods.includes(method)) return fail(405, "Method not allowed.");
  if (method !== "GET") {
    const crossSite = crossSiteRefusal(req);
    if (crossSite) return crossSite;
  }

  const headers: Record<string, string> = { ...signedAuthProxyHeaders(req, spec.path) };
  let body: Record<string, unknown> | undefined;
  if (method !== "GET") {
    const raw = await req.json().catch(() => ({}));
    body = raw && typeof raw === "object" && !Array.isArray(raw) ? { ...(raw as Record<string, unknown>) } : {};
    delete body.challenge;
    delete body.session;
    headers["content-type"] = "application/json";
  }
  if (spec.auth === "challenge") {
    const challenge = await getTwoStepChallenge();
    if (!challenge) return fail(401, "This sign-in expired after 10 minutes. Sign in again.", "two_step_challenge_invalid");
    body = { ...(body ?? {}), challenge };
  } else {
    const token = await getSessionToken();
    if (!token) return fail(401, "Dashboard session required.", "dashboard_auth_required");
    headers.Cookie = `dash_session=${token}`;
  }

  let res: Response;
  try {
    res = await fetch(backendUrl(spec.path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(55_000),
    });
  } catch {
    return fail(503, "Could not reach the sign-in service. Try again.");
  }
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    // A challenge the backend no longer accepts is spent: drop the cookie.
    const code = (data?.detail as { code?: unknown } | undefined)?.code;
    if (spec.auth === "challenge" && (code === "two_step_challenge_invalid" || res.status === 403)) {
      await clearTwoStepChallenge();
    }
    return NextResponse.json(data, { status: res.status, headers: NO_STORE });
  }
  if (typeof data.session === "string") {
    if (data.session.length < 32 || data.session.length > 4096) return fail(502, "Could not establish a secure session.");
    await setSession(data.session);
    delete data.session;
  }
  if (spec.finishes) await clearTwoStepChallenge();
  return NextResponse.json(data, { headers: NO_STORE });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
