/**
 * Same-origin signup. Proxies credentials and profile fields; on success sets
 * the first-party httpOnly `dash_session` cookie (auto-login). The session token
 * is never exposed to browser JS.
 *
 * Signing up from an invite (`invite_token`): once the account exists it
 * accepts the invite with the new session, so the person joins the inviting
 * organization with the invited role, and asks to make it their active org
 * (signing up from the invite is that choice; accepting alone never switches).
 * The API still binds the invite to the invited address; if it refuses, the
 * account stays and the answer says why (`invite.error`).
 *
 * An organization that requires two-step sign-in ends the new session at the
 * join (the account has no two-step yet). The handler then signs in again with
 * the credentials just typed, which answers with a setup challenge: it goes in
 * the httpOnly cookie and the browser goes to two-step setup, then the org. If
 * that sign-in fails, the answer says `signed_out` and the browser goes to sign
 * in; it never keeps a dead session or fails silently.
 */
import { NextResponse } from "next/server";
import { backendUrl } from "@/lib/api-base";
import { signedAuthProxyHeaders } from "@/lib/auth-proxy";
import { clearSession, setSession } from "@/lib/session";
import { isChallenge, setTwoStepChallenge } from "@/lib/two-step-cookie";
import { crossSiteRefusal } from "@/lib/same-origin-request";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const crossSite = crossSiteRefusal(req);
  if (crossSite) return crossSite;
  const raw = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  const { invite_token: inviteRaw, ...body } = raw ?? {};
  const inviteToken = typeof inviteRaw === "string" && inviteRaw.trim() && inviteRaw.length <= 512 ? inviteRaw.trim() : null;
  const backendPath = "/auth/signup";
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
    const invite = inviteToken ? await acceptInvite(data.session, inviteToken) : undefined;
    // Joining an organization that requires two-step sign-in ended the new
    // session: sign in again for its setup challenge, else send them to sign in.
    let twoStep: "setup" | null = null;
    let signedOut = false;
    if (invite && "org_id" in invite && invite.signed_out) {
      await clearSession();
      twoStep = await setupChallenge(req, body.email, body.password);
      signedOut = twoStep === null;
    }
    return NextResponse.json(
      {
        user: data.user,
        ...(invite ? { invite } : {}),
        ...(twoStep ? { two_step: twoStep } : {}),
        ...(signedOut ? { signed_out: true } : {}),
      },
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

type InviteOutcome = { org_id: string; org_role: string; signed_out: boolean } | { error: string };

/** Accept the invite as the account just made, and make its org active; never throws. */
async function acceptInvite(session: string, token: string): Promise<InviteOutcome> {
  try {
    const res = await fetch(backendUrl("/api/v1/orgs/invites/accept"), {
      method: "POST",
      headers: { "content-type": "application/json", Cookie: `dash_session=${session}` },
      body: JSON.stringify({ token, switch: true }),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    const data = (await res.json().catch(() => ({}))) as { org_id?: unknown; org_role?: unknown; signed_out?: unknown; detail?: unknown; message?: unknown };
    if (res.ok && typeof data.org_id === "string") {
      return { org_id: data.org_id, org_role: String(data.org_role ?? "member"), signed_out: data.signed_out === true };
    }
    const d = data.detail as { message?: unknown } | string | undefined;
    const message = typeof d === "string" ? d : typeof d?.message === "string" ? d.message : typeof data.message === "string" ? data.message : null;
    return { error: message ?? "The invite wasn’t accepted." };
  } catch {
    return { error: "Couldn’t reach ScaleCAD to accept the invite." };
  }
}

/**
 * The join ended the session: sign in again with the credentials just typed.
 * The API answers with a two-step setup challenge (never a session) for an
 * account in an organization that requires it; the challenge goes in the
 * httpOnly cookie. "setup" on success, null for any other answer.
 */
async function setupChallenge(req: Request, email: unknown, password: unknown): Promise<"setup" | null> {
  if (typeof email !== "string" || typeof password !== "string") return null;
  const path = "/auth/login";
  try {
    const res = await fetch(backendUrl(path), {
      method: "POST",
      headers: { "content-type": "application/json", ...signedAuthProxyHeaders(req, path) },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    const data = (await res.json().catch(() => ({}))) as { two_step?: unknown; challenge?: unknown };
    if (!res.ok || data.two_step !== "setup" || !isChallenge(data.challenge)) return null;
    await setTwoStepChallenge(data.challenge);
    return "setup";
  } catch {
    return null;
  }
}
